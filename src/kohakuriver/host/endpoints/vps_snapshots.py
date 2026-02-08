"""
VPS snapshot proxy endpoints.

Proxies snapshot operations to the runner nodes hosting the VPS instances.
"""

import httpx
from fastapi import APIRouter, HTTPException

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


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
