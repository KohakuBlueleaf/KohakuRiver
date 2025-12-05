"""
HakuRiver Host FastAPI Application.

This module provides the main entry point for the host server, which serves
as the central orchestration component of the HakuRiver cluster.

Responsibilities:
    - Task submission and scheduling
    - Node registration and health monitoring
    - VPS session management
    - Docker image distribution coordination
    - WebSocket terminal proxy
"""

import asyncio
import os

from fastapi import FastAPI, Path, Query, WebSocket

from kohakuriver.db.base import db, initialize_database
from kohakuriver.docker.client import DockerManager
from kohakuriver.docker.naming import ENV_PREFIX
from kohakuriver.host.background.health import collate_health_data
from kohakuriver.host.background.runner_monitor import check_dead_runners
from kohakuriver.host.config import config
from kohakuriver.host.endpoints import (
    container_filesystem,
    docker,
    filesystem,
    health,
    nodes,
    tasks,
    vps,
)
from kohakuriver.host.endpoints.docker_terminal import terminal_websocket_endpoint
from kohakuriver.host.endpoints.filesystem import watch_filesystem_proxy
from kohakuriver.host.endpoints.task_terminal import task_terminal_proxy_endpoint
from kohakuriver.host.services.tunnel_proxy import forward_port_proxy
from kohakuriver.tunnel.protocol import PROTO_TCP, PROTO_UDP
from kohakuriver.models.enums import LogLevel
from kohakuriver.ssh_proxy.server import start_server
from kohakuriver.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


# =============================================================================
# Application Setup
# =============================================================================

# Background tasks tracking
background_tasks: set[asyncio.Task] = set()

# FastAPI application instance
app = FastAPI(
    title="HakuRiver Host",
    description="Cluster management host server",
    version="0.4.0",
)

# Include API routers (all under /api prefix)
app.include_router(tasks.router, prefix="/api", tags=["Tasks"])
app.include_router(nodes.router, prefix="/api", tags=["Nodes"])
app.include_router(vps.router, prefix="/api", tags=["VPS"])
app.include_router(docker.router, prefix="/api/docker", tags=["Docker"])
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(filesystem.router, prefix="/api", tags=["Filesystem"])
app.include_router(
    container_filesystem.router, prefix="/api", tags=["Container Filesystem"]
)


# =============================================================================
# WebSocket Endpoints
# =============================================================================


@app.websocket("/ws/docker/host/containers/{container_name}/terminal")
async def websocket_terminal_endpoint(
    websocket: WebSocket,
    container_name: str = Path(...),
):
    """
    WebSocket endpoint for interactive terminal access to host containers.

    Provides direct shell access to environment containers running on the host.
    """
    await terminal_websocket_endpoint(websocket, container_name=container_name)


@app.websocket("/ws/task/{task_id}/terminal")
async def websocket_task_terminal_proxy(
    websocket: WebSocket,
    task_id: int = Path(...),
):
    """
    WebSocket proxy for task/VPS terminal access on remote runners.

    Proxies terminal requests from clients to the appropriate runner node.
    """
    await task_terminal_proxy_endpoint(websocket, task_id=task_id)


@app.websocket("/ws/fs/{task_id}/watch")
async def websocket_filesystem_watch(
    websocket: WebSocket,
    task_id: int = Path(...),
    paths: str = Query(
        "/shared,/local_temp", description="Comma-separated paths to watch"
    ),
):
    """
    WebSocket proxy for real-time filesystem change notifications.

    Proxies the connection to the runner hosting the task.
    """
    await watch_filesystem_proxy(websocket, task_id=task_id, paths=paths)


@app.websocket("/ws/forward/{task_id}/{port}")
async def websocket_forward_port(
    websocket: WebSocket,
    task_id: int = Path(..., description="Task ID of the container"),
    port: int = Path(..., description="Target port in the container"),
    proto: str = Query("tcp", description="Protocol: tcp or udp"),
):
    """
    WebSocket proxy for port forwarding to containers.

    Proxies TCP/UDP connections through the tunnel system to reach services
    running inside Docker containers without port mapping.
    """
    proto_type = PROTO_UDP if proto.lower() == "udp" else PROTO_TCP
    await forward_port_proxy(websocket, task_id, port, proto_type)


# =============================================================================
# Lifecycle Events
# =============================================================================


async def startup_event():
    """Initialize database and start background tasks on server startup."""
    logger.info("Host server starting up")
    logger.debug(f"Database file: {config.DB_FILE}")

    # Initialize database
    initialize_database(config.DB_FILE)

    # Ensure container tar directory exists
    container_tar_dir = config.get_container_dir()
    if not _ensure_container_directory(container_tar_dir):
        return

    # Clean up broken containers from failed migrations
    await _cleanup_broken_containers()

    # Initialize default container environment
    await _ensure_default_container(container_tar_dir)

    # Initialize overlay network manager if enabled
    if config.OVERLAY_ENABLED:
        await _initialize_overlay_network()

    # Start background tasks
    _start_background_tasks()


async def shutdown_event():
    """Clean up resources on server shutdown."""
    logger.info("Host server shutting down")

    # Cancel all background tasks
    for task in background_tasks:
        task.cancel()

    # Wait for tasks to complete
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)

    # Close overlay manager if active
    if hasattr(app.state, "overlay_manager") and app.state.overlay_manager:
        app.state.overlay_manager.close()
        logger.info("Overlay network manager closed")

    # Close database connection
    if not db.is_closed():
        db.close()

    logger.info("Host server shut down complete")


# Register lifecycle handlers
app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)


# =============================================================================
# Startup Helpers
# =============================================================================


def _ensure_container_directory(container_tar_dir: str) -> bool:
    """
    Ensure the container tarball directory exists.

    Args:
        container_tar_dir: Path to the container directory.

    Returns:
        True if directory exists or was created, False on failure.
    """
    if os.path.isdir(container_tar_dir):
        return True

    logger.warning(
        f"Shared directory '{container_tar_dir}' does not exist, creating..."
    )

    try:
        os.makedirs(container_tar_dir, exist_ok=True)
        logger.info(f"Created shared directory: {container_tar_dir}")
        return True
    except OSError as e:
        logger.critical(f"Cannot create shared directory '{container_tar_dir}': {e}")
        return False


def _start_background_tasks():
    """Start all background monitoring tasks."""
    tasks_to_start = [
        ("runner_monitor", check_dead_runners()),
        ("health_collator", collate_health_data()),
        ("ssh_proxy", start_server(config.HOST_BIND_IP, config.HOST_SSH_PROXY_PORT)),
    ]

    for name, coro in tasks_to_start:
        task = asyncio.create_task(coro, name=name)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    logger.debug(f"Started {len(tasks_to_start)} background tasks")


async def _initialize_overlay_network():
    """
    Initialize the VXLAN overlay network manager.

    Creates the overlay bridge and recovers state from existing VXLAN interfaces.
    """
    from kohakuriver.host.services.overlay_manager import OverlayNetworkManager

    logger.info("Initializing VXLAN overlay network...")

    try:
        overlay_manager = OverlayNetworkManager(config)
        await overlay_manager.initialize()

        # Store in app.state for access from endpoints
        app.state.overlay_manager = overlay_manager

        logger.info(
            f"Overlay network initialized: bridge={config.OVERLAY_BRIDGE_NAME}, "
            f"host_ip={config.OVERLAY_HOST_IP}/{config.OVERLAY_HOST_PREFIX}"
        )
    except Exception as e:
        logger.error(f"Failed to initialize overlay network: {e}")
        logger.warning("Overlay network disabled due to initialization failure")
        app.state.overlay_manager = None


def get_overlay_manager():
    """
    Get the overlay network manager instance.

    Returns:
        OverlayNetworkManager or None if overlay is disabled or not initialized.
    """
    if not config.OVERLAY_ENABLED:
        return None
    return getattr(app.state, "overlay_manager", None)


# =============================================================================
# Container Management Helpers
# =============================================================================


async def _cleanup_broken_containers():
    """
    Remove HakuRiver environment containers with missing images.

    Cleans up containers left in a broken state from failed migrations
    or operations where the image was deleted but the container remains.
    """
    try:
        await asyncio.to_thread(_do_cleanup_broken_containers)
    except Exception as e:
        logger.error(f"Failed to cleanup broken containers: {e}")


def _do_cleanup_broken_containers():
    """Remove broken containers (blocking implementation)."""
    docker_manager = DockerManager()
    containers = docker_manager.list_containers(all=True)

    for container in containers:
        # Only check HakuRiver environment containers
        if not container.name.startswith(f"{ENV_PREFIX}-"):
            continue

        # Check if image exists by trying to access it
        try:
            _ = container.image.id
        except Exception:
            # Image is missing - remove the broken container
            logger.warning(
                f"Found broken container '{container.name}' with missing image"
            )
            try:
                container.remove(force=True)
                logger.info(f"Removed broken container '{container.name}'")
            except Exception as e:
                logger.error(
                    f"Failed to remove broken container '{container.name}': {e}"
                )


async def _ensure_default_container(container_tar_dir: str):
    """
    Ensure the default container environment exists.

    Creates the default environment container and its tarball if they don't exist,
    enabling runners to sync the base image.
    """
    try:
        await asyncio.to_thread(_do_ensure_default_container, container_tar_dir)
    except Exception as e:
        logger.error(f"Failed to initialize default container: {e}")


def _do_ensure_default_container(container_tar_dir: str):
    """Ensure default container and tarball exist (blocking implementation)."""
    from kohakuriver.docker import utils as docker_utils

    default_env_name = config.DEFAULT_CONTAINER_NAME
    initial_base_image = config.INITIAL_BASE_IMAGE
    container_name = f"{ENV_PREFIX}-{default_env_name}"

    # Check for existing tarballs
    shared_tars = docker_utils.list_shared_container_tars(
        container_tar_dir, default_env_name
    )

    if shared_tars:
        logger.info(
            f"Found existing tarball for default environment '{default_env_name}'"
        )
        _ensure_container_from_tarball(container_name, default_env_name, shared_tars)
        return

    # No tarball exists - create from initial image
    logger.info(
        f"No tarball found for '{default_env_name}', "
        f"creating from '{initial_base_image}'"
    )
    _create_default_container(
        container_name, default_env_name, initial_base_image, container_tar_dir
    )


def _ensure_container_from_tarball(
    container_name: str,
    env_name: str,
    shared_tars: list[tuple[int, str]],
):
    """Ensure container exists, creating from tarball if needed."""
    docker_manager = DockerManager()

    # Check if container already exists (with or without prefix)
    if docker_manager.container_exists(container_name):
        return

    if docker_manager.container_exists(env_name):
        logger.info(f"Found legacy container '{env_name}' (without prefix)")
        return

    # Create container from tarball
    logger.info(f"Creating container '{container_name}' from tarball")
    latest_tar = shared_tars[0][1]
    docker_manager.load_image(latest_tar)
    docker_manager.create_container(
        image=f"kohakuriver/{env_name}:base",
        name=container_name,
    )
    logger.info(f"Container '{container_name}' created successfully")


def _create_default_container(
    container_name: str,
    env_name: str,
    base_image: str,
    container_tar_dir: str,
):
    """Create the default container and export to tarball."""
    docker_manager = DockerManager()

    # Create container from base image
    docker_manager.create_container(image=base_image, name=container_name)

    # Export to tarball for runner sync
    tarball_path = docker_manager.create_container_tarball(
        source_container=container_name,
        kohakuriver_name=env_name,
        container_tar_dir=container_tar_dir,
    )

    if tarball_path:
        logger.info(f"Default environment tarball created at {tarball_path}")
    else:
        logger.error(f"Failed to create tarball from '{base_image}'")


# =============================================================================
# Server Entry Points
# =============================================================================


def run():
    """Run the host server using uvicorn."""
    import uvicorn

    # Configure logging before starting uvicorn
    configure_logging(config.LOG_LEVEL)

    # Map log levels to uvicorn levels
    uvicorn_level_map = {
        LogLevel.FULL: "debug",
        LogLevel.DEBUG: "debug",
        LogLevel.INFO: "info",
        LogLevel.WARNING: "warning",
    }
    uvicorn_level = uvicorn_level_map.get(config.LOG_LEVEL, "info")

    logger.info(f"Starting host server on {config.HOST_BIND_IP}:{config.HOST_PORT}")

    uvicorn.run(
        app,
        host=config.HOST_BIND_IP,
        port=config.HOST_PORT,
        log_level=uvicorn_level,
        log_config=None,  # Disable uvicorn's default logging config (use loguru)
    )


def main():
    """Entry point for the host server."""
    run()


if __name__ == "__main__":
    main()
