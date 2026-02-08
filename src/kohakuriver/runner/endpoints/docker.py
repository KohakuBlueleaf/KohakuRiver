"""
Docker management endpoints.

Handles container image synchronization.

All Docker operations are wrapped in asyncio.to_thread to prevent blocking.
"""

import asyncio

from fastapi import APIRouter, HTTPException

from kohakuriver.docker import utils as docker_utils
from kohakuriver.docker.client import DockerManager
from kohakuriver.runner.config import config
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _do_list_images() -> list[dict]:
    """List images (blocking, run in executor)."""
    docker_manager = DockerManager()
    images = docker_manager.list_images()
    return [
        {
            "id": img.id,
            "tags": img.tags,
            "created": img.attrs.get("Created"),
            "size": img.attrs.get("Size"),
        }
        for img in images
    ]


@router.get("/docker/images")
async def list_images():
    """List locally available Docker images."""
    try:
        images = await asyncio.to_thread(_do_list_images)
        return {"images": images}
    except Exception as e:
        logger.error(f"Failed to list images: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list images: {e}",
        ) from e


def _do_sync_container(container_name: str, container_tar_dir: str) -> dict:
    """Sync container (blocking, run in executor)."""
    needs_sync, sync_path = docker_utils.needs_sync(container_name, container_tar_dir)

    if not needs_sync:
        return {
            "message": f"Container '{container_name}' is up-to-date.",
            "synced": False,
        }

    if not sync_path:
        raise FileNotFoundError(f"No tarball found for container '{container_name}'.")

    sync_timeout = config.DOCKER_IMAGE_SYNC_TIMEOUT
    logger.info(
        f"Syncing container '{container_name}' from {sync_path} "
        f"(timeout: {sync_timeout}s)"
    )

    success = docker_utils.sync_from_shared(
        container_name, sync_path, timeout=sync_timeout
    )

    if not success:
        raise RuntimeError(f"Failed to sync container '{container_name}'.")

    return {
        "message": f"Container '{container_name}' synced successfully.",
        "synced": True,
        "source": sync_path,
    }


@router.post("/docker/sync/{container_name}")
async def sync_container(container_name: str):
    """
    Synchronize a container image from shared storage.

    This will check if the local image needs updating and sync from
    the shared tarball if necessary.
    """
    container_tar_dir = config.get_container_tar_dir()

    try:
        result = await asyncio.to_thread(
            _do_sync_container,
            container_name,
            container_tar_dir,
        )
        return result

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error syncing container: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error syncing container: {e}",
        ) from e
