"""
Filesystem WebSocket watcher endpoints for task/VPS containers on the Runner.

Provides real-time file system change notifications using inotifywait
or polling fallback, for both Docker containers and VMs.
"""

import asyncio
import shlex
from collections.abc import Awaitable, Callable

import docker
from docker.errors import APIError as DockerAPIError
from docker.errors import NotFound as DockerNotFound
from fastapi import (
    WebSocket,
    WebSocketDisconnect,
)

from kohakuriver.runner.endpoints.filesystem_shared import (
    _exec_in_container,
    _is_vm_task,
    _resolve_task_data,
)
from kohakuriver.runner.services.vm_ssh import ssh_connect, ssh_exec
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Shared Helpers
# =============================================================================

# Type alias for an async exec function: (cmd, timeout) -> (exit_code, stdout, stderr)
ExecFn = Callable[..., Awaitable[tuple[int, str, str]]]
# Type alias for an async is_dir callback: (path) -> bool
IsDirFn = Callable[[str], Awaitable[bool]]


async def _handle_websocket_keepalive(
    websocket: WebSocket, stop_event: asyncio.Event
) -> None:
    """
    Receive WebSocket messages in a loop, respond to pings with pongs,
    and set stop_event on close/disconnect.

    Extracted from the identical inner functions (handle_websocket_input /
    handle_ws) that appeared in all watcher variants.
    """
    try:
        while not stop_event.is_set():
            try:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()


async def _get_file_list_via_exec(exec_fn: ExecFn, path: str) -> dict[str, float]:
    """
    Run ``find`` with ``-printf`` format (with fallback to plain ``find``),
    parse output into {path: mtime} dict.

    Shared between ``_watch_with_polling`` and ``_watch_vm_with_polling``.

    Args:
        exec_fn: An async callable ``(cmd, timeout) -> (exit_code, stdout, stderr)``.
        path: The directory path to list.
    """
    cmd = ["find", path, "-maxdepth", "3", "-printf", r"%p|%T@\n"]
    exit_code, stdout, _ = await exec_fn(cmd, 30)

    if exit_code != 0:
        # Fallback to simpler command
        cmd = ["find", path, "-maxdepth", "3"]
        exit_code, stdout, _ = await exec_fn(cmd, 30)
        if exit_code != 0:
            return {}
        # No mtime available, use 0
        return {line.strip(): 0 for line in stdout.strip().split("\n") if line.strip()}

    result = {}
    for line in stdout.strip().split("\n"):
        if "|" in line:
            file_path, mtime_str = line.rsplit("|", 1)
            try:
                result[file_path.strip()] = float(mtime_str.strip())
            except ValueError:
                result[file_path.strip()] = 0
    return result


async def _diff_file_states(
    old_state: dict[str, float],
    new_state: dict[str, float],
    is_dir_fn: IsDirFn,
) -> list[tuple[str, str, bool]]:
    """
    Compute created/deleted/modified files by comparing two state dicts.

    Returns a list of ``(event_type, path, is_dir)`` tuples.

    Args:
        old_state: Previous {path: mtime} mapping.
        new_state: Current {path: mtime} mapping.
        is_dir_fn: Async callable ``(path) -> bool`` used to determine
            whether a created or modified path is a directory.
            Deleted files always get ``is_dir=False``.
    """
    changes: list[tuple[str, str, bool]] = []
    old_files = set(old_state)
    new_files = set(new_state)

    # Created files
    for f in new_files - old_files:
        changes.append(("CREATE", f, await is_dir_fn(f)))

    # Deleted files
    for f in old_files - new_files:
        changes.append(("DELETE", f, False))

    # Modified files
    for f in old_files & new_files:
        if old_state[f] != new_state[f]:
            changes.append(("MODIFY", f, await is_dir_fn(f)))

    return changes


def _parse_inotify_line(line: str) -> dict | None:
    """
    Parse a single inotifywait output line into an event dict.

    Expected format: ``EVENT_FLAGS|PATH[|EXTRA]``

    Returns ``{"event": str, "path": str, "is_dir": bool}`` or ``None``
    if the line cannot be parsed.
    """
    parts = line.split("|")
    if len(parts) < 2:
        return None

    events = parts[0]
    file_path = parts[1]
    is_dir = "ISDIR" in events if len(parts) > 2 else False

    # Map inotify events to our event types
    event_type = "MODIFY"
    if "CREATE" in events:
        event_type = "CREATE"
    elif "DELETE" in events:
        event_type = "DELETE"
    elif "MOVE" in events:
        event_type = "MOVE"

    return {"event": event_type, "path": file_path, "is_dir": is_dir}


def _create_inotify_exec(container, paths: list[str]):
    """
    Create a Docker exec instance for inotifywait and return the raw socket.

    Args:
        container: Docker container object.
        paths: List of paths to watch.

    Returns:
        The raw socket for reading inotifywait output, or ``None`` on failure.
    """
    cmd = [
        "inotifywait",
        "-m",
        "-r",
        "-e",
        "create,modify,delete,move",
        "--format",
        "%e|%w%f|%:e",
    ] + paths

    exec_instance = container.client.api.exec_create(
        container.id,
        cmd=cmd,
        stdout=True,
        stderr=True,
        stdin=False,
        tty=False,
    )

    socket_stream = container.client.api.exec_start(
        exec_instance["Id"],
        socket=True,
        stream=True,
        tty=False,
        demux=False,
    )

    if not hasattr(socket_stream, "_sock") or not socket_stream._sock:
        return None

    raw_socket = socket_stream._sock
    raw_socket.settimeout(1.0)
    return raw_socket


async def _read_inotify_stream(
    raw_socket, stop_event: asyncio.Event, websocket: WebSocket
) -> None:
    """
    Read output from a Docker inotifywait exec socket and send parsed events
    to the WebSocket.

    Uses ``_parse_inotify_line`` to interpret each line.
    """
    buffer = ""
    while not stop_event.is_set():
        try:
            data = await asyncio.to_thread(raw_socket.recv, 4096)
            if not data:
                break

            # Decode and process output
            text = data.decode("utf-8", errors="replace")
            buffer += text

            # Process complete lines
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                parsed = _parse_inotify_line(line)
                if parsed:
                    await websocket.send_json(
                        {
                            "type": "change",
                            "event": parsed["event"],
                            "path": parsed["path"],
                            "is_dir": parsed["is_dir"],
                        }
                    )

        except TimeoutError:
            # Check for WebSocket messages during timeout
            continue
        except OSError:
            if stop_event.is_set():
                break
            raise
        except Exception as e:
            if not stop_event.is_set():
                logger.error(f"[FS Watch] Error reading inotify: {e}")
            break


# =============================================================================
# File System Watcher WebSocket Endpoint
# =============================================================================


async def watch_filesystem_handler(
    websocket: WebSocket,
    task_id: int,
    paths: str = "/shared,/local_temp",
):
    """
    WebSocket handler for real-time filesystem change notifications.

    Called from main app.py with /ws prefix.
    Supports both Docker containers and VMs.

    Uses inotifywait inside the container/VM to monitor file changes.
    Falls back to polling if inotifywait is not available.

    Events sent to client:
    - {"type": "change", "event": "CREATE|MODIFY|DELETE|MOVE", "path": "/path/to/file", "is_dir": bool}
    - {"type": "error", "message": "error description"}
    - {"type": "watching", "paths": ["/path1", "/path2"]}
    """
    await websocket.accept()

    # Resolve task
    task_data = _resolve_task_data(task_id)
    if not task_data:
        await websocket.send_json(
            {"type": "error", "message": f"Task {task_id} not found on this runner."}
        )
        await websocket.close()
        return

    # Parse paths to watch
    watch_paths = [p.strip() for p in paths.split(",") if p.strip()]
    if not watch_paths:
        watch_paths = ["/shared", "/local_temp"]

    if _is_vm_task(task_data):
        vm_ip = task_data.get("vm_ip")
        if not vm_ip:
            await websocket.send_json(
                {"type": "error", "message": f"VM {task_id} has no IP address."}
            )
            await websocket.close()
            return
        await _watch_vm_filesystem(websocket, task_id, vm_ip, watch_paths)
    else:
        await _watch_docker_filesystem(websocket, task_id, task_data, watch_paths)


async def _watch_docker_filesystem(
    websocket: WebSocket,
    task_id: int,
    task_data: dict,
    watch_paths: list[str],
):
    """Watch filesystem changes in a Docker container."""
    container_name = task_data.get("container_name")
    if not container_name:
        await websocket.send_json(
            {"type": "error", "message": f"Task {task_id} has no container."}
        )
        await websocket.close()
        return

    try:
        client = docker.from_env(timeout=30)
        container = client.containers.get(container_name)
        if container.status != "running":
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Container is not running (status: {container.status}).",
                }
            )
            await websocket.close()
            return
    except Exception as e:
        await websocket.send_json(
            {"type": "error", "message": f"Failed to connect to container: {e}"}
        )
        await websocket.close()
        return

    # Validate paths exist
    valid_paths = []
    for path in watch_paths:
        try:
            exit_code, _, _ = await _exec_in_container(
                container, ["test", "-d", path], timeout=5
            )
            if exit_code == 0:
                valid_paths.append(path)
        except Exception:
            pass

    if not valid_paths:
        await websocket.send_json(
            {"type": "error", "message": "No valid paths to watch."}
        )
        await websocket.close()
        client.close()
        return

    logger.info(
        f"[FS Watch] Starting Docker file watcher for task {task_id}, paths: {valid_paths}"
    )

    # Check if inotifywait is available
    exit_code, _, _ = await _exec_in_container(
        container, ["which", "inotifywait"], timeout=5
    )
    use_inotify = exit_code == 0

    if use_inotify:
        await _watch_with_inotify(websocket, container, valid_paths, task_id)
    else:
        await _watch_with_polling(websocket, container, valid_paths, task_id)

    client.close()


async def _watch_vm_filesystem(
    websocket: WebSocket,
    task_id: int,
    vm_ip: str,
    watch_paths: list[str],
):
    """Watch filesystem changes in a VM via SSH."""
    # Validate paths exist
    valid_paths = []
    for path in watch_paths:
        try:
            exit_code, _, _ = await ssh_exec(vm_ip, ["test", "-d", path], timeout=5)
            if exit_code == 0:
                valid_paths.append(path)
        except Exception:
            pass

    if not valid_paths:
        await websocket.send_json(
            {"type": "error", "message": "No valid paths to watch."}
        )
        await websocket.close()
        return

    logger.info(
        f"[FS Watch] Starting VM file watcher for task {task_id}, paths: {valid_paths}"
    )

    # Check if inotifywait is available
    exit_code, _, _ = await ssh_exec(vm_ip, ["which", "inotifywait"], timeout=5)
    use_inotify = exit_code == 0

    if use_inotify:
        await _watch_vm_with_inotify(websocket, task_id, vm_ip, valid_paths)
    else:
        await _watch_vm_with_polling(websocket, task_id, vm_ip, valid_paths)


# =============================================================================
# Inotify-based Watchers
# =============================================================================


async def _watch_vm_with_inotify(
    websocket: WebSocket,
    task_id: int,
    vm_ip: str,
    paths: list[str],
):
    """Watch filesystem in VM via SSH inotifywait."""
    conn = None
    process = None

    try:
        conn = await ssh_connect(vm_ip, timeout=15.0)

        # Build inotifywait command
        paths_str = " ".join(shlex.quote(p) for p in paths)
        cmd = (
            f"inotifywait -m -r -e create,modify,delete,move "
            f"--format '%e|%w%f|%:e' {paths_str}"
        )
        process = await conn.create_process(cmd)

        logger.info(f"[FS Watch] Using inotifywait via SSH for VM {task_id}")
        await websocket.send_json(
            {"type": "watching", "paths": paths, "method": "inotify"}
        )

        stop_event = asyncio.Event()

        async def read_output():
            try:
                while not stop_event.is_set():
                    line = await process.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue

                    parsed = _parse_inotify_line(line)
                    if parsed:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": parsed["event"],
                                "path": parsed["path"],
                                "is_dir": parsed["is_dir"],
                            }
                        )
            except asyncio.CancelledError:
                pass
            except Exception as e:
                if not stop_event.is_set():
                    logger.error(f"[FS Watch] VM inotify read error: {e}")

        read_task = asyncio.create_task(read_output())
        ws_task = asyncio.create_task(
            _handle_websocket_keepalive(websocket, stop_event)
        )
        await asyncio.wait([read_task, ws_task], return_when=asyncio.FIRST_COMPLETED)

    finally:
        if process:
            try:
                process.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    logger.info(f"[FS Watch] Stopped VM inotify watcher for task {task_id}")


async def _watch_with_inotify(
    websocket: WebSocket,
    container,
    paths: list[str],
    task_id: int,
):
    """
    Watch filesystem using inotifywait inside a Docker container.
    """
    logger.info(f"[FS Watch] Using inotifywait for task {task_id}")

    # Notify client we're watching
    await websocket.send_json({"type": "watching", "paths": paths, "method": "inotify"})

    # Create exec instance for inotifywait and get raw socket
    raw_socket = _create_inotify_exec(container, paths)
    if raw_socket is None:
        await websocket.send_json(
            {"type": "error", "message": "Failed to get socket for inotifywait."}
        )
        return

    stop_event = asyncio.Event()

    # Run both tasks
    try:
        read_task = asyncio.create_task(
            _read_inotify_stream(raw_socket, stop_event, websocket)
        )
        ws_task = asyncio.create_task(
            _handle_websocket_keepalive(websocket, stop_event)
        )

        await asyncio.wait([read_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()
        try:
            raw_socket.close()
        except Exception:
            pass

    logger.info(f"[FS Watch] Stopped watching for task {task_id}")


# =============================================================================
# Polling-based Watchers
# =============================================================================


async def _watch_with_polling(
    websocket: WebSocket,
    container,
    paths: list[str],
    task_id: int,
    interval: float = 2.0,
):
    """
    Watch filesystem using polling (fallback when inotifywait is not available).
    """
    logger.info(
        f"[FS Watch] Using polling for task {task_id} (inotifywait not available)"
    )

    # Notify client we're watching
    await websocket.send_json(
        {"type": "watching", "paths": paths, "method": "polling", "interval": interval}
    )

    # Build exec closure for Docker container
    async def exec_fn(cmd: list[str], timeout: int) -> tuple[int, str, str]:
        return await _exec_in_container(container, cmd, timeout=timeout)

    # Build is_dir closure (preserves endswith("/") check from original)
    async def is_dir_fn(path: str) -> bool:
        return path.endswith("/") or await _is_directory(container, path)

    # State: path -> {name -> mtime}
    file_states: dict[str, dict[str, float]] = {}

    # Get initial state
    for path in paths:
        file_states[path] = await _get_file_list_via_exec(exec_fn, path)

    stop_event = asyncio.Event()

    async def poll_changes():
        """Poll for file changes."""
        while not stop_event.is_set():
            await asyncio.sleep(interval)

            for path in paths:
                try:
                    new_state = await _get_file_list_via_exec(exec_fn, path)
                    old_state = file_states.get(path, {})

                    changes = await _diff_file_states(old_state, new_state, is_dir_fn)
                    for event_type, f, f_is_dir in changes:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": event_type,
                                "path": f,
                                "is_dir": f_is_dir,
                            }
                        )

                    file_states[path] = new_state

                except Exception as e:
                    logger.warning(f"[FS Watch] Poll error for {path}: {e}")

    # Run both tasks
    try:
        poll_task = asyncio.create_task(poll_changes())
        ws_task = asyncio.create_task(
            _handle_websocket_keepalive(websocket, stop_event)
        )

        await asyncio.wait([poll_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()

    logger.info(f"[FS Watch] Stopped polling for task {task_id}")


async def _watch_vm_with_polling(
    websocket: WebSocket,
    task_id: int,
    vm_ip: str,
    paths: list[str],
    interval: float = 2.0,
):
    """Watch filesystem in VM via SSH polling."""
    logger.info(
        f"[FS Watch] Using polling via SSH for VM {task_id} (inotifywait not available)"
    )
    await websocket.send_json(
        {"type": "watching", "paths": paths, "method": "polling", "interval": interval}
    )

    # Build exec closure for SSH
    async def exec_fn(cmd: list[str], timeout: int) -> tuple[int, str, str]:
        return await ssh_exec(vm_ip, cmd, timeout=timeout)

    # Build is_dir closure for SSH
    async def is_dir_fn(path: str) -> bool:
        exit_code, _, _ = await ssh_exec(vm_ip, ["test", "-d", path], timeout=2)
        return exit_code == 0

    file_states: dict[str, dict[str, float]] = {}

    # Get initial state
    for path in paths:
        file_states[path] = await _get_file_list_via_exec(exec_fn, path)

    stop_event = asyncio.Event()

    async def poll_changes():
        while not stop_event.is_set():
            await asyncio.sleep(interval)
            for path in paths:
                try:
                    new_state = await _get_file_list_via_exec(exec_fn, path)
                    old_state = file_states.get(path, {})

                    changes = await _diff_file_states(old_state, new_state, is_dir_fn)
                    for event_type, f, f_is_dir in changes:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": event_type,
                                "path": f,
                                "is_dir": f_is_dir,
                            }
                        )

                    file_states[path] = new_state
                except Exception as e:
                    logger.warning(f"[FS Watch] VM poll error for {path}: {e}")

    try:
        poll_task = asyncio.create_task(poll_changes())
        ws_task = asyncio.create_task(
            _handle_websocket_keepalive(websocket, stop_event)
        )
        await asyncio.wait([poll_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()

    logger.info(f"[FS Watch] Stopped VM polling for task {task_id}")


# =============================================================================
# Utilities
# =============================================================================


async def _is_directory(container, path: str) -> bool:
    """Check if path is a directory."""
    try:
        exit_code, _, _ = await _exec_in_container(
            container, ["test", "-d", path], timeout=2
        )
        return exit_code == 0
    except Exception:
        return False
