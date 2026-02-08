"""
VPS creation service.

Handles Docker-based VPS container creation, including image provisioning,
SSH setup, and Docker command construction.
"""

import asyncio
import datetime
import subprocess

from kohakuriver.docker.naming import (
    image_tag,
    vps_container_name,
)
from kohakuriver.models.requests import TaskStatusUpdate
from kohakuriver.runner.config import config
from kohakuriver.runner.services.task_executor import (
    docker_pull,
    ensure_docker_image_synced,
    report_status_to_host,
)
from kohakuriver.runner.services.tunnel_helper import (
    get_tunnel_env_vars,
    get_tunnel_mount,
    wrap_command_with_tunnel,
)
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import format_traceback, get_logger

logger = get_logger(__name__)


def _detect_package_manager(image_name: str) -> str:
    """Detect package manager from Docker image name."""
    image_lower = image_name.lower()
    pkg_map = [
        (["alpine"], "apk"),
        (["ubuntu", "debian"], "apt"),
        (["fedora"], "dnf"),
        (["centos", "rhel", "redhat", "rocky", "alma"], "yum"),
        (["opensuse", "suse"], "zypper"),
        (["arch"], "pacman"),
    ]
    for keywords, manager in pkg_map:
        if any(kw in image_lower for kw in keywords):
            return manager
    return "apt"


def _get_ssh_install_cmd(pkg_manager: str) -> str:
    """Get the SSH installation command for a package manager."""
    match pkg_manager:
        case "apk":
            return "apk update && apk add --no-cache openssh"
        case "apt":
            return "apt update && apt install -y openssh-server"
        case "dnf":
            return "dnf install -y openssh-server"
        case "yum":
            return "yum install -y openssh-server"
        case "zypper":
            return "zypper refresh && zypper install -y openssh"
        case "pacman":
            return "pacman -Syu --noconfirm openssh"
        case _:
            return "apt update && apt install -y openssh-server"


def _build_vps_docker_command(
    docker_image_tag: str,
    task_id: int,
    ssh_key_mode: str,
    ssh_public_key: str | None,
    mount_dirs: list[str],
    working_dir: str,
    cpu_cores: int,
    memory_limit_bytes: int | None,
    gpu_ids: list[int],
    privileged: bool,
    reserved_ip: str | None = None,
) -> list[str]:
    """
    Build docker run command for VPS container.

    Args:
        docker_image_tag: Docker image tag to use.
        task_id: Task ID for the VPS.
        ssh_key_mode: SSH key mode ("none", "upload", or "generate").
        ssh_public_key: SSH public key (None for "none" mode).
        mount_dirs: List of mount directories.
        working_dir: Working directory in container.
        cpu_cores: Number of CPU cores.
        memory_limit_bytes: Memory limit in bytes.
        gpu_ids: List of GPU indices.
        privileged: Run with --privileged.
        reserved_ip: Pre-reserved IP address for the container (optional).

    Returns:
        Docker command as list of strings.
    """
    docker_cmd = ["docker", "run", "--restart", "unless-stopped", "-d"]

    # Container name
    docker_cmd.extend(["--name", vps_container_name(task_id)])

    # Use overlay network if configured, otherwise kohakuriver-net bridge
    # Containers on same node can communicate via container name
    # With overlay, containers across nodes can communicate via overlay IPs
    container_network = config.get_container_network()
    docker_cmd.extend(["--network", container_network])

    # Assign specific IP if reserved
    if reserved_ip:
        docker_cmd.extend(["--ip", reserved_ip])
        logger.info(f"[VPS {task_id}] Using reserved IP: {reserved_ip}")

    # SSH port mapping - only if SSH is enabled
    if ssh_key_mode != "disabled":
        docker_cmd.extend(["-p", "0:22"])

    # Privileged mode or CAP_SYS_NICE
    if privileged:
        docker_cmd.append("--privileged")
        logger.warning(f"VPS {task_id}: Running with --privileged flag!")
    else:
        docker_cmd.extend(["--cap-add", "SYS_NICE"])

    # Mount directories
    for mount_spec in mount_dirs:
        parts = mount_spec.split(":")
        if len(parts) < 2:
            logger.warning(f"Invalid mount format: '{mount_spec}'. Skipping.")
            continue
        host_path, container_path, *options = parts
        option_str = ("," + ",".join(options)) if options else ""
        docker_cmd.extend(
            [
                "--mount",
                f"type=bind,source={host_path},target={container_path}{option_str}",
            ]
        )

    # Working directory
    if working_dir:
        docker_cmd.extend(["--workdir", working_dir])

    # CPU cores
    if cpu_cores > 0:
        docker_cmd.extend(["--cpus", str(cpu_cores)])

    # Memory limit
    if memory_limit_bytes:
        docker_cmd.extend(["--memory", str(memory_limit_bytes)])

    # GPU allocation
    if gpu_ids:
        id_string = ",".join(map(str, gpu_ids))
        docker_cmd.extend(["--gpus", f'"device={id_string}"'])

    # Add tunnel environment variables if tunnel is enabled
    container_name = vps_container_name(task_id)
    tunnel_env = get_tunnel_env_vars(container_name)
    for key, value in tunnel_env.items():
        docker_cmd.extend(["-e", f"{key}={value}"])

    # Build setup command based on SSH key mode
    match ssh_key_mode:
        case "disabled":
            # No SSH at all - just run a shell that stays alive (TTY-only mode)
            # Use tail -f /dev/null to keep container running, users connect via docker exec
            setup_cmd = "tail -f /dev/null"
            logger.info(f"VPS {task_id}: Configured for TTY-only mode (no SSH)")

        case "none":
            # No SSH key mode - enable password-less root login
            pkg_manager = _detect_package_manager(docker_image_tag)
            setup_cmd = _get_ssh_install_cmd(pkg_manager)
            setup_cmd += " && ssh-keygen -A && "
            setup_cmd += (
                "echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config && "
                "echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config && "
                "echo 'PermitEmptyPasswords yes' >> /etc/ssh/sshd_config && "
                "passwd -d root && "
                "mkdir -p /run/sshd && "
                "chmod 0755 /run/sshd && "
                "/usr/sbin/sshd -D -e"
            )
            logger.info(
                f"VPS {task_id}: Configured for passwordless root login (no SSH key)"
            )

        case "upload" | "generate":
            # SSH key mode - standard pubkey auth
            if not ssh_public_key:
                raise ValueError(f"ssh_public_key required for mode '{ssh_key_mode}'")

            pkg_manager = _detect_package_manager(docker_image_tag)
            setup_cmd = _get_ssh_install_cmd(pkg_manager)
            setup_cmd += " && ssh-keygen -A && "
            setup_cmd += (
                "echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config && "
                "echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config && "
                "mkdir -p /run/sshd && "
                "chmod 0755 /run/sshd && "
                "mkdir -p /root/.ssh && "
                f"echo '{ssh_public_key}' > /root/.ssh/authorized_keys && "
                "chmod 700 /root/.ssh && "
                "chmod 600 /root/.ssh/authorized_keys && "
                "/usr/sbin/sshd -D -e"
            )
            logger.info(f"VPS {task_id}: Configured with SSH public key authentication")

        case _:
            raise ValueError(f"Invalid ssh_key_mode: {ssh_key_mode}")

    # Wrap with tunnel-client startup if available
    # VPS uses use_exec=False since the main process (sshd or tail) stays running
    setup_cmd = wrap_command_with_tunnel(setup_cmd, container_name, use_exec=False)

    # Add image and command
    docker_cmd.append(docker_image_tag)
    docker_cmd.extend(["/bin/sh", "-c", setup_cmd])

    logger.debug(f"VPS {task_id} docker command: {' '.join(docker_cmd)}")
    return docker_cmd


async def _find_ssh_port(
    container_name: str, retries: int = 5, delay: float = 0.5
) -> int:
    """
    Find the mapped SSH port for a container.

    Args:
        container_name: Docker container name.
        retries: Number of retry attempts.
        delay: Delay between retries in seconds.

    Returns:
        SSH port number, or 0 if not found (VPS will still work via TTY).
    """
    for attempt in range(retries):
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "port",
                container_name,
                "22",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, "docker port", stderr
                )
            # Parse: "0.0.0.0:32792\n[::]:32792\n"
            port_mapping = stdout.decode().splitlines()[0].strip()
            port = int(port_mapping.split(":")[1])
            logger.debug(
                f"Found SSH port {port} for container '{container_name}' on attempt {attempt + 1}"
            )
            return port
        except subprocess.CalledProcessError:
            if attempt < retries - 1:
                logger.debug(
                    f"SSH port not ready for '{container_name}', retrying ({attempt + 1}/{retries})..."
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    f"Failed to find SSH port for container '{container_name}' after {retries} attempts. VPS will work via TTY only."
                )
                return 0
        except (IndexError, ValueError) as e:
            if attempt < retries - 1:
                logger.debug(
                    f"Failed to parse SSH port: {e}, retrying ({attempt + 1}/{retries})..."
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    f"Failed to parse SSH port for '{container_name}': {e}. VPS will work via TTY only."
                )
                return 0
    return 0


async def _report_vps_failure(
    task_id: int,
    error_message: str,
    start_time: datetime.datetime | None = None,
    exit_code: int | None = None,
) -> dict:
    """
    Report a VPS creation failure to the host and return an error result dict.

    Args:
        task_id: Task ID for this VPS.
        error_message: Human-readable error description.
        start_time: Optional start time (unused currently, reserved for future metrics).
        exit_code: Optional process exit code to include in the status update.

    Returns:
        Dictionary with ``{"success": False, "error": error_message}``.
    """
    status_update = TaskStatusUpdate(
        task_id=task_id,
        status="failed",
        message=error_message,
        completed_at=datetime.datetime.now(),
    )
    if exit_code is not None:
        status_update.exit_code = exit_code

    await report_status_to_host(status_update)
    return {
        "success": False,
        "error": error_message,
    }


async def _ensure_vps_image_available(
    task_id: int,
    container_name: str,
    registry_image: str | None,
    snapshot_tag: str | None,
) -> tuple[bool, str | None]:
    """
    Ensure the Docker image required for VPS creation is available locally.

    Decides between restoring from a snapshot (already local), pulling from a
    registry, or syncing from shared storage.

    Args:
        task_id: Task ID for this VPS.
        container_name: Base container image name (used for shared-storage sync).
        registry_image: Optional registry image to pull instead of syncing.
        snapshot_tag: If set, the snapshot image is assumed to already exist locally
                      and no pull/sync is performed.

    Returns:
        A ``(success, error_message)`` tuple.  On success ``error_message`` is
        ``None``; on failure it contains a human-readable description.
    """
    # Snapshot images are local commits — nothing to fetch.
    if snapshot_tag:
        return True, None

    if registry_image:
        logger.info(f"VPS {task_id}: Pulling registry image '{registry_image}'")
        if not await docker_pull(registry_image):
            error_message = f"Failed to pull registry image '{registry_image}'"
            logger.error(f"VPS {task_id}: {error_message}")
            return False, error_message
    else:
        logger.info(
            f"VPS {task_id}: Checking Docker image sync status for '{container_name}'"
        )
        if not await ensure_docker_image_synced(task_id, container_name):
            error_message = f"Docker image sync failed for container '{container_name}'"
            logger.error(f"VPS {task_id}: {error_message}")
            return False, error_message

    return True, None


async def _finalize_vps_creation(
    task_id: int,
    container_name: str,
    ssh_key_mode: str,
    required_cores: int,
    required_gpus: list[int],
    target_numa_node_id: int | None,
    task_store: TaskStateStore,
    start_time: datetime.datetime,
) -> dict:
    """
    Finalize a successfully started VPS container.

    Discovers the SSH port, persists the task in the local store, and reports
    the ``running`` status back to the host.

    Args:
        task_id: Task ID for this VPS.
        container_name: Full Docker container name (``vps_container_name(task_id)``).
        ssh_key_mode: SSH key mode used during creation.
        required_cores: Number of allocated CPU cores.
        required_gpus: List of allocated GPU indices.
        target_numa_node_id: NUMA node the container was pinned to.
        task_store: Local task state store.
        start_time: Timestamp recorded before creation began.

    Returns:
        Dictionary with ``{"success": True, "ssh_port": ..., "container_name": ...}``.
    """
    # Find the actual SSH port (only if SSH is enabled)
    if ssh_key_mode == "disabled":
        # No SSH - TTY-only mode
        actual_ssh_port = 0
        logger.info(f"VPS {task_id}: TTY-only mode, no SSH port")
    else:
        # Find SSH port - returns 0 if not found
        actual_ssh_port = await _find_ssh_port(container_name)
        if actual_ssh_port == 0:
            logger.warning(
                f"VPS {task_id}: SSH port not available, but VPS is running. "
                "TTY terminal access will still work."
            )

    # Store VPS state
    task_store.add_task(
        task_id=task_id,
        container_name=container_name,
        allocated_cores=required_cores,
        allocated_gpus=required_gpus,
        numa_node=target_numa_node_id,
    )

    # Report running status with SSH port
    await report_status_to_host(
        TaskStatusUpdate(
            task_id=task_id,
            status="running",
            started_at=start_time,
            ssh_port=actual_ssh_port,
        )
    )

    logger.info(
        f"VPS {task_id} started in container {container_name}, SSH port: {actual_ssh_port}"
    )

    return {
        "success": True,
        "ssh_port": actual_ssh_port,
        "container_name": container_name,
    }


async def create_vps(
    task_id: int,
    required_cores: int,
    required_gpus: list[int],
    required_memory_bytes: int | None,
    target_numa_node_id: int | None,
    container_name: str,
    ssh_key_mode: str,
    ssh_public_key: str | None,
    ssh_port: int,
    task_store: TaskStateStore,
    restore_from_snapshot: bool | None = None,
    reserved_ip: str | None = None,
    registry_image: str | None = None,
) -> dict:
    """
    Create a VPS container with SSH access using subprocess.

    Args:
        task_id: Task ID for this VPS.
        required_cores: Number of cores to allocate.
        required_gpus: List of GPU indices to allocate.
        required_memory_bytes: Memory limit in bytes.
        target_numa_node_id: Target NUMA node ID.
        container_name: Base container image name.
        ssh_key_mode: SSH key mode ("none", "upload", or "generate").
        ssh_public_key: SSH public key for access (None for "none" mode).
        ssh_port: SSH port to expose.
        task_store: Task state store.
        restore_from_snapshot: Whether to restore from latest snapshot if available.
                              If None, uses config.AUTO_RESTORE_ON_CREATE.
        reserved_ip: Pre-reserved IP address for the container (optional).

    Returns:
        Dictionary with VPS creation result.
    """
    # Import here to avoid circular imports — snapshot functions stay in vps_manager
    from kohakuriver.runner.services.vps_manager import get_latest_snapshot

    start_time = datetime.datetime.now()

    # Report pending status
    await report_status_to_host(
        TaskStatusUpdate(
            task_id=task_id,
            status="pending",
        )
    )

    # =========================================================================
    # Step 1: Resolve snapshot tag (if restoring)
    # =========================================================================
    should_restore = (
        restore_from_snapshot
        if restore_from_snapshot is not None
        else config.AUTO_RESTORE_ON_CREATE
    )

    snapshot_tag = None
    if should_restore:
        snapshot_tag = get_latest_snapshot(task_id)
        if snapshot_tag:
            logger.info(
                f"VPS {task_id}: Found existing snapshot, will restore from: {snapshot_tag}"
            )
        else:
            logger.debug(f"VPS {task_id}: No existing snapshots found, starting fresh")

    # =========================================================================
    # Step 2: Ensure Docker image is available
    # =========================================================================
    image_ok, image_error = await _ensure_vps_image_available(
        task_id, container_name, registry_image, snapshot_tag
    )
    if not image_ok:
        return await _report_vps_failure(task_id, image_error, start_time)

    # =========================================================================
    # Step 3: Build mount directories
    # shared_data subdirectory is mounted as /shared inside container
    # =========================================================================
    mount_dirs = [
        f"{config.SHARED_DIR}/shared_data:/shared",
        f"{config.LOCAL_TEMP_DIR}:/local_temp",
    ]
    mount_dirs.extend(config.ADDITIONAL_MOUNTS)

    # Add tunnel-client mount if available
    tunnel_mount = get_tunnel_mount()
    if tunnel_mount:
        mount_dirs.append(tunnel_mount)

    # Get the Docker image tag - use snapshot if available, then registry image, then base image
    if snapshot_tag:
        docker_image_tag = snapshot_tag
        logger.info(f"VPS {task_id}: Using snapshot image: {docker_image_tag}")
    elif registry_image:
        docker_image_tag = registry_image
        logger.info(f"VPS {task_id}: Using registry image: {docker_image_tag}")
    else:
        docker_image_tag = image_tag(container_name)
        logger.info(f"VPS {task_id}: Using base image: {docker_image_tag}")

    # =========================================================================
    # Step 4: Build and execute docker run command
    # (SSH port is assigned by Docker automatically, we query it after creation)
    # =========================================================================
    docker_cmd = _build_vps_docker_command(
        docker_image_tag=docker_image_tag,
        task_id=task_id,
        ssh_key_mode=ssh_key_mode,
        ssh_public_key=ssh_public_key,
        mount_dirs=mount_dirs,
        working_dir="/shared",
        cpu_cores=required_cores,
        memory_limit_bytes=required_memory_bytes,
        gpu_ids=required_gpus or [],
        privileged=config.TASKS_PRIVILEGED,
        reserved_ip=reserved_ip,
    )

    try:
        # Run docker command via subprocess
        process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        exit_code = process.returncode

        logger.debug(
            f"VPS {task_id} docker run exit code: {exit_code}: "
            f"{stdout.decode(errors='replace').strip()} | "
            f"{stderr.decode(errors='replace').strip()}"
        )

        if exit_code != 0:
            error_message = (
                f"Docker run failed: {stderr.decode(errors='replace').strip()}"
            )
            logger.error(f"VPS {task_id}: {error_message}")
            return await _report_vps_failure(
                task_id, error_message, start_time, exit_code=exit_code
            )

        # Finalize: discover SSH port, persist state, report success
        container_name_full = vps_container_name(task_id)
        return await _finalize_vps_creation(
            task_id=task_id,
            container_name=container_name_full,
            ssh_key_mode=ssh_key_mode,
            required_cores=required_cores,
            required_gpus=required_gpus,
            target_numa_node_id=target_numa_node_id,
            task_store=task_store,
            start_time=start_time,
        )

    except Exception as e:
        error_message = f"VPS creation failed: {e}"
        logger.error(error_message)
        logger.debug(format_traceback(e))
        return await _report_vps_failure(task_id, error_message, start_time)
