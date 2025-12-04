"""
Task management endpoints for HakuRiver Host.

This module provides API endpoints for task lifecycle management including:
- Task submission (both command and VPS types)
- Status queries and listing
- Task control (kill, pause, resume)
- Output retrieval (stdout/stderr)
"""

import asyncio
import datetime
import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.docker.naming import task_container_name, vps_container_name
from kohakuriver.host.config import config
from kohakuriver.host.services.node_manager import (
    find_suitable_node,
    get_node_available_cores,
    get_node_available_gpus,
    get_node_available_memory,
)
from kohakuriver.host.services.task_scheduler import (
    mark_task_killed,
    send_kill_to_runner,
    send_pause_to_runner,
    send_resume_to_runner,
    send_task_to_runner,
    send_vps_task_to_runner,
    update_task_status,
)
from kohakuriver.models.requests import TaskResponse, TaskStatusUpdate, TaskSubmission
from kohakuriver.utils.logger import get_logger
from kohakuriver.utils.snowflake import generate_snowflake_id

logger = get_logger(__name__)


# =============================================================================
# Router Setup
# =============================================================================

router = APIRouter()

# Background tasks tracking
background_tasks: set[asyncio.Task] = set()


# =============================================================================
# SSH Port Allocation
# =============================================================================


def allocate_ssh_port() -> int:
    """
    Allocate a unique SSH port for VPS sessions.

    Scans existing active VPS tasks and returns the next available port
    starting from 2222.

    Returns:
        Available SSH port number.
    """
    existing_ports = set()
    active_vps = Task.select(Task.ssh_port).where(
        (Task.task_type == "vps")
        & (Task.status.in_(["pending", "assigning", "running", "paused"]))
        & (Task.ssh_port.is_null(False))
    )

    for vps in active_vps:
        if vps.ssh_port:
            existing_ports.add(vps.ssh_port)

    port = 2222
    while port in existing_ports:
        port += 1

    logger.debug(f"Allocated SSH port: {port}")
    return port


# =============================================================================
# Task Submission
# =============================================================================


@router.post("/submit", status_code=202)
async def submit_task(req: TaskSubmission):
    """
    Submit a task for execution on the cluster.

    Handles both 'command' and 'vps' task types. Tasks can be submitted
    to specific nodes or auto-scheduled to suitable nodes.

    Args:
        req: Task submission request containing command, resources, and targets.

    Returns:
        Response with created task IDs and any failed targets.

    Raises:
        HTTPException: On validation errors or submission failures.
    """
    logger.info(
        f"Task submission: type={req.task_type}, command={req.command[:50] if req.command else 'N/A'}..."
    )
    logger.debug(f"Full submission: {req.model_dump()}")

    # Validate request
    _validate_submission(req)

    # Prepare task configuration
    task_config = _prepare_task_config(req)

    # Determine targets
    targets, required_gpus = _resolve_targets(req)

    # Process each target
    created_task_ids: list[str] = []
    failed_targets: list[dict] = []
    first_task_id: str | None = None
    last_node: Node | None = None
    last_result = None

    for target_str, target_gpus in zip(targets, required_gpus, strict=True):
        result = await _process_target(
            req=req,
            target_str=target_str,
            target_gpus=target_gpus,
            task_config=task_config,
            batch_id=first_task_id,
        )

        match result:
            case {"task_id": task_id, "node": node, "runner_response": runner_resp}:
                if first_task_id is None:
                    first_task_id = task_id
                created_task_ids.append(task_id)
                last_node = node
                last_result = runner_resp
            case {"error": reason}:
                failed_targets.append({"target": target_str, "reason": reason})

    # Build response
    return _build_submission_response(
        created_task_ids, failed_targets, last_node, last_result
    )


def _validate_submission(req: TaskSubmission) -> None:
    """Validate task submission request."""
    if req.task_type not in {"command", "vps"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid task type. Only 'command' and 'vps' are supported.",
        )

    if req.task_type == "vps":
        req.arguments = []
        req.env_vars = {}


def _prepare_task_config(req: TaskSubmission) -> dict:
    """Prepare task configuration from request and defaults."""
    # Determine container name
    if req.container_name == "NULL":
        if req.task_type == "vps":
            raise HTTPException(
                status_code=400,
                detail="VPS tasks require a Docker container.",
            )
        container_name = None
    else:
        container_name = req.container_name or config.DEFAULT_CONTAINER_NAME

    return {
        "container_name": container_name,
        "image_tag": f"kohakuriver/{container_name}:base" if container_name else None,
        "privileged": (
            config.TASKS_PRIVILEGED if req.privileged is None else req.privileged
        ),
        "mounts": (
            config.ADDITIONAL_MOUNTS
            if req.additional_mounts is None
            else req.additional_mounts
        ),
        "output_dir": os.path.join(config.SHARED_DIR, "logs"),
    }


def _resolve_targets(req: TaskSubmission) -> tuple[list[str], list[list[int]]]:
    """Resolve target nodes and GPU allocations."""
    targets = req.targets

    if not targets:
        if req.required_gpus:
            raise HTTPException(
                status_code=400,
                detail="No target node specified for GPU task is not allowed.",
            )
        node = find_suitable_node(required_cores=req.required_cores)
        if not node:
            raise HTTPException(
                status_code=503,
                detail="No suitable node available for this task.",
            )
        targets = [node.hostname]
        logger.debug(f"Auto-selected target: {targets}")

    required_gpus = req.required_gpus or [[] for _ in targets]
    if len(required_gpus) != len(targets):
        raise HTTPException(
            status_code=400,
            detail=f"required_gpus length ({len(required_gpus)}) must match targets length ({len(targets)}).",
        )

    if len(targets) > 1 and req.task_type == "vps":
        raise HTTPException(
            status_code=400,
            detail="VPS tasks cannot be submitted to multiple targets.",
        )

    return targets, required_gpus


async def _process_target(
    req: TaskSubmission,
    target_str: str,
    target_gpus: list[int],
    task_config: dict,
    batch_id: str | None,
) -> dict:
    """
    Process a single target for task submission.

    Returns:
        Dict with either task_id/node/runner_response or error.
    """
    # Parse target string
    target_hostname, target_numa_id = _parse_target_string(target_str)
    if target_hostname is None:
        return {"error": "Invalid target format"}

    # Validate node
    node = _validate_node(target_hostname, target_str)
    if isinstance(node, str):
        return {"error": node}

    # Validate NUMA and resources
    validation_error = _validate_node_resources(
        node, target_str, target_numa_id, target_gpus, req
    )
    if validation_error:
        return {"error": validation_error}

    # Create task record
    task_id = generate_snowflake_id()
    task = _create_task_record(
        task_id=task_id,
        req=req,
        node=node,
        target_numa_id=target_numa_id,
        target_gpus=target_gpus,
        task_config=task_config,
        batch_id=batch_id or task_id,
    )

    if task is None:
        return {"error": "Database error during task creation"}

    # Dispatch to runner
    runner_response = await _dispatch_task(task, node, req, task_config)

    if runner_response is False:
        return {"error": "Runner failed to execute task"}

    return {
        "task_id": str(task_id),
        "node": node,
        "runner_response": runner_response,
    }


def _parse_target_string(target_str: str) -> tuple[str | None, int | None]:
    """Parse target string into hostname and optional NUMA ID."""
    parts = target_str.split(":")
    hostname = parts[0]
    numa_id = None

    if len(parts) > 1:
        try:
            numa_id = int(parts[1])
            if numa_id < 0:
                logger.warning(f"Invalid NUMA ID in target '{target_str}'")
                return None, None
        except ValueError:
            logger.warning(f"Invalid NUMA ID format in target '{target_str}'")
            return None, None

    return hostname, numa_id


def _validate_node(hostname: str, target_str: str) -> Node | str:
    """Validate node exists and is online. Returns Node or error string."""
    node = Node.get_or_none(Node.hostname == hostname)

    if not node:
        logger.warning(f"Target node '{hostname}' not registered")
        return "Node not registered"

    if node.status != "online":
        logger.warning(f"Target node '{hostname}' is {node.status}")
        return f"Node status is {node.status}"

    return node


def _validate_node_resources(
    node: Node,
    target_str: str,
    target_numa_id: int | None,
    target_gpus: list[int],
    req: TaskSubmission,
) -> str | None:
    """Validate node has required resources. Returns error string or None."""
    # Validate NUMA
    if target_numa_id is not None:
        node_topology = node.get_numa_topology()
        if node_topology is None:
            return "Node has no NUMA topology"
        if target_numa_id not in node_topology:
            return f"Invalid NUMA ID (Valid: {list(node_topology.keys())})"

    # Validate GPUs
    gpu_info = node.get_gpu_info()
    if gpu_info and target_gpus:
        invalid_gpus = [g for g in target_gpus if g >= len(gpu_info) or g < 0]
        if invalid_gpus:
            return f"Invalid GPU IDs: {invalid_gpus}"

        available_gpus = get_node_available_gpus(node)
        if set(target_gpus) - available_gpus:
            return "Requested GPUs not available"

    # Validate cores
    available_cores = get_node_available_cores(node)
    if req.required_cores and available_cores < req.required_cores:
        return "Insufficient available cores"

    # Validate memory
    if req.required_memory_bytes:
        available_memory = get_node_available_memory(node)
        if available_memory < req.required_memory_bytes:
            return "Insufficient available memory"

    return None


def _create_task_record(
    task_id: str,
    req: TaskSubmission,
    node: Node,
    target_numa_id: int | None,
    target_gpus: list[int],
    task_config: dict,
    batch_id: str,
) -> Task | None:
    """Create task record in database."""
    output_dir = task_config["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    task_log_dir = os.path.join(output_dir, str(task_id))
    stdout_path = os.path.join(task_log_dir, "stdout.log")
    stderr_path = os.path.join(task_log_dir, "stderr.log")

    ssh_port = allocate_ssh_port() if req.task_type == "vps" else None

    try:
        return Task.create(
            task_id=task_id,
            task_type=req.task_type,
            batch_id=batch_id,
            command=req.command,
            arguments=json.dumps(req.arguments) if req.arguments else "[]",
            env_vars=json.dumps(req.env_vars) if req.env_vars else "{}",
            required_cores=req.required_cores,
            required_gpus=json.dumps(target_gpus),
            required_memory_bytes=req.required_memory_bytes,
            assigned_node=node.hostname,
            status="assigning",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            submitted_at=datetime.datetime.now(),
            target_numa_node_id=target_numa_id,
            container_name=task_config["container_name"],
            docker_image_name=task_config["image_tag"],
            docker_privileged=task_config["privileged"],
            docker_mount_dirs=(
                json.dumps(task_config["mounts"]) if task_config["mounts"] else "[]"
            ),
            ssh_port=ssh_port,
        )
    except Exception as e:
        logger.exception(f"Failed to create task record: {e}")
        return None


async def _dispatch_task(
    task: Task,
    node: Node,
    req: TaskSubmission,
    task_config: dict,
) -> dict | bool | None:
    """Dispatch task to runner node."""
    if req.task_type == "vps":
        result = await send_vps_task_to_runner(
            runner_url=node.url,
            task=task,
            container_name=task_config["container_name"],
            ssh_public_key=req.command,
        )
        if result is None:
            task.status = "failed"
            task.error_message = "Failed to create VPS on runner."
            task.completed_at = datetime.datetime.now()
            task.save()
            return False
        return result
    else:
        # Dispatch command task in background
        dispatch_task = asyncio.create_task(
            send_task_to_runner(
                runner_url=node.url,
                task=task,
                container_name=task_config["container_name"],
                working_dir="/shared",
            )
        )
        background_tasks.add(dispatch_task)
        dispatch_task.add_done_callback(background_tasks.discard)
        return True


def _build_submission_response(
    created_task_ids: list[str],
    failed_targets: list[dict],
    node: Node | None,
    runner_result: dict | None,
) -> dict:
    """Build final submission response."""
    if not created_task_ids and failed_targets:
        logger.error(f"Task submission failed for all targets: {failed_targets}")
        raise HTTPException(
            status_code=503,
            detail=f"Failed to schedule task for any target. Failures: {failed_targets}",
        )

    if failed_targets:
        logger.warning(
            f"Partial submission. Succeeded: {created_task_ids}, Failed: {failed_targets}"
        )
        return {
            "message": f"Task batch submitted. {len(created_task_ids)} tasks created. Some targets failed.",
            "task_ids": created_task_ids,
            "failed_targets": failed_targets,
        }

    logger.info(f"Task batch submission successful: {created_task_ids}")
    response = {
        "message": f"Task batch submitted successfully. {len(created_task_ids)} tasks created.",
        "task_ids": created_task_ids,
    }

    if node:
        response["assigned_node"] = {"hostname": node.hostname, "url": node.url}
    if runner_result:
        response["runner_response"] = runner_result

    return response


# =============================================================================
# Status Updates
# =============================================================================


@router.post("/update")
async def update_task_status_endpoint(update: TaskStatusUpdate):
    """
    Receive task status update from runner.

    Called by runner nodes to report task state changes.
    """
    logger.info(f"Status update for task {update.task_id}: {update.status}")
    logger.debug(f"Full update: {update.model_dump()}")

    success = update_task_status(
        task_id=update.task_id,
        status=update.status,
        exit_code=update.exit_code,
        message=update.message,
        started_at=update.started_at,
        completed_at=update.completed_at,
        ssh_port=update.ssh_port,
    )

    if not success:
        return {"message": "Task ID not recognized or invalid state transition."}

    return {"message": "Task status updated successfully."}


# =============================================================================
# Task Queries
# =============================================================================


@router.get("/status/{task_id}", response_model=TaskResponse)
async def get_task_status(task_id: int):
    """Get status and details of a specific task."""
    logger.debug(f"Getting status for task {task_id}")

    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    return TaskResponse(**task.to_dict())


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    List command tasks (excludes VPS - use /vps endpoint for VPS).

    Args:
        status: Filter by task status.
        limit: Maximum number of tasks to return.
        offset: Number of tasks to skip.

    Returns:
        List of task responses.
    """
    logger.debug(f"Listing tasks: status={status}, limit={limit}, offset={offset}")

    query = (
        Task.select()
        .where(Task.task_type == "command")
        .order_by(Task.submitted_at.desc())
    )

    if status:
        query = query.where(Task.status == status)

    query = query.limit(limit).offset(offset)

    return [TaskResponse(**task.to_dict()) for task in query]


# =============================================================================
# Task Control
# =============================================================================


@router.post("/kill/{task_id}", status_code=202)
async def request_kill_task(task_id: int):
    """
    Request to kill a running task.

    Marks the task as killed and sends kill signal to the runner
    if the task is currently running.
    """
    logger.info(f"Kill requested for task {task_id}")

    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    killable_states = ["pending", "assigning", "running", "paused"]
    if task.status not in killable_states:
        raise HTTPException(
            status_code=409,
            detail=f"Task cannot be killed (state: {task.status})",
        )

    original_status = task.status
    container_name = (
        vps_container_name(task.task_id)
        if task.task_type == "vps"
        else task_container_name(task.task_id)
    )

    mark_task_killed(task)

    # Send kill to runner if task is active
    if original_status in ["running", "paused"] and task.assigned_node:
        node = Node.get_or_none(Node.hostname == task.assigned_node)
        if node and node.status == "online":
            logger.debug(f"Sending kill to runner {node.hostname} for task {task_id}")
            kill_task = asyncio.create_task(
                send_kill_to_runner(node.url, task_id, container_name)
            )
            background_tasks.add(kill_task)
            kill_task.add_done_callback(background_tasks.discard)

    return {"message": f"Kill requested for task {task_id}. Task marked as killed."}


@router.post("/command/{task_id}/{command}")
async def send_command_to_task(task_id: int, command: str):
    """
    Send a control command (pause/resume) to a task.

    Args:
        task_id: Target task ID.
        command: Command to send ('pause' or 'resume').
    """
    logger.info(f"Command '{command}' for task {task_id}")

    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if not task.assigned_node:
        raise HTTPException(status_code=400, detail="Task has no assigned node.")

    node = Node.get_or_none(Node.hostname == task.assigned_node)
    if not node:
        raise HTTPException(status_code=400, detail="Assigned node not found.")

    container_name = (
        vps_container_name(task.task_id)
        if task.task_type == "vps"
        else task_container_name(task.task_id)
    )

    match (command, task.status):
        case ("pause", "running"):
            response = await send_pause_to_runner(node.url, task_id, container_name)
            if "successfully" in response:
                task.status = "paused"
                task.save()
            return {"message": f"Pause for task {task_id}: {response}"}

        case ("resume", "paused"):
            response = await send_resume_to_runner(node.url, task_id, container_name)
            if "successfully" in response:
                task.status = "running"
                task.save()
            return {"message": f"Resume for task {task_id}: {response}"}

        case _:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid command or task state: {command} for {task.status}",
            )


# =============================================================================
# Task Output
# =============================================================================


@router.get("/tasks/{task_id}/stdout", response_class=PlainTextResponse)
async def get_task_stdout(task_id: int, lines: int | None = None):
    """
    Get stdout output from a task.

    Args:
        task_id: Task ID.
        lines: Number of lines to return (from end of file). If None, return all.

    Returns:
        Plain text stdout content.
    """
    return await _get_task_output(task_id, "stdout", lines)


@router.get("/tasks/{task_id}/stderr", response_class=PlainTextResponse)
async def get_task_stderr(task_id: int, lines: int | None = None):
    """
    Get stderr output from a task.

    Args:
        task_id: Task ID.
        lines: Number of lines to return (from end of file). If None, return all.

    Returns:
        Plain text stderr content.
    """
    return await _get_task_output(task_id, "stderr", lines)


async def _get_task_output(task_id: int, output_type: str, lines: int | None) -> str:
    """Helper to get task stdout or stderr."""
    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.task_type == "vps":
        raise HTTPException(
            status_code=400,
            detail=f"VPS tasks do not have {output_type}.",
        )

    output_path = task.stdout_path if output_type == "stdout" else task.stderr_path
    logger.info(f"Reading {output_type} for task {task_id} from: {output_path}")

    if not output_path or not os.path.exists(output_path):
        logger.warning(f"{output_type} file not found: {output_path}")
        return ""

    try:
        with open(output_path) as f:
            if lines is not None:
                content = f.readlines()[-lines:]
                result = "".join(content)
            else:
                result = f.read()
        logger.info(f"{output_type} for task {task_id}: {len(result)} chars")
        return result
    except Exception as e:
        logger.error(f"Error reading {output_type} for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading {output_type}.")
