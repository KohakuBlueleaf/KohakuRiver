"""
Docker management endpoints.

Handles:
- Host Docker container management (list, create, start, stop, delete)
- HakuRiver container tarball management (list, create, download, delete)

All Docker operations are wrapped in asyncio.to_thread to prevent blocking.
"""

import asyncio
import os
import re
from collections import defaultdict
from typing import Annotated

import docker
import psutil
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from kohakuriver.db.auth import User
from kohakuriver.docker.client import DockerManager
from kohakuriver.docker.naming import ENV_PREFIX
from kohakuriver.host.auth.dependencies import require_operator
from kohakuriver.host.config import config
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class CreateContainerRequest(BaseModel):
    """Request body for creating a container."""

    image_name: str
    container_name: str


# =============================================================================
# Host Docker Container Management (/docker/host/*)
# =============================================================================


def _is_env_container(name: str) -> bool:
    """Check if container is a HakuRiver environment container."""
    return name.startswith(f"{ENV_PREFIX}-")


def _get_env_name(container_name: str) -> str:
    """Extract environment name from container name (strip prefix)."""
    if container_name.startswith(f"{ENV_PREFIX}-"):
        return container_name[len(ENV_PREFIX) + 1 :]
    return container_name


def _make_env_container_name(env_name: str) -> str:
    """Create full container name from environment name."""
    # If already prefixed, return as-is
    if env_name.startswith(f"{ENV_PREFIX}-"):
        return env_name
    return f"{ENV_PREFIX}-{env_name}"


def _resolve_container_name(docker_manager: DockerManager, env_name: str) -> str | None:
    """Resolve environment name to actual container name.

    Checks for prefixed name first, then falls back to unprefixed for backward
    compatibility with old containers.

    Returns the actual container name if found, None otherwise.
    """
    # Try prefixed name first
    prefixed_name = _make_env_container_name(env_name)
    if docker_manager.container_exists(prefixed_name):
        return prefixed_name

    # Fallback: try the name as-is (backward compatibility)
    if docker_manager.container_exists(env_name):
        return env_name

    return None


def _do_list_host_containers() -> list[dict]:
    """List containers (blocking, run in executor)."""
    docker_manager = DockerManager()
    containers = docker_manager.list_containers(all=True)

    result = []
    for container in containers:
        # Only include HakuRiver environment containers
        if not _is_env_container(container.name):
            continue

        # Get image tag safely - handle missing/deleted images
        try:
            image = container.image
            image_tags = image.tags if image and image.tags else []
            image_name = (
                image_tags[0]
                if image_tags
                else (image.short_id if image else "<missing>")
            )
        except Exception:
            # Image may have been deleted
            image_name = "<missing>"

        result.append(
            {
                "id": container.short_id,
                "name": container.name,
                "env_name": _get_env_name(container.name),
                "image": image_name,
                "status": container.status,
                "created": container.attrs.get("Created"),
            }
        )

    return result


@router.get("/host/containers")
async def list_host_containers(
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    List HakuRiver environment containers on the Host.

    Returns only containers with the kohakuriver-env- prefix.
    These are containers created for environment setup.

    Requires 'operator' role or higher.
    """
    try:
        result = await asyncio.to_thread(_do_list_host_containers)
        return result

    except Exception as e:
        logger.error(f"Error listing containers: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing containers: {e}")


def _get_resource_limits() -> dict:
    """Calculate resource limits for env containers.

    Returns kwargs dict with nano_cpus and mem_limit based on config percentages.
    """
    limits = {}

    # CPU limit: nano_cpus = cores * 1e9
    # e.g., 0.25 of 8 cores = 2 cores = 2e9 nano_cpus
    cpu_count = os.cpu_count() or 1
    cpu_limit = config.ENV_CONTAINER_CPU_LIMIT
    if 0 < cpu_limit < 1:
        nano_cpus = int(cpu_count * cpu_limit * 1e9)
        limits["nano_cpus"] = nano_cpus

    # Memory limit in bytes
    mem_limit = config.ENV_CONTAINER_MEM_LIMIT
    if 0 < mem_limit < 1:
        total_mem = psutil.virtual_memory().total
        mem_bytes = int(total_mem * mem_limit)
        limits["mem_limit"] = mem_bytes

    return limits


def _do_create_host_container(image_name: str, container_name: str) -> dict:
    """Create container (blocking, run in executor)."""
    docker_manager = DockerManager()

    # Check if container already exists
    if docker_manager.container_exists(container_name):
        raise ValueError(f"Container '{container_name}' already exists.")

    # Get resource limits
    resource_limits = _get_resource_limits()

    # Create container (runs with sleep infinity)
    container = docker_manager.create_container(
        image=image_name,
        name=container_name,
        command="sleep infinity",
        **resource_limits,
    )

    return {
        "container_id": container.short_id,
        "container_name": container_name,
        "status": container.status,
        "resource_limits": {
            "cpu_limit": config.ENV_CONTAINER_CPU_LIMIT,
            "mem_limit": config.ENV_CONTAINER_MEM_LIMIT,
        },
    }


@router.post("/host/create")
async def create_host_container(
    request: CreateContainerRequest,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Create a persistent Docker container on the Host for environment setup.

    The container name will be prefixed with 'kohakuriver-env-' to identify it
    as a HakuRiver environment container.

    Requires 'operator' role or higher.
    """
    # Apply prefix to container name
    container_name = _make_env_container_name(request.container_name)

    logger.info(
        f"Creating environment container '{container_name}' from image '{request.image_name}'"
    )

    try:
        result = await asyncio.to_thread(
            _do_create_host_container,
            request.image_name,
            container_name,
        )

        return {
            "message": f"Environment '{request.container_name}' created successfully.",
            "container_id": result["container_id"],
            "container_name": result["container_name"],
            "env_name": request.container_name,
            "status": result["status"],
        }

    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating container: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating container: {e}")


def _do_delete_host_container(env_name: str) -> str:
    """Delete container (blocking, run in executor). Returns actual container name."""
    docker_manager = DockerManager()

    actual_name = _resolve_container_name(docker_manager, env_name)
    if not actual_name:
        raise FileNotFoundError(f"Environment '{env_name}' not found.")

    success = docker_manager.remove_container(actual_name, force=True)
    if not success:
        raise RuntimeError(f"Failed to delete environment '{env_name}'.")

    return actual_name


@router.post("/host/delete/{env_name}")
async def delete_host_container(
    env_name: str,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Delete a Docker environment container on the Host.

    Requires 'operator' role or higher.
    """
    try:
        actual_name = await asyncio.to_thread(_do_delete_host_container, env_name)
        logger.info(f"Deleted environment container '{actual_name}'")
        return {"message": f"Environment '{env_name}' deleted successfully."}

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting container: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting container: {e}")


def _do_stop_host_container(env_name: str) -> str:
    """Stop container (blocking, run in executor). Returns actual container name."""
    docker_manager = DockerManager()

    actual_name = _resolve_container_name(docker_manager, env_name)
    if not actual_name:
        raise FileNotFoundError(f"Environment '{env_name}' not found.")

    success = docker_manager.stop_container(actual_name)
    if not success:
        raise RuntimeError(f"Failed to stop environment '{env_name}'.")

    return actual_name


@router.post("/host/stop/{env_name}")
async def stop_host_container(
    env_name: str,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Stop a running Docker environment container on the Host.

    Requires 'operator' role or higher.
    """
    try:
        actual_name = await asyncio.to_thread(_do_stop_host_container, env_name)
        logger.info(f"Stopped environment container '{actual_name}'")
        return {"message": f"Environment '{env_name}' stopped successfully."}

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error stopping container: {e}")
        raise HTTPException(status_code=500, detail=f"Error stopping container: {e}")


def _do_start_host_container(env_name: str) -> str:
    """Start container (blocking, run in executor). Returns actual container name."""
    docker_manager = DockerManager()

    actual_name = _resolve_container_name(docker_manager, env_name)
    if not actual_name:
        raise FileNotFoundError(f"Environment '{env_name}' not found.")

    success = docker_manager.start_container(actual_name)
    if not success:
        raise RuntimeError(f"Failed to start environment '{env_name}'.")

    return actual_name


@router.post("/host/start/{env_name}")
async def start_host_container(
    env_name: str,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Start a stopped Docker environment container on the Host.

    Requires 'operator' role or higher.
    """
    try:
        actual_name = await asyncio.to_thread(_do_start_host_container, env_name)
        logger.info(f"Started environment container '{actual_name}'")
        return {"message": f"Environment '{env_name}' started successfully."}

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting container: {e}")
        raise HTTPException(status_code=500, detail=f"Error starting container: {e}")


# =============================================================================
# HakuRiver Container Tarball Management (/docker/*)
# =============================================================================


@router.get("/list")
async def list_tarballs(
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    List available HakuRiver container tarballs in the shared directory.

    Requires 'operator' role or higher.

    Returns:
        Object with container names as keys, each containing:
        - latest_timestamp: Unix timestamp of latest version
        - latest_tarball: Filename of latest tarball
        - all_versions: List of all versions sorted by timestamp (newest first)
    """
    container_dir = config.get_container_dir()

    if not os.path.isdir(container_dir):
        return {}

    # Group tarballs by container name
    # Tarball naming pattern: {container_name}-{timestamp}.tar (dash separator, not underscore)
    # Example: python-1732570234.tar -> container_name="python", timestamp=1732570234
    containers: dict[str, list[dict]] = defaultdict(list)

    for filename in os.listdir(container_dir):
        if not filename.endswith(".tar"):
            continue

        filepath = os.path.join(container_dir, filename)
        stat = os.stat(filepath)

        # Parse timestamp from filename: {name}-{timestamp}.tar
        # The timestamp is always a 10-digit unix timestamp at the end before .tar
        match = re.match(r"^(.+)-(\d{10,})\.tar$", filename)
        if match:
            container_name = match.group(1)
            timestamp = int(match.group(2))
        else:
            # No valid timestamp pattern, skip this file
            continue

        containers[container_name].append(
            {
                "timestamp": timestamp,
                "tarball": filename,
                "size_bytes": stat.st_size,
            }
        )

    # Build result object with latest_timestamp, latest_tarball, all_versions
    result = {}
    for name, versions in containers.items():
        # Sort by timestamp descending (newest first)
        versions.sort(key=lambda x: x["timestamp"], reverse=True)
        result[name] = {
            "latest_timestamp": versions[0]["timestamp"],
            "latest_tarball": versions[0]["tarball"],
            "all_versions": versions,
        }

    return result


def _do_create_tarball(env_name: str, container_dir: str) -> tuple[str, str]:
    """Create tarball (blocking, run in executor). Returns (actual_name, tarball_path)."""
    docker_manager = DockerManager()

    actual_name = _resolve_container_name(docker_manager, env_name)
    if not actual_name:
        raise FileNotFoundError(f"Environment '{env_name}' not found.")

    # Create tarball using the env_name (without prefix) for the tarball name
    tarball_path = docker_manager.create_container_tarball(
        source_container=actual_name,
        kohakuriver_name=env_name,
        container_tar_dir=container_dir,
    )

    if not tarball_path:
        raise RuntimeError("Failed to create container tarball.")

    return actual_name, tarball_path


@router.post("/create_tar/{env_name}")
async def create_tarball(
    env_name: str,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Create a HakuRiver container tarball from a Host environment container.

    Requires 'operator' role or higher.
    """
    try:
        logger.info(f"Creating tarball from environment '{env_name}'")

        actual_name, tarball_path = await asyncio.to_thread(
            _do_create_tarball,
            env_name,
            config.get_container_dir(),
        )

        logger.info(f"Container tarball created at {tarball_path}")

        return {
            "message": f"Tarball created from environment '{env_name}'.",
            "tarball_path": tarball_path,
            "env_name": env_name,
        }

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating tarball: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating tarball: {e}")


def _do_find_tarball(name: str, container_dir: str) -> str | None:
    """Find tarball path (blocking, run in executor)."""
    # Try exact match first
    tarball_path = os.path.join(container_dir, f"{name}.tar")
    if os.path.exists(tarball_path):
        return tarball_path

    # Try to find tarball with timestamp pattern
    docker_manager = DockerManager()
    tarballs = docker_manager.list_shared_tarballs(container_dir, name)
    if tarballs:
        return tarballs[0][1]  # Latest tarball

    return None


@router.get("/container/{name}")
async def download_container(
    name: str,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Download a container tarball.

    Requires 'operator' role or higher.
    """
    container_dir = config.get_container_dir()

    tarball_path = await asyncio.to_thread(_do_find_tarball, name, container_dir)

    if not tarball_path or not os.path.exists(tarball_path):
        raise HTTPException(
            status_code=404,
            detail=f"Container '{name}' not found.",
        )

    return FileResponse(
        path=tarball_path,
        filename=os.path.basename(tarball_path),
        media_type="application/x-tar",
    )


def _do_delete_tarball(name: str, container_dir: str) -> list[str]:
    """Delete tarballs (blocking, run in executor). Returns list of deleted paths."""
    docker_manager = DockerManager()
    tarballs = docker_manager.list_shared_tarballs(container_dir, name)

    # Also check for exact match
    exact_path = os.path.join(container_dir, f"{name}.tar")
    if os.path.exists(exact_path):
        tarballs.append((0, exact_path))

    if not tarballs:
        raise FileNotFoundError(f"Container '{name}' not found.")

    deleted = []
    for _, tarball_path in tarballs:
        os.remove(tarball_path)
        deleted.append(tarball_path)

    return deleted


@router.delete("/container/{name}")
async def delete_tarball(
    name: str,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Delete a container tarball.

    Requires 'operator' role or higher.
    """
    container_dir = config.get_container_dir()

    try:
        deleted = await asyncio.to_thread(_do_delete_tarball, name, container_dir)
        for path in deleted:
            logger.info(f"Deleted container tarball: {path}")

        return {"message": f"Container '{name}' deleted."}

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting container: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting container: {e}",
        )


# =============================================================================
# Migration Endpoint
# =============================================================================


def _do_migrate_container(old_name: str, new_name: str) -> dict:
    """Perform container migration (blocking, run in executor).

    Args:
        old_name: Original container name
        new_name: New container name with kohakuriver-env- prefix

    Returns:
        Result dict with migration info
    """
    # No timeout - large containers can take a very long time
    client = docker.from_env(timeout=None)

    logger.info(f"Migrating container '{old_name}' to '{new_name}' (no timeout)")

    # Stop old container
    logger.info(f"Stopping container '{old_name}'...")
    container = client.containers.get(old_name)
    container.stop(timeout=60)

    # Commit to a permanent image (kohakuriver/{env_name}:base)
    # This is the same naming convention used for tarballs
    logger.info(f"Committing container '{old_name}' to image...")
    image_repo = f"kohakuriver/{old_name}"
    image_tag = "base"
    full_image_tag = f"{image_repo}:{image_tag}"
    container.commit(repository=image_repo, tag=image_tag)

    # Create new container from the committed image
    logger.info(f"Creating new container '{new_name}'...")
    client.containers.create(
        image=full_image_tag,
        name=new_name,
        command="sleep infinity",
        detach=True,
    )

    # Remove old container
    logger.info(f"Removing old container '{old_name}'...")
    container.remove(force=True)

    # Note: We keep the image (kohakuriver/{name}:base) as it's needed by the container
    # and follows our standard naming convention for KohakuRiver images

    logger.info(f"Successfully migrated '{old_name}' to '{new_name}'")

    return {
        "message": f"Container migrated from '{old_name}' to '{new_name}'.",
        "old_name": old_name,
        "new_name": new_name,
        "env_name": old_name,
        "image": full_image_tag,
    }


def _check_migrate_preconditions(old_name: str, new_name: str) -> None:
    """Check migration preconditions (blocking, run in executor)."""
    docker_manager = DockerManager()

    # Check if old container exists
    if not docker_manager.container_exists(old_name):
        raise FileNotFoundError(f"Container '{old_name}' not found.")

    # Check if new name already exists
    if docker_manager.container_exists(new_name):
        raise ValueError(f"Container '{new_name}' already exists. Cannot migrate.")


@router.post("/host/migrate/{old_name}")
async def migrate_container(
    old_name: str,
    current_user: Annotated[User, Depends(require_operator)],
):
    """
    Migrate a legacy container to the new kohakuriver-env- naming convention.

    Renames container from '{old_name}' to 'kohakuriver-env-{old_name}'.
    This allows users to migrate existing environment containers to the new format.

    Note: This operation can take several minutes for large containers (10-50GB).

    Requires 'operator' role or higher.
    """
    try:
        # Check if already using new naming (no Docker call needed)
        if old_name.startswith(f"{ENV_PREFIX}-"):
            raise HTTPException(
                status_code=400,
                detail=f"Container '{old_name}' already uses the new naming convention.",
            )

        new_name = _make_env_container_name(old_name)

        # Check preconditions in executor
        await asyncio.to_thread(_check_migrate_preconditions, old_name, new_name)

        # Run migration in executor (no timeout - can take very long for large containers)
        result = await asyncio.to_thread(
            _do_migrate_container,
            old_name,
            new_name,
        )

        return result

    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Error migrating container: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error migrating container: {e}",
        )
