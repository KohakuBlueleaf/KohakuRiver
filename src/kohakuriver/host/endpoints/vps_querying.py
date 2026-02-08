"""
VPS querying endpoints.

Handles listing and filtering VPS instances.
"""

import json
from typing import Annotated

import peewee
from fastapi import APIRouter, Depends, HTTPException

from kohakuriver.db.auth import User, VpsAssignment
from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.host.auth.dependencies import require_user, require_viewer
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _get_vps_owner_username(owner_id: int | None) -> str | None:
    """Get username for owner_id."""
    if not owner_id:
        return None
    try:
        user = User.get_or_none(User.id == owner_id)
        return user.username if user else None
    except Exception:
        return None


def _get_vps_assignees(task_id: int) -> list[dict]:
    """Get list of users assigned to a VPS."""
    try:
        assignments = VpsAssignment.select().where(VpsAssignment.vps_task_id == task_id)
        assignees = []
        for assignment in assignments:
            user = assignment.user
            if user:
                assignees.append(
                    {
                        "id": user.id,
                        "username": user.username,
                        "display_name": user.display_name,
                    }
                )
        return assignees
    except Exception:
        return []


@router.get("/vps")
async def get_vps_list(
    current_user: Annotated[User, Depends(require_viewer)],
):
    """
    Get list of ALL VPS tasks.

    Requires 'viewer' role or higher.
    Users should use /vps/my endpoint to see their assigned VPS.
    """
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
                    "name": task.name,
                    "owner_id": task.owner_id,
                    "owner_username": _get_vps_owner_username(task.owner_id),
                    "assignees": _get_vps_assignees(task.task_id),
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
                    "vps_backend": task.vps_backend,
                    "vm_image": task.vm_image,
                    "vm_ip": task.vm_ip,
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
async def get_active_vps_status(
    current_user: Annotated[User, Depends(require_viewer)],
):
    """
    Get list of active VPS instances.

    Requires 'viewer' role or higher.
    """
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
                    "name": task.name,
                    "owner_id": task.owner_id,
                    "owner_username": _get_vps_owner_username(task.owner_id),
                    "assignees": _get_vps_assignees(task.task_id),
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
                    "vps_backend": task.vps_backend,
                    "vm_image": task.vm_image,
                    "vm_ip": task.vm_ip,
                }
            )

        return vps_list

    except peewee.PeeweeException as e:
        logger.error(f"Database error fetching active VPS: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database error fetching active VPS.",
        )


@router.get("/vps/my")
async def get_my_vps(
    current_user: Annotated[User, Depends(require_user)],
):
    """
    Get list of VPS instances assigned to the current user.

    Requires 'user' role or higher.
    """
    logger.debug(f"Fetching VPS list for user {current_user.username}")

    try:
        # Get VPS task IDs assigned to this user
        assigned_vps_ids = [
            assignment.vps_task_id
            for assignment in VpsAssignment.select().where(
                VpsAssignment.user == current_user
            )
        ]

        if not assigned_vps_ids:
            return []

        query = (
            Task.select()
            .where((Task.task_type == "vps") & (Task.task_id.in_(assigned_vps_ids)))
            .order_by(Task.submitted_at.desc())
        )

        vps_list = []
        for task in query:
            vps_list.append(
                {
                    "task_id": str(task.task_id),
                    "name": task.name,
                    "owner_id": task.owner_id,
                    "owner_username": _get_vps_owner_username(task.owner_id),
                    "assignees": _get_vps_assignees(task.task_id),
                    "required_cores": task.required_cores,
                    "required_gpus": (
                        json.loads(task.required_gpus) if task.required_gpus else []
                    ),
                    "required_memory_bytes": task.required_memory_bytes,
                    "status": task.status,
                    "assigned_node": task.assigned_node,
                    "target_numa_node_id": task.target_numa_node_id,
                    "container_name": task.container_name,
                    "ssh_port": task.ssh_port,
                    "vps_backend": task.vps_backend,
                    "vm_image": task.vm_image,
                    "vm_ip": task.vm_ip,
                    "submitted_at": task.submitted_at,
                    "started_at": task.started_at,
                }
            )

        return vps_list

    except peewee.PeeweeException as e:
        logger.error(f"Database error fetching user VPS: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database error fetching VPS.",
        )
