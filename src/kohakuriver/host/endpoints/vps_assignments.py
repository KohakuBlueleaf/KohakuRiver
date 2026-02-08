"""
VPS assignment endpoints.

Handles assigning and unassigning users to/from VPS instances.
"""

from typing import Annotated

import peewee
from fastapi import APIRouter, Depends, HTTPException

from kohakuriver.db.auth import User, VpsAssignment
from kohakuriver.db.task import Task
from kohakuriver.host.auth.dependencies import require_operator
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.post("/vps/{task_id}/assign")
async def assign_vps_to_users(
    task_id: int,
    user_ids: list[int],
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Assign VPS access to one or more users.

    Requires 'operator' role or higher.

    Args:
        task_id: VPS task ID.
        user_ids: List of user IDs to assign.
    """
    task = Task.get_or_none((Task.task_id == task_id) & (Task.task_type == "vps"))
    if not task:
        raise HTTPException(status_code=404, detail="VPS not found.")

    # Validate all users exist
    for user_id in user_ids:
        user = User.get_or_none(User.id == user_id)
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} not found.",
            )

    # Create assignments (ignore duplicates)
    created = 0
    for user_id in user_ids:
        try:
            VpsAssignment.create(
                vps_task_id=task_id,
                user_id=user_id,
            )
            created += 1
        except peewee.IntegrityError:
            # Already assigned
            pass

    logger.info(
        f"Operator '{current_user.username}' assigned VPS {task_id} to {created} users"
    )

    return {
        "message": f"VPS {task_id} assigned to {created} user(s).",
        "task_id": task_id,
        "assigned_users": user_ids,
    }


@router.delete("/vps/{task_id}/assign/{user_id}")
async def unassign_vps_from_user(
    task_id: int,
    user_id: int,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Remove VPS access from a user.

    Requires 'operator' role or higher.

    Args:
        task_id: VPS task ID.
        user_id: User ID to unassign.
    """
    task = Task.get_or_none((Task.task_id == task_id) & (Task.task_type == "vps"))
    if not task:
        raise HTTPException(status_code=404, detail="VPS not found.")

    deleted = (
        VpsAssignment.delete()
        .where(
            (VpsAssignment.vps_task_id == task_id) & (VpsAssignment.user_id == user_id)
        )
        .execute()
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"User {user_id} is not assigned to VPS {task_id}.",
        )

    logger.info(
        f"Operator '{current_user.username}' unassigned user {user_id} from VPS {task_id}"
    )

    return {
        "message": f"User {user_id} unassigned from VPS {task_id}.",
    }


@router.get("/vps/{task_id}/assignments")
async def get_vps_assignments(
    task_id: int,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Get list of users assigned to a VPS.

    Requires 'operator' role or higher.
    """
    task = Task.get_or_none((Task.task_id == task_id) & (Task.task_type == "vps"))
    if not task:
        raise HTTPException(status_code=404, detail="VPS not found.")

    assignments = (
        VpsAssignment.select(VpsAssignment, User)
        .join(User)
        .where(VpsAssignment.vps_task_id == task_id)
    )

    return {
        "task_id": task_id,
        "assignments": [
            {
                "user_id": a.user.id,
                "username": a.user.username,
                "display_name": a.user.display_name,
                "assigned_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in assignments
        ],
    }
