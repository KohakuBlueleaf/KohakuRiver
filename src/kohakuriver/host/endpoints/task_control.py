"""
Task Control Endpoints.

Provides endpoints for task lifecycle control including kill,
pause/resume commands, and stdout/stderr output retrieval.
"""

import asyncio
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from kohakuriver.db.auth import User, UserRole
from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.host.auth.dependencies import require_role, require_user
from kohakuriver.docker.naming import task_container_name, vps_container_name
from kohakuriver.host.services.task_scheduler import (
    mark_task_killed,
    send_kill_to_runner,
    send_pause_to_runner,
    send_resume_to_runner,
)
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Background tasks tracking
background_tasks: set[asyncio.Task] = set()


# =============================================================================
# Task Control
# =============================================================================


@router.post("/kill/{task_id}", status_code=202)
async def request_kill_task(
    task_id: int,
    current_user: Annotated[User, Depends(require_user)],
):
    """
    Request to kill a running task.

    Access rules:
    - Users can kill their own tasks
    - Operators/admins can kill any task

    Marks the task as killed and sends kill signal to the runner
    if the task is currently running.
    """
    logger.info(f"Kill requested for task {task_id}")

    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    # Check access: users can kill own tasks, operators+ can kill any
    if current_user.role == UserRole.USER:
        if task.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied to this task")

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
async def send_command_to_task(
    task_id: int,
    command: str,
    current_user: Annotated[User, Depends(require_user)],
):
    """
    Send a control command (pause/resume) to a task.

    Access rules:
    - Users can pause/resume their own tasks
    - Operators/admins can pause/resume any task

    Args:
        task_id: Target task ID.
        command: Command to send ('pause' or 'resume').
    """
    logger.info(f"Command '{command}' for task {task_id}")

    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    # Check access: users can control own tasks, operators+ can control any
    if current_user.role == UserRole.USER:
        if task.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied to this task")

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
async def get_task_stdout(
    task_id: int,
    current_user: Annotated[User, Depends(require_role(UserRole.USER))],
    lines: int | None = None,
):
    """
    Get stdout output from a task.

    Access rules:
    - Users can view logs of their own tasks
    - Viewers/operators/admins can view any task logs

    Args:
        task_id: Task ID.
        lines: Number of lines to return (from end of file). If None, return all.

    Returns:
        Plain text stdout content.
    """
    return await _get_task_output(task_id, "stdout", lines, current_user)


@router.get("/tasks/{task_id}/stderr", response_class=PlainTextResponse)
async def get_task_stderr(
    task_id: int,
    current_user: Annotated[User, Depends(require_role(UserRole.USER))],
    lines: int | None = None,
):
    """
    Get stderr output from a task.

    Access rules:
    - Users can view logs of their own tasks
    - Viewers/operators/admins can view any task logs

    Args:
        task_id: Task ID.
        lines: Number of lines to return (from end of file). If None, return all.

    Returns:
        Plain text stderr content.
    """
    return await _get_task_output(task_id, "stderr", lines, current_user)


async def _get_task_output(
    task_id: int,
    output_type: str,
    lines: int | None,
    current_user: User,
) -> str:
    """Helper to get task stdout or stderr."""
    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    # Check access: users can view own task logs, viewers+ can view any
    if current_user.role == UserRole.USER:
        if task.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied to this task")

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

        def _read_output():
            with open(output_path) as f:
                if lines is not None:
                    content = f.readlines()[-lines:]
                    return "".join(content)
                else:
                    return f.read()

        result = await asyncio.to_thread(_read_output)
        logger.info(f"{output_type} for task {task_id}: {len(result)} chars")
        return result
    except Exception as e:
        logger.error(f"Error reading {output_type} for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading {output_type}.")
