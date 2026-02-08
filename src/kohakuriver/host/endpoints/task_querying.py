"""
Task Querying Endpoints.

Provides endpoints for querying task status, listing tasks,
and receiving status updates from runners.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from kohakuriver.db.auth import User, UserRole
from kohakuriver.db.task import Task
from kohakuriver.host.auth.dependencies import (
    require_role,
    require_user,
    require_viewer,
)
from kohakuriver.host.services.task_scheduler import update_task_status
from kohakuriver.models.requests import TaskResponse, TaskStatusUpdate
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


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
async def get_task_status(
    task_id: int,
    current_user: Annotated[User, Depends(require_role(UserRole.ANONY))],
):
    """
    Get status and details of a specific task.

    Access rules:
    - Anonymous users can see cluster summary but not task details
    - Viewers can see all task details
    - Users can see their own task details
    - Operators/admins can see all task details
    """
    logger.debug(f"Getting status for task {task_id}")

    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    # Check access: viewers+ can see all, users can see own tasks
    if current_user.role == UserRole.ANONY:
        raise HTTPException(
            status_code=403, detail="Anonymous users cannot view task details"
        )

    if current_user.role == UserRole.USER:
        # Users can only see their own tasks
        if task.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied to this task")

    return TaskResponse(**task.to_dict())


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    current_user: Annotated[User, Depends(require_viewer)],
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    List all command tasks (excludes VPS - use /vps endpoint for VPS).

    Requires 'viewer' role or higher (viewers, operators, admins).
    Users should use /tasks/my endpoint to see their own tasks.

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


@router.get("/tasks/my", response_model=list[TaskResponse])
async def list_my_tasks(
    current_user: Annotated[User, Depends(require_user)],
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    List tasks owned by the current user.

    Requires 'user' role or higher.

    Args:
        status: Filter by task status.
        limit: Maximum number of tasks to return.
        offset: Number of tasks to skip.

    Returns:
        List of task responses owned by current user.
    """
    logger.debug(f"Listing my tasks: user={current_user.username}, status={status}")

    query = (
        Task.select()
        .where((Task.task_type == "command") & (Task.owner_id == current_user.id))
        .order_by(Task.submitted_at.desc())
    )

    if status:
        query = query.where(Task.status == status)

    query = query.limit(limit).offset(offset)

    return [TaskResponse(**task.to_dict()) for task in query]
