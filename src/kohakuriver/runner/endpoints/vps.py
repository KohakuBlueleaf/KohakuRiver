"""
VPS management endpoints.

Handles VPS creation, control, and snapshot requests.
"""

import asyncio
import os
import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from kohakuriver.models.requests import VPSCreateRequest
from kohakuriver.qemu.naming import vm_instance_dir, vm_pidfile_path, vm_qmp_socket_path
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
from kohakuriver.runner.services.vm_vps_manager import (
    create_vm_vps,
    get_vm_status,
    mark_vm_ready,
    receive_vm_heartbeat,
    restart_vm_vps,
    stop_vm_vps,
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


@router.get("/vm/images")
async def list_vm_images():
    """List available VM base images (qcow2 files) on this runner."""
    images_dir = config.VM_IMAGES_DIR
    images = []

    if not os.path.isdir(images_dir):
        return {"images": [], "images_dir": images_dir}

    for entry in os.scandir(images_dir):
        if entry.name.endswith(".qcow2") and entry.is_file():
            stat = entry.stat()
            name = entry.name.removesuffix(".qcow2")
            images.append(
                {
                    "name": name,
                    "filename": entry.name,
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )

    images.sort(key=lambda x: x["name"])
    return {"images": images, "images_dir": images_dir}


@router.post("/vps/create")
async def create_vps_endpoint(request: VPSCreateRequest):
    """Create a VPS container or VM."""
    task_id = request.task_id

    # Check if already running
    if task_store and task_store.get_task(task_id):
        logger.warning(f"VPS {task_id} is already running.")
        raise HTTPException(
            status_code=409,
            detail=f"VPS {task_id} is already running on this node.",
        )

    # Dispatch based on backend
    if request.vps_backend == "qemu":
        return await _create_vm_vps(request)
    else:
        return await _create_docker_vps(request)


async def _create_docker_vps(request: VPSCreateRequest):
    """Create a Docker-based VPS."""
    task_id = request.task_id

    # Check local temp directory
    if not os.path.isdir(config.LOCAL_TEMP_DIR):
        logger.error(f"Local temp directory '{config.LOCAL_TEMP_DIR}' not found.")
        raise HTTPException(
            status_code=500,
            detail="Configuration error: LOCAL_TEMP_DIR missing on node.",
        )

    ssh_key_mode = request.ssh_key_mode or "upload"
    logger.info(
        f"Creating Docker VPS {task_id} with {request.required_cores} cores, "
        f"SSH port {request.ssh_port}, ssh_key_mode={ssh_key_mode}"
    )

    result = await create_vps(
        task_id=task_id,
        required_cores=request.required_cores,
        required_gpus=request.required_gpus or [],
        required_memory_bytes=request.required_memory_bytes,
        target_numa_node_id=request.target_numa_node_id,
        container_name=request.container_name,
        registry_image=request.registry_image,
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


async def _create_vm_vps(request: VPSCreateRequest):
    """Create a QEMU VM-based VPS."""
    task_id = request.task_id

    vm_image = request.vm_image or "ubuntu-24.04"
    memory_mb = request.memory_mb or config.VM_DEFAULT_MEMORY_MB
    disk_size = request.vm_disk_size or config.VM_DEFAULT_DISK_SIZE

    logger.info(
        f"Creating VM VPS {task_id} with {request.required_cores} cores, "
        f"{memory_mb}MB RAM, image={vm_image}, disk={disk_size}"
    )

    result = await create_vm_vps(
        task_id=task_id,
        vm_image=vm_image,
        cores=request.required_cores,
        memory_mb=memory_mb,
        disk_size=disk_size,
        gpu_ids=request.required_gpus,
        ssh_public_key=request.ssh_public_key,
        ssh_port=request.ssh_port,
        task_store=task_store,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "VM VPS creation failed."),
        )

    return result


@router.post("/vps/stop/{task_id}")
async def stop_vps_endpoint(task_id: int):
    """Stop a running VPS (Docker or VM)."""
    logger.info(f"Received stop request for VPS {task_id}")

    if not task_store or not task_store.get_task(task_id):
        logger.warning(f"Stop request for unknown VPS {task_id}")
        raise HTTPException(
            status_code=404,
            detail=f"VPS {task_id} not found.",
        )

    # Check if this is a VM VPS
    task_info = task_store.get_task(task_id)
    container_name = task_info.get("container_name", "") if task_info else ""

    if container_name and container_name.startswith("vm-"):
        success = await stop_vm_vps(task_id, task_store)
    else:
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
    snapshot_tag = await asyncio.to_thread(create_snapshot, task_id, message or "")

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

    success = await asyncio.to_thread(delete_snapshot, task_id, timestamp)
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

    count = await asyncio.to_thread(delete_all_snapshots, task_id)
    return {
        "message": f"Deleted {count} snapshot(s) for VPS {task_id}",
        "deleted_count": count,
    }


@router.get("/vps/snapshots/{task_id}/latest")
async def get_latest_snapshot_endpoint(task_id: int):
    """Get the latest snapshot for a VPS."""
    logger.info(f"Getting latest snapshot for VPS {task_id}")

    tag = await asyncio.to_thread(get_latest_snapshot, task_id)
    if not tag:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshots found for VPS {task_id}.",
        )

    return {
        "task_id": task_id,
        "tag": tag,
    }


# =============================================================================
# VM VPS Endpoints
# =============================================================================


@router.get("/vps/{task_id}/vm-status")
async def vm_status_endpoint(task_id: int):
    """Get VM status."""
    status = await get_vm_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"VM {task_id} not found.")
    return status


@router.post("/vps/{task_id}/vm-restart")
async def vm_restart_endpoint(task_id: int):
    """Restart a VM."""
    success = await restart_vm_vps(task_id)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to restart VM {task_id}.")
    return {"message": f"VM {task_id} restarted."}


class VMHeartbeatPayload(BaseModel):
    """Payload from VM agent heartbeat."""

    task_id: int
    timestamp: float | None = None
    gpus: list[dict] | None = None
    system: dict | None = None
    status: str = "healthy"


@router.post("/vps/{task_id}/vm-heartbeat")
async def vm_heartbeat_endpoint(task_id: int, payload: VMHeartbeatPayload):
    """Receive heartbeat from VM agent."""
    await receive_vm_heartbeat(task_id, payload.model_dump())
    return {"status": "ok"}


@router.post("/vps/{task_id}/vm-phone-home")
async def vm_phone_home_endpoint(task_id: int):
    """Receive phone-home callback from cloud-init inside VM."""
    await mark_vm_ready(task_id)
    return {"status": "ok"}


# =============================================================================
# VM Instance Management Endpoints
# =============================================================================


def _scan_instance_dir(instances_dir: str, task_store) -> dict:
    """Scan VM instances directory and collect info (blocking, run via to_thread)."""
    instances = []
    total_disk_usage = 0

    if not os.path.isdir(instances_dir):
        return {
            "instances_dir": instances_dir,
            "instances": [],
            "total_disk_usage_bytes": 0,
        }

    for entry in os.scandir(instances_dir):
        if not entry.is_dir():
            continue

        # Only consider directories with integer names (task IDs)
        try:
            tid = int(entry.name)
        except ValueError:
            continue

        instance_dir = entry.path
        disk_usage = 0
        files = []

        for f in os.scandir(instance_dir):
            if f.is_file(follow_symlinks=False):
                files.append(f.name)
                try:
                    st = f.stat(follow_symlinks=False)
                    disk_usage += st.st_blocks * 512
                except OSError:
                    pass

        # Check QEMU running via pidfile
        qemu_running = False
        qemu_pid = None
        pidfile = vm_pidfile_path(instance_dir)
        if os.path.isfile(pidfile):
            try:
                with open(pidfile) as pf:
                    pid = int(pf.read().strip())
                os.kill(pid, 0)
                qemu_running = True
                qemu_pid = pid
            except (ValueError, OSError, ProcessLookupError):
                pass

        # Also check QMP socket existence
        if not qemu_running and os.path.exists(vm_qmp_socket_path(tid)):
            # Socket exists but process not found via pidfile - stale
            pass

        # Check task store
        in_task_store = False
        if task_store:
            in_task_store = task_store.get_task(tid) is not None

        total_disk_usage += disk_usage
        instances.append(
            {
                "task_id": str(tid),
                "disk_usage_bytes": disk_usage,
                "files": sorted(files),
                "qemu_running": qemu_running,
                "qemu_pid": qemu_pid,
                "in_task_store": in_task_store,
            }
        )

    instances.sort(key=lambda x: int(x["task_id"]))

    return {
        "instances_dir": instances_dir,
        "instances": instances,
        "total_disk_usage_bytes": total_disk_usage,
    }


@router.get("/vps/vm-instances")
async def list_vm_instances():
    """List all VM instance directories with disk usage and status."""
    instances_dir = config.VM_INSTANCES_DIR
    result = await asyncio.to_thread(_scan_instance_dir, instances_dir, task_store)
    return result


@router.delete("/vps/vm-instances/{task_id}")
async def delete_vm_instance(task_id: int, force: bool = False):
    """Delete a VM instance directory.

    Refuses to delete if QEMU is still running unless force=True.
    If force=True and QEMU is running, stops the VM first.
    """
    instances_dir = config.VM_INSTANCES_DIR
    instance_dir = vm_instance_dir(instances_dir, task_id)

    if not os.path.isdir(instance_dir):
        raise HTTPException(
            status_code=404,
            detail=f"VM instance directory for task {task_id} not found.",
        )

    # Check if QEMU is running
    qemu_running = False
    pidfile = vm_pidfile_path(instance_dir)
    if os.path.isfile(pidfile):
        try:

            def _read_pidfile():
                with open(pidfile) as pf:
                    return int(pf.read().strip())

            pid = await asyncio.to_thread(_read_pidfile)
            os.kill(pid, 0)
            qemu_running = True
        except (ValueError, OSError, ProcessLookupError):
            pass

    if qemu_running and not force:
        raise HTTPException(
            status_code=409,
            detail=f"QEMU is still running for task {task_id}. Use force=true to stop and delete.",
        )

    if qemu_running and force:
        logger.info(f"Force-stopping VM {task_id} before deletion")
        try:
            await stop_vm_vps(task_id, task_store)
        except Exception as e:
            logger.warning(f"Failed to gracefully stop VM {task_id}: {e}")

    # Calculate freed bytes before deletion
    def _calc_and_delete():
        freed = 0
        for root, dirs, files in os.walk(instance_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    st = os.stat(fpath, follow_symlinks=False)
                    freed += st.st_blocks * 512
                except OSError:
                    pass
        shutil.rmtree(instance_dir)
        return freed

    freed_bytes = await asyncio.to_thread(_calc_and_delete)

    # Remove QMP socket if exists
    qmp_path = vm_qmp_socket_path(task_id)
    try:
        os.unlink(qmp_path)
    except FileNotFoundError:
        pass

    # Remove from task store if present
    if task_store:
        task_store.remove_task(task_id)

    logger.info(
        f"Deleted VM instance {task_id}, freed {freed_bytes / (1024**2):.1f} MB"
    )

    return {
        "message": f"VM instance {task_id} deleted.",
        "task_id": str(task_id),
        "freed_bytes": freed_bytes,
    }
