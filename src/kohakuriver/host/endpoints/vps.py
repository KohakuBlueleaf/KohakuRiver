"""
VPS (Virtual Private Server) endpoints.

Handles VPS container creation and management.

Supports four SSH key modes:
- disabled: No SSH server at all, TTY-only mode (default, faster startup)
- none: SSH with passwordless root login
- upload: SSH with user-provided public key
- generate: SSH with server-generated keypair (returns private key to CLI)
"""

import asyncio
import datetime
import json
import os
import subprocess
import tempfile

import httpx
import peewee
from fastapi import APIRouter, HTTPException

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.docker.naming import vps_container_name
from kohakuriver.host.config import config
from kohakuriver.host.services.node_manager import find_suitable_node
from kohakuriver.host.services.task_scheduler import send_kill_to_runner
from kohakuriver.models.requests import VPSSubmission
from kohakuriver.utils.logger import get_logger
from kohakuriver.utils.snowflake import generate_snowflake_id

logger = get_logger(__name__)
router = APIRouter()

# Background tasks set
background_tasks: set[asyncio.Task] = set()


def _generate_ssh_keypair_for_vps(task_id: int) -> tuple[str, str]:
    """
    Generate an SSH keypair for VPS.

    Args:
        task_id: Task ID to use in key comment.

    Returns:
        Tuple of (private_key_content, public_key_content).

    Raises:
        RuntimeError: If key generation fails.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = os.path.join(tmpdir, "id_ed25519")

        cmd = [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            key_path,
            "-N",
            "",  # Empty passphrase
            "-q",  # Quiet
            "-C",
            f"kohakuriver-vps-{task_id}",
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to generate SSH keypair: {e.stderr.decode()}")
        except FileNotFoundError:
            raise RuntimeError("ssh-keygen not found. Please install OpenSSH.")

        # Read generated keys
        with open(key_path, "r") as f:
            private_key = f.read()
        with open(f"{key_path}.pub", "r") as f:
            public_key = f.read().strip()

        return private_key, public_key


async def send_vps_to_runner(
    runner_url: str,
    task: Task,
    container_name: str,
    ssh_key_mode: str,
    ssh_public_key: str | None,
) -> dict | None:
    """
    Send VPS creation request to a runner.

    Args:
        runner_url: Runner's HTTP URL.
        task: Task record for the VPS.
        container_name: Docker container base image.
        ssh_key_mode: SSH key mode ("none", "upload", or "generate").
        ssh_public_key: SSH public key for VPS access (None for "none" mode).

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
        "ssh_key_mode": ssh_key_mode,
        "ssh_public_key": ssh_public_key,
        "ssh_port": task.ssh_port,
    }

    logger.info(
        f"Sending VPS {task.task_id} to runner at {runner_url} (ssh_key_mode={ssh_key_mode})"
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{runner_url}/api/vps/create",
                json=payload,
                timeout=None,  # No timeout - VPS creation can take a long time
            )
            response.raise_for_status()
            return response.json()

    except httpx.RequestError as e:
        logger.error(f"Failed to send VPS {task.task_id} to {runner_url}: {e}")
        # Return empty dict to indicate communication failure (not rejection)
        # The task should remain in "assigning" state - runner will report actual status
        return {}
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Runner {runner_url} rejected VPS {task.task_id}: "
            f"{e.response.status_code} - {e.response.text}"
        )
        # Return None only for explicit rejection from runner
        return None


def allocate_ssh_port() -> int:
    """
    Allocate a unique SSH port for VPS.

    Returns:
        Available SSH port number.
    """
    # Get existing VPS ports
    existing_ports = set()
    active_vps = Task.select(Task.ssh_port).where(
        (Task.task_type == "vps")
        & (Task.status.in_(["pending", "assigning", "running", "paused"]))
        & (Task.ssh_port.is_null(False))
    )
    for vps in active_vps:
        if vps.ssh_port:
            existing_ports.add(vps.ssh_port)

    # Find available port starting from 2222
    port = 2222
    while port in existing_ports:
        port += 1

    return port


@router.post("/vps/create")
async def submit_vps(submission: VPSSubmission):
    """Submit a new VPS for creation."""
    logger.info(
        f"Received VPS submission for {submission.required_cores} cores "
        f"(ssh_key_mode={submission.ssh_key_mode})"
    )

    # Validate SSH key mode
    ssh_key_mode = submission.ssh_key_mode or "disabled"
    if ssh_key_mode not in ("disabled", "none", "upload", "generate"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ssh_key_mode: {ssh_key_mode}. Must be 'disabled', 'none', 'upload', or 'generate'.",
        )

    # Validate public key is provided for upload mode
    if ssh_key_mode == "upload" and not submission.ssh_public_key:
        raise HTTPException(
            status_code=400,
            detail="ssh_public_key is required when ssh_key_mode is 'upload'.",
        )

    # Find suitable node
    node = find_suitable_node(
        required_cores=submission.required_cores,
        required_gpus=submission.required_gpus,
        required_memory_bytes=submission.required_memory_bytes,
        target_hostname=submission.target_hostname,
        target_numa_node_id=submission.target_numa_node_id,
    )

    if not node:
        raise HTTPException(
            status_code=503,
            detail="No suitable node available for this VPS.",
        )

    # Generate task ID and allocate SSH port
    task_id = generate_snowflake_id()
    ssh_port = allocate_ssh_port()

    # Get container name
    container_name = submission.container_name or config.DEFAULT_CONTAINER_NAME

    # Handle SSH key based on mode
    ssh_public_key = None
    ssh_private_key = None

    match ssh_key_mode:
        case "disabled":
            # No SSH server at all - TTY-only mode
            ssh_public_key = None
            logger.info(f"VPS {task_id}: SSH disabled (TTY-only mode)")

        case "none":
            # No SSH key - passwordless root
            ssh_public_key = None
            logger.info(f"VPS {task_id}: No SSH key mode (passwordless root)")

        case "upload":
            # User provided key
            ssh_public_key = submission.ssh_public_key
            logger.info(f"VPS {task_id}: Using uploaded SSH key")

        case "generate":
            # Generate keypair on host
            try:
                ssh_private_key, ssh_public_key = _generate_ssh_keypair_for_vps(task_id)
                logger.info(f"VPS {task_id}: Generated SSH keypair")
            except RuntimeError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to generate SSH keypair: {e}",
                )

    # Create task record
    task = Task.create(
        task_id=task_id,
        task_type="vps",
        command="vps",
        required_cores=submission.required_cores,
        required_gpus=(
            json.dumps(submission.required_gpus) if submission.required_gpus else "[]"
        ),
        required_memory_bytes=submission.required_memory_bytes,
        target_numa_node_id=submission.target_numa_node_id,
        assigned_node=node.hostname,
        status="assigning",
        ssh_port=ssh_port,
        submitted_at=datetime.datetime.now(),
    )

    logger.info(f"Created VPS task {task_id} assigned to {node.hostname}")

    # Send to runner
    result = await send_vps_to_runner(
        runner_url=node.url,
        task=task,
        container_name=container_name,
        ssh_key_mode=ssh_key_mode,
        ssh_public_key=ssh_public_key,
    )

    if result is None:
        # Runner explicitly rejected the VPS creation
        task.status = "failed"
        task.error_message = "Runner rejected VPS creation."
        task.completed_at = datetime.datetime.now()
        task.save()
        raise HTTPException(
            status_code=502,
            detail="Runner rejected VPS creation.",
        )

    if result == {}:
        # Communication failure - don't mark as failed
        # Task remains in "assigning" state, runner will report actual status
        logger.warning(
            f"VPS {task.task_id} communication failed, but task remains in 'assigning' state. "
            "Runner will report actual status."
        )
        # Return success response - client should poll for actual status
        return {
            "message": "VPS creation request sent (awaiting runner confirmation).",
            "task_id": str(task_id),
            "ssh_key_mode": ssh_key_mode,
            "ssh_port": ssh_port,
            "assigned_node": {
                "hostname": node.hostname,
                "url": node.url,
            },
            "status": "assigning",
        }

    response = {
        "message": "VPS created successfully.",
        "task_id": str(task_id),
        "ssh_key_mode": ssh_key_mode,
        "ssh_port": ssh_port,
        "assigned_node": {
            "hostname": node.hostname,
            "url": node.url,
        },
        "runner_response": result,
    }

    # Include generated keys in response (for "generate" mode)
    if ssh_key_mode == "generate" and ssh_private_key:
        response["ssh_private_key"] = ssh_private_key
        response["ssh_public_key"] = ssh_public_key

    return response


@router.get("/vps")
async def get_vps_list():
    """Get list of ALL VPS tasks (matching old /vps endpoint)."""
    logger.debug("Fetching all VPS list.")

    try:
        query = (
            Task.select(Task, Node.hostname)
            .join(
                Node, peewee.JOIN.LEFT_OUTER, on=(Task.assigned_node == Node.hostname)
            )
            .where(Task.task_type == "vps")
            .order_by(Task.submitted_at.desc())
        )

        vps_list = []
        for task in query:
            node_hostname = (
                task.assigned_node
                if isinstance(task.assigned_node, str)
                else (task.assigned_node.hostname if task.assigned_node else None)
            )
            vps_list.append(
                {
                    "task_id": str(task.task_id),
                    "required_cores": task.required_cores,
                    "required_gpus": (
                        json.loads(task.required_gpus) if task.required_gpus else []
                    ),
                    "required_memory_bytes": task.required_memory_bytes,
                    "status": task.status,
                    "assigned_node": node_hostname,
                    "target_numa_node_id": task.target_numa_node_id,
                    "container_name": task.container_name,
                    "ssh_port": task.ssh_port,
                    "exit_code": task.exit_code,
                    "error_message": task.error_message,
                    "submitted_at": task.submitted_at,
                    "started_at": task.started_at,
                    "completed_at": task.completed_at,
                }
            )

        return vps_list

    except peewee.PeeweeException as e:
        logger.error(f"Database error fetching VPS: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database error fetching VPS.",
        )


@router.get("/vps/status")
async def get_active_vps_status():
    """Get list of active VPS instances."""
    logger.debug("Fetching active VPS list.")

    try:
        active_statuses = ["pending", "assigning", "running", "paused"]
        query = (
            Task.select(Task, Node.hostname)
            .join(
                Node, peewee.JOIN.LEFT_OUTER, on=(Task.assigned_node == Node.hostname)
            )
            .where((Task.task_type == "vps") & (Task.status.in_(active_statuses)))
            .order_by(Task.submitted_at.desc())
        )

        vps_list = []
        for task in query:
            vps_list.append(
                {
                    "task_id": str(task.task_id),
                    "status": task.status,
                    "assigned_node": task.assigned_node,
                    "target_numa_node_id": task.target_numa_node_id,
                    "required_cores": task.required_cores,
                    "required_gpus": (
                        json.loads(task.required_gpus) if task.required_gpus else []
                    ),
                    "required_memory_bytes": task.required_memory_bytes,
                    "container_name": task.container_name,
                    "submitted_at": (
                        task.submitted_at.isoformat() if task.submitted_at else None
                    ),
                    "started_at": (
                        task.started_at.isoformat() if task.started_at else None
                    ),
                    "ssh_port": task.ssh_port,
                }
            )

        return vps_list

    except peewee.PeeweeException as e:
        logger.error(f"Database error fetching active VPS: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database error fetching active VPS.",
        )


@router.post("/vps/stop/{task_id}", status_code=202)
async def stop_vps(task_id: int):
    """Stop a VPS instance."""
    try:
        task_uuid = int(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Task ID format.")

    task: Task | None = Task.get_or_none(
        (Task.task_id == task_uuid) & (Task.task_type == "vps")
    )

    if not task:
        raise HTTPException(status_code=404, detail="VPS not found.")

    # Check if VPS can be stopped
    stoppable_states = ["pending", "assigning", "running", "paused"]
    if task.status not in stoppable_states:
        raise HTTPException(
            status_code=409,
            detail=f"VPS cannot be stopped (state: {task.status})",
        )

    original_status = task.status
    container_name = vps_container_name(task.task_id)

    # Mark as stopped
    task.status = "stopped"
    task.error_message = "Stopped by user."
    task.completed_at = datetime.datetime.now()
    task.save()
    logger.info(f"Marked VPS {task_id} as 'stopped'.")

    # Tell runner to stop the VPS container
    if original_status in ["running", "paused"] and task.assigned_node:
        node = Node.get_or_none(Node.hostname == task.assigned_node)
        if node and node.status == "online":
            logger.info(
                f"Requesting stop from runner {node.hostname} " f"for VPS {task_id}"
            )
            stop_task = asyncio.create_task(
                send_kill_to_runner(node.url, task_id, container_name)
            )
            background_tasks.add(stop_task)
            stop_task.add_done_callback(background_tasks.discard)

    return {"message": f"VPS {task_id} stop requested. VPS marked as stopped."}


@router.post("/vps/restart/{task_id}", status_code=202)
async def restart_vps(task_id: int):
    """Restart a VPS instance.

    Useful when nvidia docker breaks (nvml error) or container becomes unresponsive.
    This will stop the current container and create a new one with the same configuration.
    """
    try:
        task_uuid = int(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Task ID format.")

    task: Task | None = Task.get_or_none(
        (Task.task_id == task_uuid) & (Task.task_type == "vps")
    )

    if not task:
        raise HTTPException(status_code=404, detail="VPS not found.")

    # Check if VPS can be restarted
    restartable_states = ["running", "paused", "failed"]
    if task.status not in restartable_states:
        raise HTTPException(
            status_code=409,
            detail=f"VPS cannot be restarted (state: {task.status}). Must be running, paused, or failed.",
        )

    if not task.assigned_node:
        raise HTTPException(
            status_code=400,
            detail="VPS has no assigned node.",
        )

    node = Node.get_or_none(Node.hostname == task.assigned_node)
    if not node or node.status != "online":
        raise HTTPException(
            status_code=503,
            detail=f"Assigned node '{task.assigned_node}' is not online.",
        )

    container_name = vps_container_name(task.task_id)
    original_status = task.status

    logger.info(f"Restarting VPS {task_id} on node {node.hostname}")

    # Step 1: Stop the current container
    if original_status in ["running", "paused"]:
        logger.info(f"Stopping VPS container {container_name} on {node.hostname}")
        await send_kill_to_runner(node.url, task_id, container_name)
        # Wait briefly for container to stop
        await asyncio.sleep(2)

    # Step 2: Update task status to "assigning" for restart
    task.status = "assigning"
    task.error_message = None
    task.started_at = None
    task.completed_at = None
    task.save()

    # Step 3: Re-send VPS creation request to runner
    # We need to get the container name from the original task
    # The container_name field stores the base image name (e.g., "kohakuriver-base")
    base_container_name = task.container_name or config.DEFAULT_CONTAINER_NAME

    result = await send_vps_to_runner(
        runner_url=node.url,
        task=task,
        container_name=base_container_name,
        ssh_key_mode="none",  # Restart uses existing container, SSH should already be set up
        ssh_public_key=None,
    )

    if result is None:
        task.status = "failed"
        task.error_message = "Runner rejected VPS restart."
        task.completed_at = datetime.datetime.now()
        task.save()
        raise HTTPException(
            status_code=502,
            detail="Runner rejected VPS restart.",
        )

    if result == {}:
        # Communication failure - task remains in "assigning" state
        logger.warning(
            f"VPS {task_id} restart communication failed, task remains in 'assigning' state."
        )
        return {
            "message": "VPS restart request sent (awaiting runner confirmation).",
            "task_id": str(task_id),
            "status": "assigning",
        }

    return {
        "message": f"VPS {task_id} restart successful.",
        "task_id": str(task_id),
        "runner_response": result,
    }


# =============================================================================
# Snapshot Proxy Endpoints
# =============================================================================


async def _get_vps_runner_url(task_id: int) -> tuple[Task, str]:
    """
    Get the runner URL for a VPS task.

    Args:
        task_id: VPS task ID.

    Returns:
        Tuple of (task, runner_url).

    Raises:
        HTTPException: If task not found or node unavailable.
    """
    task: Task | None = Task.get_or_none(
        (Task.task_id == task_id) & (Task.task_type == "vps")
    )

    if not task:
        raise HTTPException(status_code=404, detail="VPS not found.")

    if not task.assigned_node:
        raise HTTPException(status_code=400, detail="VPS has no assigned node.")

    node = Node.get_or_none(Node.hostname == task.assigned_node)
    if not node:
        raise HTTPException(
            status_code=404, detail=f"Node '{task.assigned_node}' not found."
        )

    # For snapshots, node doesn't need to be online - we just need its URL
    # The runner will handle the case when container isn't running
    return task, node.url


@router.get("/vps/snapshots/{task_id}")
async def list_vps_snapshots(task_id: int):
    """
    List all snapshots for a VPS.

    Proxies to the runner that hosts/hosted this VPS.
    Works even if the VPS is not currently running.
    """
    logger.info(f"Listing snapshots for VPS {task_id}")

    task, runner_url = await _get_vps_runner_url(task_id)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{runner_url}/api/vps/snapshots/{task_id}",
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Failed to list snapshots for VPS {task_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to communicate with runner: {e}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text,
        )


@router.post("/vps/snapshots/{task_id}")
async def create_vps_snapshot(task_id: int, message: str = None):
    """
    Create a snapshot of the current VPS state.

    The VPS must be running to create a snapshot.
    Proxies to the runner that hosts this VPS.
    """
    logger.info(f"Creating snapshot for VPS {task_id}")

    task, runner_url = await _get_vps_runner_url(task_id)

    # Check if VPS is running
    if task.status != "running":
        raise HTTPException(
            status_code=400,
            detail=f"VPS is not running (status: {task.status}). Cannot create snapshot.",
        )

    try:
        payload = {"message": message} if message else {}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{runner_url}/api/vps/snapshots/{task_id}",
                json=payload,
                timeout=120.0,  # Snapshots can take time
            )
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Failed to create snapshot for VPS {task_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to communicate with runner: {e}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text,
        )


@router.delete("/vps/snapshots/{task_id}/{timestamp}")
async def delete_vps_snapshot(task_id: int, timestamp: int):
    """
    Delete a specific snapshot by timestamp.

    Proxies to the runner that hosts/hosted this VPS.
    """
    logger.info(f"Deleting snapshot {timestamp} for VPS {task_id}")

    task, runner_url = await _get_vps_runner_url(task_id)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{runner_url}/api/vps/snapshots/{task_id}/{timestamp}",
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Failed to delete snapshot for VPS {task_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to communicate with runner: {e}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text,
        )


@router.delete("/vps/snapshots/{task_id}")
async def delete_all_vps_snapshots(task_id: int):
    """
    Delete all snapshots for a VPS.

    Proxies to the runner that hosts/hosted this VPS.
    """
    logger.info(f"Deleting all snapshots for VPS {task_id}")

    task, runner_url = await _get_vps_runner_url(task_id)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{runner_url}/api/vps/snapshots/{task_id}",
                timeout=120.0,  # Multiple deletions may take time
            )
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Failed to delete snapshots for VPS {task_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to communicate with runner: {e}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text,
        )


@router.get("/vps/snapshots/{task_id}/latest")
async def get_latest_vps_snapshot(task_id: int):
    """
    Get the latest snapshot for a VPS.

    Proxies to the runner that hosts/hosted this VPS.
    """
    logger.info(f"Getting latest snapshot for VPS {task_id}")

    task, runner_url = await _get_vps_runner_url(task_id)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{runner_url}/api/vps/snapshots/{task_id}/latest",
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Failed to get latest snapshot for VPS {task_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to communicate with runner: {e}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text,
        )
