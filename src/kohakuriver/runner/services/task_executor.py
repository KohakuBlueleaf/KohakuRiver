"""
Task execution service.

Handles Docker container creation and task lifecycle management.
Uses subprocess-based Docker execution for task containers (matching old behavior).
"""

import asyncio
import datetime
import functools
import os
import shlex
import subprocess

import httpx

from kohakuriver.docker import utils as docker_utils
from kohakuriver.docker.naming import image_tag, task_container_name
from kohakuriver.models.requests import TaskStatusUpdate
from kohakuriver.runner.config import config
from kohakuriver.runner.numa.detector import get_numa_prefix
from kohakuriver.runner.services.tunnel_helper import (
    get_tunnel_env_vars,
    get_tunnel_mount,
    wrap_command_with_tunnel,
)
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import format_traceback, get_logger

logger = get_logger(__name__)

# Lock for Docker image sync operations to prevent concurrent syncs
docker_sync_lock = asyncio.Lock()


def _run_docker_command(
    cmd: list[str], check: bool = False, timeout: int | None = None
) -> subprocess.CompletedProcess:
    """
    Run a Docker command via subprocess.

    Args:
        cmd: Command list to run.
        check: If True, raise CalledProcessError on non-zero exit.
        timeout: Optional timeout in seconds.

    Returns:
        CompletedProcess result.
    """
    logger.debug(f"Running docker command: {' '.join(shlex.quote(c) for c in cmd)}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.debug(f"  Command returned non-zero: {result.returncode}")
            if result.stderr:
                logger.debug(f"  stderr: {result.stderr.strip()}")
        else:
            logger.debug(f"  Command succeeded")
        return result
    except subprocess.TimeoutExpired as e:
        logger.error(f"Docker command timed out: {e}")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"Docker command failed: {e}")
        logger.debug(f"  stderr: {e.stderr}")
        raise
    except Exception as e:
        logger.exception(f"Unexpected error running docker command: {e}")
        raise


async def report_status_to_host(update: TaskStatusUpdate):
    """
    Report task status update to the host.

    Args:
        update: Task status update data.
    """
    host_url = f"http://{config.HOST_ADDRESS}:{config.HOST_PORT}"
    logger.debug(
        f"[Task {update.task_id}] report_status_to_host called: status={update.status}"
    )
    logger.info(
        f"[Task {update.task_id}] Reporting status '{update.status}' to host {host_url}"
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{host_url}/api/update",
                json=update.model_dump(mode="json"),
                timeout=15.0,
            )
            response.raise_for_status()
        logger.info(
            f"[Task {update.task_id}] Host acknowledged status update: {update.status}"
        )

    except httpx.RequestError as e:
        logger.error(f"[Task {update.task_id}] Failed to report status to host: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[Task {update.task_id}] Host rejected status update: "
            f"{e.response.status_code} - {e.response.text}"
        )
    except Exception as e:
        logger.exception(
            f"[Task {update.task_id}] Unexpected error reporting status: {e}"
        )


async def ensure_docker_image_synced(task_id: int, container_name: str) -> bool:
    """
    Ensure the Docker image is synced from shared storage before running a task.

    This checks if the local image is up-to-date by comparing timestamps:
    1. Get local image timestamp
    2. Get latest shared tarball timestamp
    3. If shared is newer (or local doesn't exist), load the tarball

    Args:
        task_id: Task ID (for logging).
        container_name: KohakuRiver container name (e.g., "kohakuriver-base").

    Returns:
        True if image is ready, False if sync failed.
    """
    container_tar_dir = config.get_container_tar_dir()
    logger.debug(
        f"[Task {task_id}] ensure_docker_image_synced: container={container_name}, tar_dir={container_tar_dir}"
    )

    try:
        async with docker_sync_lock:
            logger.debug(f"[Task {task_id}] Acquired docker_sync_lock")

            # Check if sync is needed
            logger.debug(f"[Task {task_id}] Calling docker_utils.needs_sync()...")
            needs_sync, sync_path = docker_utils.needs_sync(
                container_name, container_tar_dir
            )
            logger.debug(
                f"[Task {task_id}] needs_sync={needs_sync}, sync_path={sync_path}"
            )

            if not needs_sync:
                logger.info(
                    f"Task {task_id}: Local Docker image '{container_name}' is up-to-date."
                )
                return True

            if not sync_path:
                # needs_sync is True but no path - this means no tarball exists
                logger.error(
                    f"Task {task_id}: No tarball found for container '{container_name}' "
                    f"in {container_tar_dir}"
                )
                return False

            # Sync the image from shared storage
            sync_timeout = config.DOCKER_IMAGE_SYNC_TIMEOUT
            logger.info(
                f"Task {task_id}: Syncing Docker image '{container_name}' from {sync_path} "
                f"(timeout: {sync_timeout}s)..."
            )
            sync_func = functools.partial(
                docker_utils.sync_from_shared,
                container_name,
                sync_path,
                timeout=sync_timeout,
            )
            sync_success = await asyncio.get_running_loop().run_in_executor(
                None,
                sync_func,
            )

            if not sync_success:
                logger.error(
                    f"Task {task_id}: Failed to sync Docker image from {sync_path}"
                )
                return False

            logger.info(f"Task {task_id}: Docker image sync successful.")
            return True

    except Exception as e:
        logger.error(f"Task {task_id}: Docker image sync failed: {e}")
        logger.debug(f"Task {task_id}: Traceback:\n{format_traceback(e)}")
        return False


def build_docker_run_command(
    task_id: int,
    docker_image_tag: str,
    command: str,
    arguments: list[str],
    working_dir: str,
    stdout_path: str,
    stderr_path: str,
    numa_prefix: str | None,
    required_cores: int,
    required_memory_bytes: int | None,
    required_gpus: list[str],
    env_vars: dict[str, str],
    privileged: bool = False,
) -> list[str]:
    """
    Build a 'docker run --rm' command list for subprocess execution.

    This matches the old behavior using subprocess-based Docker execution.

    Args:
        task_id: Task ID.
        docker_image_tag: Full Docker image tag (e.g., "kohakuriver/container:base").
        command: Command to run.
        arguments: Command arguments.
        working_dir: Working directory inside container.
        stdout_path: Path to stdout log file.
        stderr_path: Path to stderr log file.
        numa_prefix: NUMA binding prefix (e.g., "numactl --cpunodebind=0 --membind=0").
        required_cores: Number of CPU cores.
        required_memory_bytes: Memory limit in bytes.
        required_gpus: List of GPU IDs.
        env_vars: Environment variables.
        privileged: Run in privileged mode.

    Returns:
        Command list for subprocess execution.
    """
    logger.debug(f"[Task {task_id}] build_docker_run_command called")
    logger.debug(f"[Task {task_id}]   image={docker_image_tag}")
    logger.debug(f"[Task {task_id}]   command={command}, args={arguments}")
    logger.debug(f"[Task {task_id}]   working_dir={working_dir}")
    logger.debug(f"[Task {task_id}]   stdout={stdout_path}, stderr={stderr_path}")
    logger.debug(f"[Task {task_id}]   numa_prefix={numa_prefix}")
    logger.debug(
        f"[Task {task_id}]   cores={required_cores}, mem={required_memory_bytes}, gpus={required_gpus}"
    )
    logger.debug(f"[Task {task_id}]   privileged={privileged}")

    container_name_full = task_container_name(task_id)

    # Build docker run command
    docker_cmd = ["docker", "run", "--rm"]

    # Container name
    docker_cmd.extend(["--name", container_name_full])

    # Use kohakuriver-net bridge network
    # Containers on same node can communicate via container name
    # Network is created on runner startup with known gateway for tunnel access
    docker_cmd.extend(["--network", "kohakuriver-net"])

    # Privileged mode
    if privileged:
        docker_cmd.append("--privileged")
        logger.warning(
            f"Task {task_id}: Running Docker container with --privileged flag!"
        )
    else:
        docker_cmd.extend(["--cap-add", "SYS_NICE"])

    # Mount directories
    # shared_data subdirectory is mounted as /shared inside container
    # logs directory is mounted as /kohakuriver-logs for task output
    mount_dirs = [
        f"{config.SHARED_DIR}/shared_data:/shared",
        f"{config.SHARED_DIR}/logs:/kohakuriver-logs",
        f"{config.LOCAL_TEMP_DIR}:/local_temp",
    ]
    for mount_spec in config.ADDITIONAL_MOUNTS:
        mount_dirs.append(mount_spec)

    # Add tunnel-client mount if available
    tunnel_mount = get_tunnel_mount()
    if tunnel_mount:
        mount_dirs.append(tunnel_mount)

    for mount in mount_dirs:
        parts = mount.split(":")
        if len(parts) < 2:
            logger.warning(f"Invalid mount format: '{mount}'. Skipping.")
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

    # CPU allocation
    if required_cores > 0:
        docker_cmd.extend(["--cpus", str(required_cores)])

    # Memory limit
    if required_memory_bytes and required_memory_bytes > 0:
        # Convert to MB for docker
        mem_mb = required_memory_bytes / (1024 * 1024)
        docker_cmd.extend(["--memory", f"{mem_mb:.0f}m"])

    # GPU allocation
    if required_gpus:
        id_string = ",".join(str(g) for g in required_gpus)
        docker_cmd.extend(["--gpus", f'"device={id_string}"'])

    # Environment variables
    for key, value in env_vars.items():
        docker_cmd.extend(["-e", f"{key}={value}"])

    # Add tunnel environment variables if tunnel is enabled
    tunnel_env = get_tunnel_env_vars(container_name_full)
    for key, value in tunnel_env.items():
        docker_cmd.extend(["-e", f"{key}={value}"])

    # Add container image
    docker_cmd.append(docker_image_tag)

    # Build the inner command (what runs inside the container)
    # Quote arguments for shell
    quoted_args = [shlex.quote(arg) for arg in arguments]
    args_str = " ".join(quoted_args) if quoted_args else ""

    if numa_prefix:
        inner_cmd = f"{numa_prefix} {command} {args_str}".strip()
    else:
        inner_cmd = f"{command} {args_str}".strip()

    # Quote stdout/stderr paths for shell
    quoted_stdout = shlex.quote(stdout_path)
    quoted_stderr = shlex.quote(stderr_path)

    # Build shell command with redirection
    # Using 'exec' replaces the shell with our command, ensuring proper signal handling
    shell_cmd = f"exec {inner_cmd} > {quoted_stdout} 2> {quoted_stderr}"

    # Wrap with tunnel-client startup if available
    shell_cmd = wrap_command_with_tunnel(shell_cmd, container_name_full, use_exec=True)

    logger.debug(f"[Task {task_id}] Inner shell command: {shell_cmd}")

    # Add shell wrapper
    docker_cmd.extend(["/bin/sh", "-c", shell_cmd])

    logger.debug(f"[Task {task_id}] Full docker command: {docker_cmd}")

    return docker_cmd


async def execute_task(
    task_id: int,
    command: str,
    arguments: list[str],
    env_vars: dict[str, str],
    required_cores: int,
    required_gpus: list[str],
    required_memory_bytes: int | None,
    target_numa_node_id: int | None,
    container_name: str,
    working_dir: str,
    stdout_path: str,
    stderr_path: str,
    numa_topology: dict | None,
    task_store: TaskStateStore,
):
    """
    Execute a task in a Docker container using subprocess.

    This is the main task execution function that:
    1. Syncs Docker image from shared storage if needed
    2. Builds and runs Docker container via subprocess
    3. Reports status updates to the host
    4. Waits for completion
    5. Reports final status
    """
    logger.info(f"[Task {task_id}] ========== STARTING TASK EXECUTION ==========")
    logger.info(f"[Task {task_id}] Command: {command}")
    logger.info(f"[Task {task_id}] Arguments: {arguments}")
    logger.info(f"[Task {task_id}] Container: {container_name}")
    logger.info(f"[Task {task_id}] Working dir: {working_dir}")
    logger.info(
        f"[Task {task_id}] Cores: {required_cores}, GPUs: {required_gpus}, Memory: {required_memory_bytes}"
    )
    logger.info(f"[Task {task_id}] NUMA node: {target_numa_node_id}")
    logger.info(f"[Task {task_id}] Stdout: {stdout_path}")
    logger.info(f"[Task {task_id}] Stderr: {stderr_path}")

    start_time = datetime.datetime.now()
    container_name_full = task_container_name(task_id)

    # Report pending status
    logger.info(f"[Task {task_id}] Reporting pending status to host...")
    await report_status_to_host(
        TaskStatusUpdate(
            task_id=task_id,
            status="pending",
            started_at=start_time,
        )
    )

    # Ensure output directories exist
    logger.info(f"[Task {task_id}] Creating output directories...")
    logger.debug(f"[Task {task_id}]   stdout dir: {os.path.dirname(stdout_path)}")
    logger.debug(f"[Task {task_id}]   stderr dir: {os.path.dirname(stderr_path)}")
    os.makedirs(os.path.dirname(stdout_path), exist_ok=True)
    os.makedirs(os.path.dirname(stderr_path), exist_ok=True)

    # =========================================================================
    # Step 1: Ensure Docker image is synced from shared storage
    # =========================================================================
    logger.info(
        f"[Task {task_id}] Step 1: Checking Docker image sync status for '{container_name}'"
    )

    if not await ensure_docker_image_synced(task_id, container_name):
        error_message = f"Docker image sync failed for container '{container_name}'"
        logger.error(f"[Task {task_id}] {error_message}")
        await report_status_to_host(
            TaskStatusUpdate(
                task_id=task_id,
                status="failed",
                message=error_message,
                completed_at=datetime.datetime.now(),
            )
        )
        logger.info(
            f"[Task {task_id}] ========== TASK EXECUTION FAILED (image sync) =========="
        )
        return

    logger.info(f"[Task {task_id}] Step 1 complete: Docker image ready")

    # =========================================================================
    # Step 2: Build task configuration
    # =========================================================================
    logger.info(f"[Task {task_id}] Step 2: Building task configuration...")

    # Build environment variables
    task_env = env_vars.copy()
    task_env["KOHAKURIVER_TASK_ID"] = str(task_id)
    task_env["KOHAKURIVER_LOCAL_TEMP_DIR"] = config.LOCAL_TEMP_DIR
    task_env["KOHAKURIVER_SHARED_DIR"] = config.SHARED_DIR
    if target_numa_node_id is not None:
        task_env["KOHAKURIVER_TARGET_NUMA_NODE"] = str(target_numa_node_id)
    logger.debug(f"[Task {task_id}] Environment variables: {list(task_env.keys())}")

    # Get NUMA prefix if applicable
    numa_prefix = get_numa_prefix(target_numa_node_id, numa_topology)
    logger.info(
        f"[Task {task_id}] NUMA prefix: {numa_prefix if numa_prefix else 'None'}"
    )

    # Convert host paths to container paths for stdout/stderr
    # Host path: {SHARED_DIR}/logs/... -> Container path: /kohakuriver-logs/...
    logs_dir = os.path.join(config.SHARED_DIR, "logs")
    container_stdout_path = stdout_path.replace(logs_dir, "/kohakuriver-logs", 1)
    container_stderr_path = stderr_path.replace(logs_dir, "/kohakuriver-logs", 1)
    logger.debug(f"[Task {task_id}] Container stdout path: {container_stdout_path}")
    logger.debug(f"[Task {task_id}] Container stderr path: {container_stderr_path}")

    # Get the full Docker image tag
    docker_image_tag = image_tag(container_name)
    logger.debug(f"[Task {task_id}] Docker image tag: {docker_image_tag}")

    # Build the docker run command
    docker_cmd = build_docker_run_command(
        task_id=task_id,
        docker_image_tag=docker_image_tag,
        command=command,
        arguments=arguments,
        working_dir=working_dir,
        stdout_path=container_stdout_path,  # Use container path, not host path
        stderr_path=container_stderr_path,  # Use container path, not host path
        numa_prefix=numa_prefix,
        required_cores=required_cores,
        required_memory_bytes=required_memory_bytes,
        required_gpus=required_gpus,
        env_vars=task_env,
        privileged=config.TASKS_PRIVILEGED,
    )

    logger.info(f"[Task {task_id}] Step 2 complete: Task configuration built")

    # =========================================================================
    # Step 3: Run the Docker container via subprocess
    # =========================================================================
    logger.info(f"[Task {task_id}] Step 3: Running Docker container...")

    try:
        # Store task state BEFORE starting the container
        logger.debug(f"[Task {task_id}] Storing task state in task_store...")
        task_store.add_task(
            task_id=task_id,
            container_name=container_name_full,
            allocated_cores=required_cores,
            allocated_gpus=required_gpus,
            numa_node=target_numa_node_id,
        )

        # Report running status
        logger.info(f"[Task {task_id}] Reporting running status to host...")
        await report_status_to_host(
            TaskStatusUpdate(
                task_id=task_id,
                status="running",
                started_at=start_time,
            )
        )

        logger.info(
            f"[Task {task_id}] Starting subprocess: {' '.join(shlex.quote(c) for c in docker_cmd[:10])}..."
        )

        # Run the docker command via async subprocess
        process = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.debug(f"[Task {task_id}] Subprocess PID: {process.pid}")

        logger.info(f"[Task {task_id}] Container started, waiting for completion...")

        # Wait for process to finish
        stdout_data, stderr_data = await process.communicate()
        exit_code = process.returncode

        logger.info(f"[Task {task_id}] Container finished with exit code: {exit_code}")
        if stdout_data:
            logger.debug(
                f"[Task {task_id}] Docker stdout: {stdout_data.decode(errors='replace').strip()}"
            )
        if stderr_data:
            logger.debug(
                f"[Task {task_id}] Docker stderr: {stderr_data.decode(errors='replace').strip()}"
            )

        # Check if task was killed by host (kill_task removes from store before we get here)
        # If task is no longer in store, it was killed externally - don't report status
        task_data = task_store.get_task(task_id)
        logger.debug(f"[Task {task_id}] Task data in store: {task_data}")
        if task_data is None:
            logger.info(
                f"[Task {task_id}] Task was removed from store (likely killed by host). "
                "Skipping status report."
            )
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            logger.info(
                f"[Task {task_id}] ========== TASK KILLED EXTERNALLY ({elapsed:.2f}s) =========="
            )
            return

        # Remove from tracking (task still exists, so this is normal completion)
        logger.debug(f"[Task {task_id}] Removing task from task_store...")
        task_store.remove_task(task_id)

        # Determine final status
        # Exit code 137 = 128 + 9 (SIGKILL) - could be OOM or manual kill
        # Exit code 143 = 128 + 15 (SIGTERM) - graceful termination
        if exit_code == 0:
            status = "completed"
            message = None
        elif exit_code == 137:
            status = "killed_oom"
            message = "Container killed (SIGKILL) - likely out of memory."
        elif exit_code == 143:
            status = "failed"
            message = "Container terminated (SIGTERM)."
        else:
            status = "failed"
            message = f"Container exited with code {exit_code}."
            # Include docker stderr in error message if present
            if stderr_data:
                stderr_str = stderr_data.decode(errors="replace").strip()
                if stderr_str:
                    message += f" Docker stderr: {stderr_str[:500]}"

        logger.info(f"[Task {task_id}] Final status: {status}")
        if message:
            logger.info(f"[Task {task_id}] Message: {message}")

        # Report completion
        logger.info(f"[Task {task_id}] Reporting completion status to host...")
        await report_status_to_host(
            TaskStatusUpdate(
                task_id=task_id,
                status=status,
                exit_code=exit_code,
                message=message,
                started_at=start_time,
                completed_at=datetime.datetime.now(),
            )
        )

        elapsed = (datetime.datetime.now() - start_time).total_seconds()
        logger.info(
            f"[Task {task_id}] ========== TASK EXECUTION COMPLETED ({elapsed:.2f}s) =========="
        )

    except Exception as e:
        error_message = f"Task execution failed: {e}"
        logger.error(f"[Task {task_id}] {error_message}")
        logger.error(f"[Task {task_id}] Traceback:\n{format_traceback(e)}")

        # Remove from tracking
        task_store.remove_task(task_id)

        # Report failure
        await report_status_to_host(
            TaskStatusUpdate(
                task_id=task_id,
                status="failed",
                message=error_message,
                started_at=start_time,
                completed_at=datetime.datetime.now(),
            )
        )
        logger.info(f"[Task {task_id}] ========== TASK EXECUTION FAILED ==========")


def kill_task(
    task_id: int,
    container_name: str,
    task_store: TaskStateStore,
) -> bool:
    """
    Kill a running task.

    Args:
        task_id: Task ID to kill.
        container_name: Docker container name (e.g., kohakuriver-task-123 or kohakuriver-vps-123).
        task_store: Task state store.

    Returns:
        True if kill was successful, False otherwise.
    """
    logger.debug(f"kill_task called: task_id={task_id}, container={container_name}")

    try:
        # Remove from tracking FIRST (so execute_task knows not to report status)
        logger.debug(f"Removing task {task_id} from task_store...")
        task_store.remove_task(task_id)

        # Kill the container using docker kill
        logger.debug(f"Killing container {container_name}...")
        result = _run_docker_command(["docker", "kill", container_name], check=False)

        if result.returncode == 0:
            logger.info(f"Killed task {task_id}")
            return True
        else:
            logger.warning(
                f"docker kill returned {result.returncode} for task {task_id}: {result.stderr}"
            )
            return True  # Still return True since task was removed from tracking

    except Exception as e:
        logger.error(f"Failed to kill task {task_id}: {e}")
        return False


def pause_task(
    task_id: int,
    container_name: str,
    task_store: TaskStateStore,
) -> bool:
    """
    Pause a running task.

    Args:
        task_id: Task ID to pause.
        container_name: Docker container name.
        task_store: Task state store.

    Returns:
        True if pause was successful, False otherwise.
    """
    logger.debug(f"pause_task called: task_id={task_id}, container={container_name}")

    try:
        result = _run_docker_command(["docker", "pause", container_name], check=False)

        if result.returncode == 0:
            logger.info(f"Paused task {task_id}")
            return True
        else:
            logger.error(f"Failed to pause task {task_id}: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Failed to pause task {task_id}: {e}")
        return False


def resume_task(
    task_id: int,
    container_name: str,
    task_store: TaskStateStore,
) -> bool:
    """
    Resume a paused task.

    Args:
        task_id: Task ID to resume.
        container_name: Docker container name.
        task_store: Task state store.

    Returns:
        True if resume was successful, False otherwise.
    """
    logger.debug(f"resume_task called: task_id={task_id}, container={container_name}")

    try:
        result = _run_docker_command(["docker", "unpause", container_name], check=False)

        if result.returncode == 0:
            logger.info(f"Resumed task {task_id}")
            return True
        else:
            logger.error(f"Failed to resume task {task_id}: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Failed to resume task {task_id}: {e}")
        return False
