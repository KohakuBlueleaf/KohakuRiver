"""
VPS lifecycle endpoints.

Handles VPS creation, restart, stop, and related helpers.
"""

import asyncio
import datetime
import json
import os
import subprocess
import tempfile
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from kohakuriver.db.auth import User
from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.docker.naming import vps_container_name
from kohakuriver.host.auth.dependencies import require_operator
from kohakuriver.host.config import config
from kohakuriver.host.services.node_manager import (
    find_suitable_node,
    find_suitable_node_for_vm,
)
from kohakuriver.host.services.task_scheduler import send_vps_stop_to_runner
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
    registry_image: str | None = None,
    vps_backend: str = "docker",
    vm_image: str | None = None,
    vm_disk_size: str | None = None,
    memory_mb: int | None = None,
) -> dict | None:
    """
    Send VPS creation request to a runner.

    Args:
        runner_url: Runner's HTTP URL.
        task: Task record for the VPS.
        container_name: Docker container base image.
        ssh_key_mode: SSH key mode ("none", "upload", or "generate").
        ssh_public_key: SSH public key for VPS access (None for "none" mode).
        registry_image: Docker registry image override.
        vps_backend: "docker" or "qemu".
        vm_image: Base VM image name (qemu only).
        vm_disk_size: VM disk size (qemu only).
        memory_mb: VM memory in MB (qemu only).

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
        "ssh_key_mode": ssh_key_mode,
        "ssh_public_key": ssh_public_key,
        "ssh_port": task.ssh_port,
        "vps_backend": vps_backend,
    }

    # Add VM-specific fields
    if vps_backend == "qemu":
        payload["vm_image"] = vm_image
        payload["vm_disk_size"] = vm_disk_size
        payload["memory_mb"] = memory_mb

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


def _validate_vps_submission(submission: VPSSubmission) -> tuple[str, str]:
    """
    Validate VPS submission inputs.

    Args:
        submission: The VPS submission request.

    Returns:
        Tuple of (vps_backend, ssh_key_mode).

    Raises:
        HTTPException: On invalid input.
    """
    vps_backend = submission.vps_backend or "docker"

    if vps_backend not in ("docker", "qemu"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid vps_backend: {vps_backend}. Must be 'docker' or 'qemu'.",
        )

    ssh_key_mode = submission.ssh_key_mode or "disabled"
    if ssh_key_mode not in ("disabled", "none", "upload", "generate"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ssh_key_mode: {ssh_key_mode}. Must be 'disabled', 'none', 'upload', or 'generate'.",
        )

    if ssh_key_mode == "upload" and not submission.ssh_public_key:
        raise HTTPException(
            status_code=400,
            detail="ssh_public_key is required when ssh_key_mode is 'upload'.",
        )

    return vps_backend, ssh_key_mode


def _resolve_ssh_keys(
    ssh_key_mode: str, submission: VPSSubmission, task_id: int
) -> tuple[str | None, str | None]:
    """
    Resolve SSH keys based on the key mode.

    Args:
        ssh_key_mode: SSH key mode ("disabled", "none", "upload", or "generate").
        submission: The VPS submission request.
        task_id: Task ID for key generation comment.

    Returns:
        Tuple of (ssh_public_key, ssh_private_key).

    Raises:
        HTTPException: If key generation fails.
    """
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

    return ssh_public_key, ssh_private_key


def _create_vps_task_record(
    task_id: int,
    submission: VPSSubmission,
    ssh_port: int,
    node: Node,
    container_name: str | None,
    vps_backend: str,
    ssh_key_mode: str,
    current_user: User,
) -> Task:
    """
    Create the Task database record for a new VPS.

    Args:
        task_id: Snowflake task ID.
        submission: The VPS submission request.
        ssh_port: Allocated SSH port.
        node: Assigned compute node.
        container_name: Docker container base image name (None if registry_image is used).
        vps_backend: "docker" or "qemu".
        ssh_key_mode: SSH key mode.
        current_user: The authenticated user submitting the VPS.

    Returns:
        Created Task record.
    """
    task = Task.create(
        task_id=task_id,
        task_type="vps",
        name=submission.name,
        owner_id=current_user.id if current_user.id > 0 else None,
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
        container_name=container_name,
        registry_image=submission.registry_image,
        docker_image_name=submission.registry_image
        or (f"kohakuriver/{container_name}:base" if container_name else None),
        vps_backend=vps_backend,
        vm_image=submission.vm_image if vps_backend == "qemu" else None,
        vm_disk_size=submission.vm_disk_size if vps_backend == "qemu" else None,
    )

    logger.info(f"Created VPS task {task_id} assigned to {node.hostname}")
    return task


def _build_vps_response(
    task: Task,
    result: dict,
    ssh_private_key: str | None,
    ssh_public_key: str | None,
    vps_backend: str,
    ssh_key_mode: str,
) -> dict:
    """
    Build the VPS creation success response dict.

    Includes VM-specific info for qemu backend and generated SSH keys
    when ssh_key_mode is "generate". Also stores VM IP back in the task
    record if available.

    Args:
        task: The VPS task record.
        result: Runner response dict.
        ssh_private_key: Generated private key (None unless generate mode).
        ssh_public_key: Generated or uploaded public key.
        vps_backend: "docker" or "qemu".
        ssh_key_mode: SSH key mode.

    Returns:
        Response dict for the API caller.
    """
    node = Node.get_or_none(Node.hostname == task.assigned_node)

    response = {
        "message": "VPS created successfully.",
        "task_id": str(task.task_id),
        "vps_backend": vps_backend,
        "ssh_key_mode": ssh_key_mode,
        "ssh_port": task.ssh_port,
        "assigned_node": {
            "hostname": node.hostname if node else task.assigned_node,
            "url": node.url if node else None,
        },
        "runner_response": result,
    }

    # Add VM-specific info
    if vps_backend == "qemu" and result:
        response["vm_ip"] = result.get("vm_ip")
        response["vm_network_mode"] = result.get("network_mode")
        # Store VM IP back in task record
        vm_ip = result.get("vm_ip")
        if vm_ip:
            task.vm_ip = vm_ip
            task.save()

    # Include generated keys in response (for "generate" mode)
    if ssh_key_mode == "generate" and ssh_private_key:
        response["ssh_private_key"] = ssh_private_key
        response["ssh_public_key"] = ssh_public_key

    return response


@router.post("/vps/create")
async def submit_vps(
    submission: VPSSubmission,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Submit a new VPS for creation.

    Requires 'operator' role or higher (operators and admins can create VPS).
    """
    # Validate inputs
    vps_backend, ssh_key_mode = _validate_vps_submission(submission)

    logger.info(
        f"Received VPS submission for {submission.required_cores} cores "
        f"(ssh_key_mode={ssh_key_mode}, backend={vps_backend})"
    )

    # Find suitable node (different logic for VM backend)
    if vps_backend == "qemu":
        node, reject_reason = find_suitable_node_for_vm(
            required_cores=submission.required_cores,
            required_gpus=submission.required_gpus,
            required_memory_bytes=submission.required_memory_bytes,
            target_hostname=submission.target_hostname,
        )
        if not node:
            raise HTTPException(status_code=503, detail=reject_reason)
    else:
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

    # Get container name (registry_image overrides container_name)
    if submission.registry_image:
        container_name = None
    else:
        container_name = submission.container_name or config.DEFAULT_CONTAINER_NAME

    # Resolve SSH keys
    ssh_public_key, ssh_private_key = _resolve_ssh_keys(
        ssh_key_mode, submission, task_id
    )

    # Create task record
    task = _create_vps_task_record(
        task_id=task_id,
        submission=submission,
        ssh_port=ssh_port,
        node=node,
        container_name=container_name,
        vps_backend=vps_backend,
        ssh_key_mode=ssh_key_mode,
        current_user=current_user,
    )

    # Send to runner
    result = await send_vps_to_runner(
        runner_url=node.url,
        task=task,
        container_name=container_name or "",
        ssh_key_mode=ssh_key_mode,
        ssh_public_key=ssh_public_key,
        registry_image=submission.registry_image,
        vps_backend=vps_backend,
        vm_image=submission.vm_image,
        vm_disk_size=submission.vm_disk_size,
        memory_mb=submission.memory_mb,
    )

    # Handle runner rejection
    if result is None:
        task.status = "failed"
        task.error_message = "Runner rejected VPS creation."
        task.completed_at = datetime.datetime.now()
        task.save()
        raise HTTPException(
            status_code=502,
            detail="Runner rejected VPS creation.",
        )

    # Handle communication failure
    if result == {}:
        logger.warning(
            f"VPS {task.task_id} communication failed, but task remains in 'assigning' state. "
            "Runner will report actual status."
        )
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

    # Build and return success response
    return _build_vps_response(
        task=task,
        result=result,
        ssh_private_key=ssh_private_key,
        ssh_public_key=ssh_public_key,
        vps_backend=vps_backend,
        ssh_key_mode=ssh_key_mode,
    )


@router.post("/vps/stop/{task_id}", status_code=202)
async def stop_vps(
    task_id: int,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Stop a VPS instance.

    Requires 'operator' role or higher.
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

    # Check if VPS can be stopped
    stoppable_states = ["pending", "assigning", "running", "paused"]
    if task.status not in stoppable_states:
        raise HTTPException(
            status_code=409,
            detail=f"VPS cannot be stopped (state: {task.status})",
        )

    original_status = task.status

    # Mark as stopped
    task.status = "stopped"
    task.error_message = "Stopped by user."
    task.completed_at = datetime.datetime.now()
    task.save()
    logger.info(f"Marked VPS {task_id} as 'stopped'.")

    # Tell runner to stop the VPS (handles both Docker and VM)
    if original_status in ["running", "paused"] and task.assigned_node:
        node = Node.get_or_none(Node.hostname == task.assigned_node)
        if node and node.status == "online":
            logger.info(
                f"Requesting stop from runner {node.hostname} " f"for VPS {task_id}"
            )
            stop_task = asyncio.create_task(send_vps_stop_to_runner(node.url, task_id))
            background_tasks.add(stop_task)
            stop_task.add_done_callback(background_tasks.discard)

    return {"message": f"VPS {task_id} stop requested. VPS marked as stopped."}


@router.post("/vps/restart/{task_id}", status_code=202)
async def restart_vps(
    task_id: int,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Restart a VPS instance.

    Useful when nvidia docker breaks (nvml error) or container becomes unresponsive.
    This will stop the current container and create a new one with the same configuration.

    Requires 'operator' role or higher.
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

    original_status = task.status
    vps_backend = task.vps_backend or "docker"

    logger.info(
        f"Restarting VPS {task_id} on node {node.hostname} (backend={vps_backend})"
    )

    if vps_backend == "qemu":
        # VM restart: QMP system_reset (soft reboot, keeps disk/network/GPU)
        # No stop needed -- just send a reset command
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{node.url}/api/vps/{task_id}/vm-restart",
                    timeout=15.0,
                )
                resp.raise_for_status()
                result = resp.json()
        except httpx.RequestError as e:
            logger.error(f"Failed to send VM restart for VPS {task_id}: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Failed to communicate with runner for VM restart: {e}",
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Runner failed VM restart for VPS {task_id}: {e.response.status_code}"
            )
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Runner rejected VM restart: {e.response.text}",
            )

        return {
            "message": f"VM VPS {task_id} restart (QMP reset) successful.",
            "task_id": str(task_id),
            "runner_response": result,
        }

    else:
        # Docker restart: stop container, then recreate

        # Step 1: Stop the current container
        if original_status in ["running", "paused"]:
            container_name = vps_container_name(task.task_id)
            logger.info(f"Stopping VPS container {container_name} on {node.hostname}")
            await send_vps_stop_to_runner(node.url, task_id)
            # Wait briefly for container to stop
            await asyncio.sleep(2)

        # Step 2: Update task status to "assigning" for restart
        task.status = "assigning"
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        task.save()

        # Step 3: Re-send VPS creation request to runner
        base_container_name = task.container_name or config.DEFAULT_CONTAINER_NAME

        result = await send_vps_to_runner(
            runner_url=node.url,
            task=task,
            container_name=base_container_name,
            ssh_key_mode="none",  # Restart uses existing container, SSH should already be set up
            ssh_public_key=None,
            registry_image=task.registry_image,
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
