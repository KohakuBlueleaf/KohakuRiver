"""
Task Approval Endpoints.

Provides endpoints for listing, approving, and rejecting
tasks that require operator approval.
"""

import asyncio
import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from kohakuriver.db.auth import User
from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.host.auth.dependencies import require_operator
from kohakuriver.host.services.task_scheduler import (
    send_task_to_runner,
    send_vps_task_to_runner,
)
from kohakuriver.models.requests import TaskResponse
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Background tasks tracking
background_tasks: set[asyncio.Task] = set()


# =============================================================================
# Task Approval
# =============================================================================


@router.get("/tasks/pending-approval", response_model=list[TaskResponse])
async def list_pending_approval_tasks(
    current_user: Annotated[User, Depends(require_operator)],
    limit: int = 100,
    offset: int = 0,
):
    """
    List tasks awaiting approval.

    Requires 'operator' role or higher.

    Returns:
        List of tasks with status 'pending_approval'.
    """
    logger.debug(f"Listing pending approval tasks: limit={limit}, offset={offset}")

    query = (
        Task.select()
        .where(Task.status == "pending_approval")
        .order_by(Task.submitted_at.desc())
        .limit(limit)
        .offset(offset)
    )

    return [TaskResponse(**task.to_dict()) for task in query]


@router.post("/approve/{task_id}", status_code=200)
async def approve_task(
    task_id: int,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Approve a pending task for execution.

    Requires 'operator' role or higher.
    Changes task status from 'pending_approval' to 'assigning' and dispatches to runner.
    """
    logger.info(f"Approval requested for task {task_id} by {current_user.username}")

    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Task is not pending approval (status: {task.status})",
        )

    # Update task approval info
    task.approval_status = "approved"
    task.approved_by_id = current_user.id
    task.approved_at = datetime.datetime.now()
    task.status = "assigning"
    task.save()

    # Get assigned node and dispatch
    if task.assigned_node:
        node = Node.get_or_none(Node.hostname == task.assigned_node)
        if node and node.status == "online":
            # Dispatch to runner
            if task.task_type == "vps":
                result = await send_vps_task_to_runner(
                    runner_url=node.url,
                    task=task,
                    container_name=task.container_name,
                    ssh_public_key=task.command,
                    reserved_ip=None,
                    registry_image=task.registry_image,
                )
                if result is None:
                    task.status = "failed"
                    task.error_message = (
                        "Failed to dispatch VPS to runner after approval"
                    )
                    task.completed_at = datetime.datetime.now()
                    task.save()
                    raise HTTPException(
                        status_code=502, detail="Failed to dispatch VPS to runner"
                    )
            else:
                # Dispatch command task
                dispatch_coro = send_task_to_runner(
                    runner_url=node.url,
                    task=task,
                    container_name=task.container_name,
                    working_dir="/shared",
                    reserved_ip=None,
                    registry_image=task.registry_image,
                )
                bg_task = asyncio.create_task(dispatch_coro)
                background_tasks.add(bg_task)
                bg_task.add_done_callback(background_tasks.discard)
        else:
            # Node offline, set to pending for rescheduling
            task.status = "pending"
            task.assigned_node = None
            task.save()
            logger.warning(
                f"Assigned node {task.assigned_node} offline, task {task_id} set to pending"
            )

    logger.info(f"Task {task_id} approved by {current_user.username}")
    return {"message": "Task approved and dispatched", "task_id": str(task_id)}


@router.post("/reject/{task_id}", status_code=200)
async def reject_task(
    task_id: int,
    current_user: Annotated[User, Depends(require_operator)],
    reason: str | None = Query(None, description="Rejection reason"),
):
    """
    Reject a pending task.

    Requires 'operator' role or higher.
    Changes task status from 'pending_approval' to 'rejected'.
    """
    logger.info(f"Rejection requested for task {task_id} by {current_user.username}")

    task = Task.get_or_none(Task.task_id == task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if task.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Task is not pending approval (status: {task.status})",
        )

    # Update task
    task.status = "rejected"
    task.approval_status = "rejected"
    task.approved_by_id = current_user.id
    task.approved_at = datetime.datetime.now()
    task.rejection_reason = reason
    task.save()

    logger.info(f"Task {task_id} rejected by {current_user.username}: {reason}")
    return {"message": "Task rejected", "task_id": str(task_id), "reason": reason}
