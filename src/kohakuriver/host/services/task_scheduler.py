"""
Task Scheduling Service.

Handles task submission, assignment, and control operations.
Provides communication with runner nodes for task lifecycle management.
"""

import datetime
import json

import httpx

from kohakuriver.db.task import Task
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Task Execution
# =============================================================================


async def send_task_to_runner(
    runner_url: str,
    task: Task,
    container_name: str,
    working_dir: str,
    reserved_ip: str | None = None,
    registry_image: str | None = None,
) -> dict | None:
    """
    Send task execution request to a runner.

    Args:
        runner_url: Runner's HTTP URL.
        task: Task to execute.
        container_name: Docker container to use.
        working_dir: Working directory inside container.
        reserved_ip: Pre-reserved IP address for the container (optional).

    Returns:
        Runner response dict or None on failure.
    """
    payload = {
        "task_id": task.task_id,
        "command": task.command,
        "arguments": task.get_arguments(),
        "env_vars": task.get_env_vars(),
        "required_cores": task.required_cores,
        "required_gpus": json.loads(task.required_gpus) if task.required_gpus else [],
        "required_memory_bytes": task.required_memory_bytes,
        "target_numa_node_id": task.target_numa_node_id,
        "container_name": container_name,
        "registry_image": registry_image,
        "working_dir": working_dir,
        "stdout_path": task.stdout_path,
        "stderr_path": task.stderr_path,
        "reserved_ip": reserved_ip,
    }

    logger.info(f"Sending task {task.task_id} to runner at {runner_url}")
    logger.debug(f"Task payload: {payload}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{runner_url}/api/execute",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()
            logger.debug(f"Runner response: {result}")
            return result

    except httpx.RequestError as e:
        logger.error(f"Failed to send task {task.task_id} to {runner_url}: {e}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Runner {runner_url} rejected task {task.task_id}: "
            f"{e.response.status_code} - {e.response.text}"
        )
        return None


# =============================================================================
# VPS Operations
# =============================================================================


async def send_vps_task_to_runner(
    runner_url: str,
    task: Task,
    container_name: str,
    ssh_public_key: str,
    reserved_ip: str | None = None,
    registry_image: str | None = None,
) -> dict | None:
    """
    Send VPS creation request to a runner.

    Args:
        runner_url: Runner's HTTP URL.
        task: Task record for the VPS.
        container_name: Docker container base image.
        ssh_public_key: SSH public key for VPS access.
        reserved_ip: Pre-reserved IP address for the container (optional).

    Returns:
        Runner response dict or None on failure.
    """
    payload = {
        "task_id": task.task_id,
        "required_cores": task.required_cores,
        "required_gpus": json.loads(task.required_gpus) if task.required_gpus else [],
        "required_memory_bytes": task.required_memory_bytes,
        "target_numa_node_id": task.target_numa_node_id,
        "container_name": container_name,
        "registry_image": registry_image,
        "ssh_public_key": ssh_public_key,
        "ssh_port": task.ssh_port,
        "reserved_ip": reserved_ip,
    }

    logger.info(f"Sending VPS {task.task_id} to runner at {runner_url}")
    logger.debug(f"VPS payload: task_id={task.task_id}, ssh_port={task.ssh_port}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{runner_url}/api/vps/create",
                json=payload,
                timeout=60.0,  # VPS creation may take longer
            )
            response.raise_for_status()
            result = response.json()

            # Update SSH port from runner response if provided
            ssh_port = result.get("ssh_port")
            if ssh_port:
                task.ssh_port = ssh_port
                task.save()
                logger.debug(f"Updated task SSH port to {ssh_port}")

            return result

    except httpx.RequestError as e:
        logger.error(f"Failed to send VPS {task.task_id} to {runner_url}: {e}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Runner {runner_url} rejected VPS {task.task_id}: "
            f"{e.response.status_code} - {e.response.text}"
        )
        return None


# =============================================================================
# Task Control
# =============================================================================


async def send_kill_to_runner(
    runner_url: str, task_id: int, container_name: str
) -> None:
    """
    Send kill request to a runner.

    Args:
        runner_url: Runner's HTTP URL.
        task_id: Task ID to kill.
        container_name: Container name for the task.
    """
    logger.info(f"Sending kill for task {task_id} to {runner_url}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{runner_url}/api/kill",
                json={"task_id": task_id, "container_name": container_name},
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info(f"Kill for task {task_id} acknowledged by {runner_url}")

    except httpx.RequestError as e:
        logger.error(f"Failed to send kill for task {task_id} to {runner_url}: {e}")
        _update_task_error_message(task_id, f"Runner unreachable: {e}")

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Runner {runner_url} failed kill for task {task_id}: "
            f"{e.response.status_code}"
        )


async def send_pause_to_runner(
    runner_url: str,
    task_id: int,
    container_name: str,
) -> str:
    """
    Send pause request to a runner.

    Args:
        runner_url: Runner's HTTP URL.
        task_id: Task ID to pause.
        container_name: Container name for the task.

    Returns:
        Status message.
    """
    logger.info(f"Sending pause for task {task_id} to {runner_url}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{runner_url}/api/pause",
                json={"task_id": task_id, "container_name": container_name},
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info(f"Pause for task {task_id} acknowledged by {runner_url}")
            return "Pause command sent successfully."

    except httpx.RequestError as e:
        logger.error(f"Failed to send pause for task {task_id} to {runner_url}: {e}")
        return "Failed to send pause command."

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Runner {runner_url} failed pause for task {task_id}: "
            f"{e.response.status_code}"
        )
        return "Runner error during pause command."


async def send_resume_to_runner(
    runner_url: str,
    task_id: int,
    container_name: str,
) -> str:
    """
    Send resume request to a runner.

    Args:
        runner_url: Runner's HTTP URL.
        task_id: Task ID to resume.
        container_name: Container name for the task.

    Returns:
        Status message.
    """
    logger.info(f"Sending resume for task {task_id} to {runner_url}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{runner_url}/api/resume",
                json={"task_id": task_id, "container_name": container_name},
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info(f"Resume for task {task_id} acknowledged by {runner_url}")
            return "Resume command sent successfully."

    except httpx.RequestError as e:
        logger.error(f"Failed to send resume for task {task_id} to {runner_url}: {e}")
        return "Failed to send resume command."

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Runner {runner_url} failed resume for task {task_id}: "
            f"{e.response.status_code}"
        )
        return "Runner error during resume command."


# =============================================================================
# Task Status Updates
# =============================================================================


def mark_task_killed(task: Task, message: str = "Kill requested by user.") -> None:
    """Mark a task as killed in the database."""
    task.status = "killed"
    task.error_message = message
    task.completed_at = datetime.datetime.now()
    task.save()
    logger.info(f"Marked task {task.task_id} as 'killed'")


def update_task_status(
    task_id: int,
    status: str,
    exit_code: int | None = None,
    message: str | None = None,
    started_at: datetime.datetime | None = None,
    completed_at: datetime.datetime | None = None,
    ssh_port: int | None = None,
) -> bool:
    """
    Update task status from runner callback.

    Args:
        task_id: Task ID to update.
        status: New status.
        exit_code: Exit code if completed.
        message: Error or status message.
        started_at: When task started.
        completed_at: When task completed.
        ssh_port: SSH port for VPS tasks.

    Returns:
        True if updated, False if task not found or invalid state.
    """
    logger.debug(
        f"Updating task {task_id}: status={status}, exit_code={exit_code}, "
        f"ssh_port={ssh_port}"
    )

    task: Task | None = Task.get_or_none(Task.task_id == task_id)
    if not task:
        logger.warning(f"Received update for unknown task ID: {task_id}")
        return False

    # Check for valid state transitions
    if not _validate_status_transition(task, status, message):
        return False

    # Check if recovering from lost state
    is_recovering = task.status == "lost" and status == "running"

    # Apply updates
    _apply_task_updates(
        task,
        status,
        exit_code,
        message,
        started_at,
        completed_at,
        ssh_port,
        is_recovering,
    )

    task.save()
    logger.info(f"Task {task_id} status updated to {status}")
    return True


def _validate_status_transition(
    task: Task, new_status: str, message: str | None
) -> bool:
    """Validate that a status transition is allowed."""
    final_states = {"completed", "failed", "killed", "killed_oom", "lost", "stopped"}

    if task.status not in final_states:
        return True

    if new_status in final_states:
        return True

    # Special case: Allow VPS tasks to recover from "lost" state
    if task.task_type == "vps" and task.status == "lost" and new_status == "running":
        logger.info(
            f"[VPS Recovery] VPS {task.task_id} recovering from 'lost' to 'running'. "
            f"Runner likely restarted and found the container still running"
        )
        if message:
            logger.info(f"[VPS Recovery] Recovery message: {message}")
        return True

    logger.warning(
        f"Ignoring status update '{new_status}' for task {task.task_id} "
        f"which is already in final state '{task.status}'"
    )
    return False


def _apply_task_updates(
    task: Task,
    status: str,
    exit_code: int | None,
    message: str | None,
    started_at: datetime.datetime | None,
    completed_at: datetime.datetime | None,
    ssh_port: int | None,
    is_recovering: bool,
) -> None:
    """Apply updates to a task record."""
    final_states = {"completed", "failed", "killed", "killed_oom", "lost", "stopped"}

    task.status = status
    task.exit_code = exit_code
    task.error_message = message

    if started_at and not task.started_at:
        task.started_at = started_at
        logger.info(f"Task {task.task_id} started at {started_at}")

    # Handle completed_at based on recovery state
    if is_recovering:
        task.completed_at = None
        logger.info(
            f"[VPS Recovery] Cleared completed_at for VPS {task.task_id}, "
            "task is now active again"
        )
    elif completed_at:
        task.completed_at = completed_at
    elif status in final_states and not task.completed_at:
        task.completed_at = datetime.datetime.now()

    # Update SSH port for VPS tasks
    if ssh_port is not None:
        task.ssh_port = ssh_port
        logger.info(f"Task {task.task_id} SSH port updated to {ssh_port}")

    # Clear suspicion count on successful updates
    if task.assignment_suspicion_count > 0:
        logger.debug(f"Clearing suspicion count for task {task.task_id}")
        task.assignment_suspicion_count = 0


def _update_task_error_message(task_id: int, additional_message: str) -> None:
    """Append an error message to a task's error_message field."""
    task: Task | None = Task.get_or_none(Task.task_id == task_id)
    if task and task.status == "killed":
        task.error_message = f"{task.error_message or ''} | {additional_message}"
        task.save()
