"""
VPS management service.

Handles VPS snapshot management and lifecycle operations (stop, pause, resume).
VPS creation logic lives in vps_creation.py; create_vps is re-exported here
so existing import paths continue to work.
"""

import asyncio
import subprocess
import time

import docker

from kohakuriver.docker.naming import (
    SNAPSHOT_PREFIX,
    parse_snapshot_tag,
    snapshot_image_tag,
    vps_container_name,
)
from kohakuriver.runner.config import config
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import get_logger

# Re-export create_vps so that
#   from kohakuriver.runner.services.vps_manager import create_vps
# keeps working.
from kohakuriver.runner.services.vps_creation import create_vps  # noqa: F401

logger = get_logger(__name__)


# =============================================================================
# Snapshot Management Functions
# =============================================================================


def list_snapshots(task_id: int) -> list[dict]:
    """
    List all snapshots for a VPS task.

    Args:
        task_id: VPS task ID.

    Returns:
        List of snapshot info dicts, sorted by timestamp (newest first).
        Each dict contains: tag, task_id, timestamp, size, created_at
    """
    try:
        client = docker.from_env(timeout=30)
        prefix = f"{SNAPSHOT_PREFIX}/vps-{task_id}:"

        snapshots = []
        for image in client.images.list():
            for tag in image.tags or []:
                if tag.startswith(prefix):
                    parsed = parse_snapshot_tag(tag)
                    if parsed:
                        _, timestamp = parsed
                        # Get image size
                        size = image.attrs.get("Size", 0)
                        created_at = image.attrs.get("Created", "")
                        snapshots.append(
                            {
                                "tag": tag,
                                "task_id": task_id,
                                "timestamp": timestamp,
                                "size": size,
                                "created_at": created_at,
                            }
                        )

        # Sort by timestamp, newest first
        snapshots.sort(key=lambda x: x["timestamp"], reverse=True)
        return snapshots

    except Exception as e:
        logger.error(f"Failed to list snapshots for VPS {task_id}: {e}")
        return []


def get_latest_snapshot(task_id: int) -> str | None:
    """
    Get the latest snapshot image tag for a VPS task.

    Args:
        task_id: VPS task ID.

    Returns:
        Image tag of the latest snapshot, or None if no snapshots exist.
    """
    snapshots = list_snapshots(task_id)
    if snapshots:
        return snapshots[0]["tag"]
    return None


def create_snapshot(task_id: int, message: str = "") -> str | None:
    """
    Create a snapshot of the current VPS container state.

    Args:
        task_id: VPS task ID.
        message: Optional commit message/description.

    Returns:
        Image tag of the created snapshot, or None if failed.
    """
    container_name = vps_container_name(task_id)
    timestamp = int(time.time())
    tag = snapshot_image_tag(task_id, timestamp)

    logger.info(f"[Snapshot] Creating snapshot for VPS {task_id}: {tag}")

    try:
        client = docker.from_env(timeout=None)

        # Get the container
        try:
            container = client.containers.get(container_name)
        except docker.errors.NotFound:
            logger.error(f"[Snapshot] Container '{container_name}' not found.")
            return None

        # Commit the container to create snapshot image
        # Using pause=True to ensure filesystem consistency
        logger.debug(f"[Snapshot] Committing container {container_name}...")
        image = container.commit(
            repository=f"{SNAPSHOT_PREFIX}/vps-{task_id}",
            tag=str(timestamp),
            message=message or f"VPS {task_id} snapshot at {timestamp}",
            pause=True,
        )

        logger.info(f"[Snapshot] Created snapshot: {tag} (ID: {image.short_id})")

        # Cleanup old snapshots if limit is set
        if config.MAX_SNAPSHOTS_PER_VPS > 0:
            cleanup_old_snapshots(task_id, config.MAX_SNAPSHOTS_PER_VPS)

        return tag

    except Exception as e:
        logger.error(f"[Snapshot] Failed to create snapshot for VPS {task_id}: {e}")
        return None


def cleanup_old_snapshots(task_id: int, keep_count: int) -> int:
    """
    Remove old snapshots exceeding the keep limit.

    Args:
        task_id: VPS task ID.
        keep_count: Number of snapshots to keep.

    Returns:
        Number of snapshots deleted.
    """
    snapshots = list_snapshots(task_id)

    if len(snapshots) <= keep_count:
        return 0

    # Remove oldest snapshots (list is sorted newest first)
    to_delete = snapshots[keep_count:]
    deleted = 0

    try:
        client = docker.from_env(timeout=30)

        for snapshot in to_delete:
            tag = snapshot["tag"]
            try:
                logger.info(f"[Snapshot] Removing old snapshot: {tag}")
                client.images.remove(tag, force=False)
                deleted += 1
            except docker.errors.ImageNotFound:
                logger.debug(f"[Snapshot] Snapshot already removed: {tag}")
                deleted += 1
            except Exception as e:
                logger.warning(f"[Snapshot] Failed to remove snapshot {tag}: {e}")

    except Exception as e:
        logger.error(f"[Snapshot] Error during snapshot cleanup for VPS {task_id}: {e}")

    if deleted > 0:
        logger.info(
            f"[Snapshot] Cleaned up {deleted} old snapshot(s) for VPS {task_id}"
        )

    return deleted


def delete_snapshot(task_id: int, timestamp: int) -> bool:
    """
    Delete a specific snapshot.

    Args:
        task_id: VPS task ID.
        timestamp: Snapshot timestamp to delete.

    Returns:
        True if deleted successfully.
    """
    tag = snapshot_image_tag(task_id, timestamp)

    try:
        client = docker.from_env(timeout=30)
        client.images.remove(tag, force=False)
        logger.info(f"[Snapshot] Deleted snapshot: {tag}")
        return True
    except docker.errors.ImageNotFound:
        logger.warning(f"[Snapshot] Snapshot not found: {tag}")
        return False
    except Exception as e:
        logger.error(f"[Snapshot] Failed to delete snapshot {tag}: {e}")
        return False


def delete_all_snapshots(task_id: int) -> int:
    """
    Delete all snapshots for a VPS task.

    Args:
        task_id: VPS task ID.

    Returns:
        Number of snapshots deleted.
    """
    snapshots = list_snapshots(task_id)
    deleted = 0

    try:
        client = docker.from_env(timeout=30)

        for snapshot in snapshots:
            tag = snapshot["tag"]
            try:
                client.images.remove(tag, force=False)
                deleted += 1
                logger.debug(f"[Snapshot] Deleted: {tag}")
            except Exception as e:
                logger.warning(f"[Snapshot] Failed to delete {tag}: {e}")

    except Exception as e:
        logger.error(f"[Snapshot] Error deleting snapshots for VPS {task_id}: {e}")

    if deleted > 0:
        logger.info(f"[Snapshot] Deleted {deleted} snapshot(s) for VPS {task_id}")

    return deleted


# =============================================================================
# VPS Lifecycle Operations
# =============================================================================

# Alias to avoid name collision with the function parameter in stop_vps
create_snapshot_func = create_snapshot


async def stop_vps(
    task_id: int,
    task_store: TaskStateStore,
    create_snapshot: bool | None = None,
) -> bool:
    """
    Stop a running VPS.

    Args:
        task_id: VPS task ID to stop.
        task_store: Task state store.
        create_snapshot: Whether to create a snapshot before stopping.
                        If None, uses config.AUTO_SNAPSHOT_ON_STOP.

    Returns:
        True if stop was successful, False otherwise.
    """
    container_name = vps_container_name(task_id)

    # Determine if we should snapshot
    should_snapshot = (
        create_snapshot if create_snapshot is not None else config.AUTO_SNAPSHOT_ON_STOP
    )

    try:
        # Create snapshot before stopping (if enabled)
        if should_snapshot:
            logger.info(f"[VPS Stop] Creating snapshot before stopping VPS {task_id}")
            snapshot_tag = create_snapshot_func(
                task_id, message=f"Auto-snapshot on stop"
            )
            if snapshot_tag:
                logger.info(f"[VPS Stop] Created snapshot: {snapshot_tag}")
            else:
                logger.warning(
                    f"[VPS Stop] Failed to create snapshot for VPS {task_id}, "
                    "continuing with stop anyway"
                )

        # Stop the container
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "stop",
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, "docker stop", stderr)

        # Remove the container
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, "docker rm", stderr)

        # Remove from tracking
        task_store.remove_task(task_id)

        logger.info(f"Stopped VPS {task_id}")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(
            f"Failed to stop VPS {task_id}: {e.stderr.decode() if e.stderr else e}"
        )
        return False
    except Exception as e:
        logger.error(f"Failed to stop VPS {task_id}: {e}")
        return False


async def pause_vps(
    task_id: int,
    task_store: TaskStateStore,
) -> bool:
    """
    Pause a running VPS.

    Args:
        task_id: VPS task ID to pause.
        task_store: Task state store.

    Returns:
        True if pause was successful, False otherwise.
    """
    container_name = vps_container_name(task_id)

    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "pause",
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, "docker pause", stderr)
        logger.info(f"Paused VPS {task_id}")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(
            f"Failed to pause VPS {task_id}: {e.stderr.decode() if e.stderr else e}"
        )
        return False
    except Exception as e:
        logger.error(f"Failed to pause VPS {task_id}: {e}")
        return False


async def resume_vps(
    task_id: int,
    task_store: TaskStateStore,
) -> bool:
    """
    Resume a paused VPS.

    Args:
        task_id: VPS task ID to resume.
        task_store: Task state store.

    Returns:
        True if resume was successful, False otherwise.
    """
    container_name = vps_container_name(task_id)

    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "unpause",
            container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode, "docker unpause", stderr
            )
        logger.info(f"Resumed VPS {task_id}")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(
            f"Failed to resume VPS {task_id}: {e.stderr.decode() if e.stderr else e}"
        )
        return False
    except Exception as e:
        logger.error(f"Failed to resume VPS {task_id}: {e}")
        return False
