"""
HakuRiver Runner FastAPI Application.

Main entry point for the runner server.
"""

import asyncio
import os
import socket

import docker as docker_lib
import httpx
import psutil
from fastapi import FastAPI, Path, Query, WebSocket

from kohakuriver.docker.client import DockerManager
from kohakuriver.runner.background.heartbeat import send_heartbeat
from kohakuriver.runner.background.startup_check import startup_check
from kohakuriver.runner.config import config
from kohakuriver.runner.endpoints import docker as docker_endpoints
from kohakuriver.runner.endpoints import filesystem, tasks, terminal, vps
from kohakuriver.runner.services.tunnel_server import (
    handle_container_tunnel,
    handle_port_forward,
)
from kohakuriver.tunnel.protocol import PROTO_TCP, PROTO_UDP
from kohakuriver.runner.numa.detector import detect_numa_topology
from kohakuriver.runner.services.resource_monitor import get_gpu_stats, get_total_cores
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

# Background tasks set
background_tasks: set[asyncio.Task] = set()

# Global state
numa_topology: dict | None = None
task_store: TaskStateStore | None = None

# FastAPI app
app = FastAPI(
    title="HakuRiver Runner",
    description="Cluster runner node",
    version="0.2.0",
)

# Include routers (all under /api prefix)
app.include_router(tasks.router, prefix="/api", tags=["Tasks"])
app.include_router(vps.router, prefix="/api", tags=["VPS"])
app.include_router(docker_endpoints.router, prefix="/api", tags=["Docker"])
app.include_router(filesystem.router, prefix="/api", tags=["Filesystem"])


# WebSocket endpoint for task/VPS terminal access
@app.websocket("/ws/task/{task_id}/terminal")
async def websocket_task_terminal(websocket: WebSocket, task_id: int = Path(...)):
    """WebSocket endpoint for interactive terminal access to task/VPS containers."""
    await terminal.task_terminal_websocket_endpoint(websocket, task_id=task_id)


# WebSocket endpoint for filesystem watching
@app.websocket("/ws/fs/{task_id}/watch")
async def websocket_filesystem_watch(
    websocket: WebSocket,
    task_id: int = Path(...),
    paths: str = Query(
        "/shared,/local_temp", description="Comma-separated paths to watch"
    ),
):
    """WebSocket endpoint for real-time filesystem change notifications."""
    await filesystem.watch_filesystem_handler(websocket, task_id=task_id, paths=paths)


# WebSocket endpoint for container tunnel connections (tunnel-client connects here)
@app.websocket("/ws/tunnel/{container_id}")
async def websocket_container_tunnel(
    websocket: WebSocket,
    container_id: str = Path(..., description="Container ID or name"),
):
    """WebSocket endpoint for container tunnel-client connections."""
    await handle_container_tunnel(websocket, container_id)


# WebSocket endpoint for port forwarding (user requests forwarded to container)
@app.websocket("/ws/forward/{container_id}/{port}")
async def websocket_port_forward(
    websocket: WebSocket,
    container_id: str = Path(..., description="Container ID or name"),
    port: int = Path(..., description="Target port in container"),
    proto: str = Query("tcp", description="Protocol: tcp or udp"),
):
    """WebSocket endpoint for port forwarding to containers."""
    logger.info(
        f"[Runner] Port forward WebSocket request: container={container_id}, port={port}, proto={proto}"
    )
    proto_type = PROTO_UDP if proto.lower() == "udp" else PROTO_TCP
    await handle_port_forward(websocket, container_id, port, proto_type)


def get_hostname() -> str:
    """Get the runner's hostname."""
    return socket.gethostname()


def get_runner_url() -> str:
    """Get the runner's URL for registration."""
    ip = config.RUNNER_BIND_IP
    if ip == "0.0.0.0":
        # Try to get actual IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((config.HOST_ADDRESS, config.HOST_PORT))
            ip = s.getsockname()[0]
            s.close()
        except Exception:
            ip = "127.0.0.1"
    return f"http://{ip}:{config.RUNNER_PORT}"


async def register_with_host() -> tuple[bool, dict | None]:
    """
    Register this runner with the host.

    Returns:
        Tuple of (success, overlay_info). overlay_info is the overlay network
        configuration from Host if overlay is enabled, otherwise None.
    """
    global numa_topology

    # Detect NUMA topology if not done
    if numa_topology is None:
        numa_topology = detect_numa_topology()

    hostname = get_hostname()
    runner_url = get_runner_url()
    total_cores = get_total_cores()
    total_ram = psutil.virtual_memory().total
    gpu_info = get_gpu_stats()

    register_data = {
        "hostname": hostname,
        "url": runner_url,
        "total_cores": total_cores,
        "total_ram_bytes": total_ram,
        "numa_topology": numa_topology,
        "gpu_info": gpu_info,
    }

    host_url = f"http://{config.HOST_ADDRESS}:{config.HOST_PORT}"

    logger.info(
        f"Registering with host {host_url} as {hostname} "
        f"({total_cores} cores, NUMA: {'Yes' if numa_topology else 'No'}) "
        f"at {runner_url}"
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{host_url}/api/register",
                json=register_data,
                timeout=15.0,
            )
            response.raise_for_status()

        data = response.json()
        overlay_info = data.get("overlay")

        if overlay_info:
            logger.info(
                f"Successfully registered with host. "
                f"Overlay: runner_id={overlay_info.get('runner_id')}, "
                f"subnet={overlay_info.get('overlay_subnet')}"
            )
        else:
            logger.info("Successfully registered with host (no overlay).")

        return True, overlay_info

    except httpx.RequestError as e:
        logger.error(f"Failed to register with host: {e}")
        return False, None
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Host rejected registration: {e.response.status_code} - "
            f"{e.response.text}"
        )
        return False, None
    except Exception as e:
        logger.exception(f"Unexpected error during registration: {e}")
        return False, None


async def startup_event():
    """Initialize runner and start background tasks."""
    global numa_topology, task_store

    hostname = get_hostname()
    logger.info(
        f"Runner starting on {hostname} "
        f"({config.RUNNER_BIND_IP}:{config.RUNNER_PORT})"
    )

    # Check Docker access and ensure network exists (in executor to avoid blocking)
    logger.info("Checking Docker access...")
    try:

        def _check_docker_and_network():
            dm = DockerManager()
            dm.client.ping()

            # Ensure kohakuriver-net network exists
            network_name = config.DOCKER_NETWORK_NAME
            try:
                dm.client.networks.get(network_name)
                logger.info(f"Docker network '{network_name}' already exists.")
            except docker_lib.errors.NotFound:
                logger.info(f"Creating Docker network '{network_name}'...")
                dm.client.networks.create(
                    network_name,
                    driver="bridge",
                    ipam=docker_lib.types.IPAMConfig(
                        pool_configs=[
                            docker_lib.types.IPAMPool(
                                subnet=config.DOCKER_NETWORK_SUBNET,
                                gateway=config.DOCKER_NETWORK_GATEWAY,
                            )
                        ]
                    ),
                )
                logger.info(
                    f"Created Docker network '{network_name}' "
                    f"(subnet={config.DOCKER_NETWORK_SUBNET}, gateway={config.DOCKER_NETWORK_GATEWAY})"
                )

        await asyncio.to_thread(_check_docker_and_network)
        logger.info("Docker daemon accessible.")
    except Exception as e:
        logger.warning(f"Docker check failed: {e}. Docker tasks may fail.")

    # Check directories
    if not os.path.isdir(config.SHARED_DIR):
        logger.error(
            f"Shared directory '{config.SHARED_DIR}' not found. "
            "Runner may not function correctly."
        )
    else:
        # Ensure shared_data subdirectory exists (mounted as /shared inside containers)
        shared_data_dir = os.path.join(config.SHARED_DIR, "shared_data")
        if not os.path.isdir(shared_data_dir):
            os.makedirs(shared_data_dir, exist_ok=True)
            logger.info(f"Created shared data directory: {shared_data_dir}")

    # Create local temp directory
    if not os.path.isdir(config.LOCAL_TEMP_DIR):
        os.makedirs(config.LOCAL_TEMP_DIR, exist_ok=True)

    # Initialize task store
    db_path = config.get_state_db_path()
    task_store = TaskStateStore(db_path)

    # Set dependencies on endpoint modules
    tasks.set_dependencies(task_store, numa_topology)
    vps.set_dependencies(task_store)
    terminal.set_dependencies(task_store)
    filesystem.set_dependencies(task_store)

    # Detect NUMA topology
    logger.info("Detecting NUMA topology...")
    numa_topology = detect_numa_topology()
    tasks.set_dependencies(task_store, numa_topology)

    # Register with host
    registered = False
    overlay_info = None
    for attempt in range(5):
        registered, overlay_info = await register_with_host()
        if registered:
            break
        wait_time = 5 * (attempt + 1)
        logger.info(
            f"Registration attempt {attempt + 1}/5 failed. "
            f"Retrying in {wait_time} seconds..."
        )
        await asyncio.sleep(wait_time)

    if not registered:
        logger.error(
            "Failed to register with host after multiple attempts. "
            "Runner may not function correctly."
        )
    else:
        # Set up overlay network if configured
        if overlay_info and config.OVERLAY_ENABLED:
            await _setup_overlay_network(overlay_info)

        # Apply ACS override if configured (splits IOMMU groups for individual GPU allocation)
        if config.VM_ACS_OVERRIDE:
            await _apply_acs_override()

        # Initialize VM network manager (after overlay setup)
        await _setup_vm_network()

        # Run startup check
        logger.info("Running startup check...")
        await startup_check(task_store)

        # Start heartbeat (with modified callback that ignores overlay_info return)
        logger.info("Starting heartbeat background task.")

        async def register_callback():
            success, _ = await register_with_host()
            return success

        heartbeat_task = asyncio.create_task(
            send_heartbeat(
                hostname=hostname,
                numa_topology=numa_topology,
                task_store=task_store,
                register_callback=register_callback,
            )
        )
        background_tasks.add(heartbeat_task)
        heartbeat_task.add_done_callback(background_tasks.discard)


async def _apply_acs_override() -> None:
    """Apply ACS override to split IOMMU groups for individual GPU allocation."""
    try:
        from kohakuriver.qemu.capability import apply_acs_override

        def _apply():
            return apply_acs_override()

        results = await asyncio.to_thread(_apply)
        total = results["root_ports"] + results["plx_switches"] + results["pci_bridges"]
        if total > 0:
            logger.info(
                f"ACS override applied: {results['root_ports']} root ports, "
                f"{results['plx_switches']} PLX switches, "
                f"{results['pci_bridges']} PCI bridges"
            )
        else:
            logger.debug("ACS override: no PCI bridges/switches found to modify")
        if results["errors"]:
            for err in results["errors"]:
                logger.warning(f"ACS override warning: {err}")
    except Exception as e:
        logger.warning(f"ACS override failed: {e}")


async def _setup_vm_network() -> None:
    """Initialize VM network manager for QEMU VMs."""
    try:
        from kohakuriver.runner.services.vm_network_manager import (
            get_vm_network_manager,
        )

        net_manager = get_vm_network_manager()
        await net_manager.setup()
        logger.info("VM network manager initialized")
    except Exception as e:
        logger.debug(f"VM network manager setup skipped: {e}")


async def _setup_overlay_network(overlay_info: dict) -> None:
    """
    Set up the VXLAN overlay network on this runner.

    Args:
        overlay_info: Overlay configuration from Host registration response
    """
    from kohakuriver.runner.services.overlay_manager import (
        OverlayConfig,
        RunnerOverlayManager,
    )

    logger.info("Setting up VXLAN overlay network...")

    # Get runner's physical IP (same logic as get_runner_url)
    runner_ip = config.RUNNER_BIND_IP
    if runner_ip == "0.0.0.0":
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((config.HOST_ADDRESS, config.HOST_PORT))
            runner_ip = s.getsockname()[0]
            s.close()
        except Exception:
            runner_ip = "127.0.0.1"

    try:
        overlay_config = OverlayConfig(
            runner_id=overlay_info["runner_id"],
            subnet=overlay_info["overlay_subnet"],
            gateway=overlay_info["overlay_gateway"],
            host_overlay_ip=overlay_info["host_overlay_ip"],
            host_physical_ip=overlay_info["host_physical_ip"],
            runner_physical_ip=runner_ip,
            overlay_network_cidr=overlay_info.get(
                "overlay_network_cidr", "10.128.0.0/12"
            ),
            host_ip_on_runner_subnet=overlay_info.get(
                "host_ip_on_runner_subnet",
                "",  # Will be calculated from runner_id if not provided
            ),
        )

        overlay_manager = RunnerOverlayManager(
            base_vxlan_id=config.OVERLAY_VXLAN_ID,
            vxlan_port=config.OVERLAY_VXLAN_PORT,
            mtu=config.OVERLAY_MTU,
        )

        await overlay_manager.setup(overlay_config)

        # Store manager in app.state
        app.state.overlay_manager = overlay_manager

        # Mark overlay as configured in config so containers use overlay network
        config.set_overlay_configured(overlay_config.gateway)

        logger.info(
            f"Overlay network setup complete: "
            f"subnet={overlay_config.subnet}, gateway={overlay_config.gateway}"
        )

    except Exception as e:
        logger.error(f"Failed to set up overlay network: {e}")
        logger.warning("Containers will use default kohakuriver-net network")


async def shutdown_event():
    """Clean shutdown."""
    logger.info("Runner shutting down.")

    # Cancel background tasks
    for task in background_tasks:
        task.cancel()

    # Close overlay manager if active
    if hasattr(app.state, "overlay_manager") and app.state.overlay_manager:
        app.state.overlay_manager.close()
        logger.info("Overlay network manager closed")

    # Don't stop containers on shutdown - VPS containers have --restart unless-stopped
    # and should persist. Task containers will be cleaned up on next startup.
    if task_store:
        tracked_tasks = task_store.list_tasks()
        if tracked_tasks:
            logger.info(
                f"Leaving {len(tracked_tasks)} containers running. "
                "They will be recovered or cleaned up on next startup."
            )


app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)


def run():
    """Run the runner server using uvicorn."""
    import uvicorn

    from kohakuriver.models.enums import LogLevel

    log_level = config.LOG_LEVEL

    # Configure HakuRiver logging (IMPORTANT: must be called before uvicorn.run)
    configure_logging(log_level)

    match log_level:
        case LogLevel.FULL:
            uvicorn_level = "debug"
        case LogLevel.DEBUG:
            uvicorn_level = "debug"
        case LogLevel.INFO:
            uvicorn_level = "info"
        case LogLevel.WARNING:
            uvicorn_level = "warning"

    uvicorn.run(
        app,
        host=config.RUNNER_BIND_IP,
        port=config.RUNNER_PORT,
        log_level=uvicorn_level,
    )


def main():
    """Entry point for KohakuEngine."""
    run()


if __name__ == "__main__":
    main()
