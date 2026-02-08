"""
VM instance management endpoints.

Handles listing and deleting VM instances across runner nodes.
"""

import asyncio
import datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException

from kohakuriver.db.auth import User
from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.host.auth.dependencies import require_admin, require_viewer
from kohakuriver.host.endpoints.vps_querying import _get_vps_owner_username
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/vm/images/{hostname}")
async def get_vm_images(
    hostname: str,
    current_user: Annotated[User, Depends(require_viewer)],
):
    """
    List available VM base images on a specific runner node.

    Proxies the request to the runner's /api/vm/images endpoint.
    Requires 'viewer' role or higher.
    """
    node = Node.get_or_none(Node.hostname == hostname)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{hostname}' not found.")
    if node.status != "online":
        raise HTTPException(status_code=503, detail=f"Node '{hostname}' is not online.")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{node.url}/api/vm/images",
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Failed to fetch VM images from {hostname}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to communicate with runner '{hostname}': {e}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text,
        )


async def _fetch_runner_vm_instances(node: Node) -> dict:
    """Fetch VM instances from a single runner node."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{node.url}/api/vps/vm-instances",
                timeout=15.0,
            )
            response.raise_for_status()
            data = response.json()
            return {
                "hostname": node.hostname,
                "status": "online",
                "instances": data.get("instances", []),
                "instances_dir": data.get("instances_dir"),
                "total_disk_usage_bytes": data.get("total_disk_usage_bytes", 0),
            }
    except Exception as e:
        logger.warning(f"Failed to fetch VM instances from {node.hostname}: {e}")
        return {
            "hostname": node.hostname,
            "status": "unreachable",
            "instances": None,
            "instances_dir": None,
            "total_disk_usage_bytes": 0,
            "error": str(e),
        }


def _enrich_instance_with_db(instance: dict) -> dict:
    """Cross-reference a VM instance with the Task database."""
    task_id = int(instance["task_id"])
    task = Task.get_or_none(Task.task_id == task_id)

    if task:
        instance["db_status"] = task.status
        instance["task_metadata"] = {
            "status": task.status,
            "name": task.name,
            "owner_id": task.owner_id,
            "owner_username": _get_vps_owner_username(task.owner_id),
            "vm_image": task.vm_image,
            "required_cores": task.required_cores,
            "ssh_port": task.ssh_port,
            "submitted_at": (
                task.submitted_at.isoformat() if task.submitted_at else None
            ),
            "assigned_node": task.assigned_node,
        }
    else:
        instance["db_status"] = "orphaned"
        instance["task_metadata"] = None

    return instance


@router.get("/vps/vm-instances")
async def list_all_vm_instances(
    current_user: Annotated[User, Depends(require_admin)],
):
    """List VM instances across all nodes with DB cross-reference.

    Requires admin role. Aggregates data from all runner nodes
    and enriches with Task DB metadata.
    """
    nodes = list(Node.select())

    # Fetch from online nodes in parallel
    online_nodes = [n for n in nodes if n.status == "online"]
    offline_nodes = [n for n in nodes if n.status != "online"]

    tasks = [_fetch_runner_vm_instances(node) for node in online_nodes]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    node_results = []
    total_instances = 0
    orphaned_count = 0
    total_disk_usage = 0

    for result in results:
        if isinstance(result, Exception):
            continue
        # Enrich each instance with DB info
        if result["instances"]:
            for inst in result["instances"]:
                _enrich_instance_with_db(inst)
                total_instances += 1
                if inst.get("db_status") == "orphaned":
                    orphaned_count += 1
        total_disk_usage += result.get("total_disk_usage_bytes", 0)
        node_results.append(result)

    # Add offline nodes
    for node in offline_nodes:
        node_results.append(
            {
                "hostname": node.hostname,
                "status": "unreachable",
                "instances": None,
                "instances_dir": None,
                "total_disk_usage_bytes": 0,
            }
        )

    return {
        "nodes": node_results,
        "summary": {
            "total_instances": total_instances,
            "orphaned_count": orphaned_count,
            "total_disk_usage_bytes": total_disk_usage,
        },
    }


@router.delete("/vps/vm-instances/{task_id}")
async def delete_vm_instance(
    task_id: int,
    current_user: Annotated[User, Depends(require_admin)],
    hostname: str | None = None,
    force: bool = False,
):
    """Delete a VM instance directory on a runner node.

    Requires admin role. Forwards the delete request to the appropriate runner.

    If the task exists in DB, uses its assigned_node. Otherwise, hostname
    query parameter is required to identify the runner.
    """
    # Look up task in DB
    task = Task.get_or_none(Task.task_id == task_id)

    if task and task.assigned_node:
        target_hostname = task.assigned_node
    elif hostname:
        target_hostname = hostname
    else:
        raise HTTPException(
            status_code=400,
            detail="Task not found in DB. Provide 'hostname' query parameter to identify the runner.",
        )

    # Find node
    node = Node.get_or_none(Node.hostname == target_hostname)
    if not node:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{target_hostname}' not found.",
        )
    if node.status != "online":
        raise HTTPException(
            status_code=503,
            detail=f"Node '{target_hostname}' is not online.",
        )

    # Forward delete to runner
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{node.url}/api/vps/vm-instances/{task_id}",
                params={"force": str(force).lower()},
                timeout=60.0,
            )
            response.raise_for_status()
            runner_result = response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=e.response.text,
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to communicate with runner '{target_hostname}': {e}",
        )

    # Update Task DB if task exists with active status and force was used
    if task and force and task.status in ("running", "paused", "assigning"):
        task.status = "stopped"
        task.error_message = "Stopped by admin (VM instance cleanup)."
        task.completed_at = datetime.datetime.now()
        task.save()
        logger.info(
            f"Marked task {task_id} as stopped after forced VM instance deletion"
        )

    return runner_result
