"""
VPS management endpoints.

Handles VPS creation, control, and snapshot requests.
"""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from kohakuriver.models.requests import VPSCreateRequest
from kohakuriver.runner.config import config
from kohakuriver.runner.services.vps_manager import (
    create_snapshot,
    create_vps,
    delete_all_snapshots,
    delete_snapshot,
    get_latest_snapshot,
    list_snapshots,
    pause_vps,
    resume_vps,
    stop_vps,
)
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# These will be set by the app on startup
task_store = None


def set_dependencies(store):
    """Set module dependencies from app startup."""
    global task_store
    task_store = store


@router.post("/vps/create")
async def create_vps_endpoint(request: VPSCreateRequest):
    """Create a VPS container."""
    task_id = request.task_id

    # Check if already running
    if task_store and task_store.get_task(task_id):
        logger.warning(f"VPS {task_id} is already running.")
        raise HTTPException(
            status_code=409,
            detail=f"VPS {task_id} is already running on this node.",
        )

    # Check local temp directory
    if not os.path.isdir(config.LOCAL_TEMP_DIR):
        logger.error(f"Local temp directory '{config.LOCAL_TEMP_DIR}' not found.")
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: LOCAL_TEMP_DIR missing on node.",
        )

    ssh_key_mode = request.ssh_key_mode or "upload"
    logger.info(
        f"Creating VPS {task_id} with {request.required_cores} cores, "
        f"SSH port {request.ssh_port}, ssh_key_mode={ssh_key_mode}"
    )

    result = await create_vps(
        task_id=task_id,
        required_cores=request.required_cores,
        required_gpus=request.required_gpus or [],
        required_memory_bytes=request.required_memory_bytes,
        target_numa_node_id=request.target_numa_node_id,
        container_name=request.container_name,
        ssh_key_mode=ssh_key_mode,
        ssh_public_key=request.ssh_public_key,
        ssh_port=request.ssh_port,
        task_store=task_store,
        reserved_ip=request.reserved_ip,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "VPS creation failed."),
        )

    return result


@router.post("/vps/stop/{task_id}")
async def stop_vps_endpoint(task_id: int):
    """Stop a running VPS."""
    logger.info(f"Received stop request for VPS {task_id}")

    if not task_store or not task_store.get_task(task_id):
        logger.warning(f"Stop request for unknown VPS {task_id}")
        raise HTTPException(
            status_code=404,
            detail=f"VPS {task_id} not found.",
        )

    success = await stop_vps(task_id, task_store)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop VPS {task_id}.",
        )

    return {"message": f"VPS {task_id} stopped."}


@router.post("/vps/pause/{task_id}")
async def pause_vps_endpoint(task_id: int):
    """Pause a running VPS."""
    logger.info(f"Received pause request for VPS {task_id}")

    if not task_store or not task_store.get_task(task_id):
        logger.warning(f"Pause request for unknown VPS {task_id}")
        raise HTTPException(
            status_code=404,
            detail=f"VPS {task_id} not found.",
        )

    success = await pause_vps(task_id, task_store)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to pause VPS {task_id}.",
        )

    return {"message": f"VPS {task_id} paused."}


@router.post("/vps/resume/{task_id}")
async def resume_vps_endpoint(task_id: int):
    """Resume a paused VPS."""
    logger.info(f"Received resume request for VPS {task_id}")

    if not task_store or not task_store.get_task(task_id):
        logger.warning(f"Resume request for unknown VPS {task_id}")
        raise HTTPException(
            status_code=404,
            detail=f"VPS {task_id} not found.",
        )

    success = await resume_vps(task_id, task_store)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resume VPS {task_id}.",
        )

    return {"message": f"VPS {task_id} resumed."}


# =============================================================================
# Snapshot Endpoints
# =============================================================================


class CreateSnapshotRequest(BaseModel):
    """Request model for creating a snapshot."""

    message: str | None = None


@router.get("/vps/snapshots/{task_id}")
async def list_snapshots_endpoint(task_id: int):
    """
    List all snapshots for a VPS.

    Note: This works even if the VPS is not currently running,
    as snapshots are stored as Docker images.
    """
    logger.info(f"Listing snapshots for VPS {task_id}")

    snapshots = list_snapshots(task_id)
    return {
        "task_id": task_id,
        "snapshots": snapshots,
        "count": len(snapshots),
    }


@router.post("/vps/snapshots/{task_id}")
async def create_snapshot_endpoint(
    task_id: int,
    request: CreateSnapshotRequest | None = None,
):
    """
    Create a snapshot of the current VPS state.

    The VPS must be running to create a snapshot.
    """
    logger.info(f"Creating snapshot for VPS {task_id}")

    if not task_store or not task_store.get_task(task_id):
        logger.warning(f"Snapshot request for VPS {task_id} which is not running")
        raise HTTPException(
            status_code=404,
            detail=f"VPS {task_id} is not running on this node.",
        )

    message = request.message if request else None
    snapshot_tag = create_snapshot(task_id, message=message or "")

    if not snapshot_tag:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create snapshot for VPS {task_id}.",
        )

    return {
        "message": f"Snapshot created for VPS {task_id}",
        "tag": snapshot_tag,
    }


@router.delete("/vps/snapshots/{task_id}/{timestamp}")
async def delete_snapshot_endpoint(task_id: int, timestamp: int):
    """Delete a specific snapshot by timestamp."""
    logger.info(f"Deleting snapshot {timestamp} for VPS {task_id}")

    success = delete_snapshot(task_id, timestamp)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot not found or failed to delete.",
        )

    return {"message": f"Snapshot {timestamp} deleted for VPS {task_id}"}


@router.delete("/vps/snapshots/{task_id}")
async def delete_all_snapshots_endpoint(task_id: int):
    """Delete all snapshots for a VPS."""
    logger.info(f"Deleting all snapshots for VPS {task_id}")

    count = delete_all_snapshots(task_id)
    return {
        "message": f"Deleted {count} snapshot(s) for VPS {task_id}",
        "deleted_count": count,
    }


@router.get("/vps/snapshots/{task_id}/latest")
async def get_latest_snapshot_endpoint(task_id: int):
    """Get the latest snapshot for a VPS."""
    logger.info(f"Getting latest snapshot for VPS {task_id}")

    tag = get_latest_snapshot(task_id)
    if not tag:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshots found for VPS {task_id}.",
        )

    return {
        "task_id": task_id,
        "tag": tag,
    }
