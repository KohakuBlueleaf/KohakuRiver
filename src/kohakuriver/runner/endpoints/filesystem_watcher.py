"""
Filesystem WebSocket watcher endpoints for task/VPS containers on the Runner.

Provides real-time file system change notifications using inotifywait
or polling fallback, for both Docker containers and VMs.
"""

import asyncio
import shlex

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

                    parts = line.split("|")
                    if len(parts) >= 2:
                        events = parts[0]
                        file_path = parts[1]
                        is_dir = "ISDIR" in events if len(parts) > 2 else False

                        event_type = "MODIFY"
                        if "CREATE" in events:
                            event_type = "CREATE"
                        elif "DELETE" in events:
                            event_type = "DELETE"
                        elif "MOVE" in events:
                            event_type = "MOVE"

                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": event_type,
                                "path": file_path,
                                "is_dir": is_dir,
                            }
                        )
            except asyncio.CancelledError:
                pass
            except Exception as e:
                if not stop_event.is_set():
                    logger.error(f"[FS Watch] VM inotify read error: {e}")

        async def handle_ws():
            try:
                while not stop_event.is_set():
                    try:
                        message = await asyncio.wait_for(
                            websocket.receive_json(), timeout=1.0
                        )
                        if message.get("type") == "ping":
                            await websocket.send_json({"type": "pong"})
                    except asyncio.TimeoutError:
                        continue
            except WebSocketDisconnect:
                pass
            finally:
                stop_event.set()

        read_task = asyncio.create_task(read_output())
        ws_task = asyncio.create_task(handle_ws())
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

    file_states: dict[str, dict[str, float]] = {}

    async def get_file_list(path: str) -> dict[str, float]:
        cmd = ["find", path, "-maxdepth", "3", "-printf", r"%p|%T@\n"]
        exit_code, stdout, _ = await ssh_exec(vm_ip, cmd, timeout=30)

        if exit_code != 0:
            cmd = ["find", path, "-maxdepth", "3"]
            exit_code, stdout, _ = await ssh_exec(vm_ip, cmd, timeout=30)
            if exit_code != 0:
                return {}
            return {
                line.strip(): 0 for line in stdout.strip().split("\n") if line.strip()
            }

        result = {}
        for line in stdout.strip().split("\n"):
            if "|" in line:
                file_path, mtime_str = line.rsplit("|", 1)
                try:
                    result[file_path.strip()] = float(mtime_str.strip())
                except ValueError:
                    result[file_path.strip()] = 0
        return result

    async def is_dir(path: str) -> bool:
        exit_code, _, _ = await ssh_exec(vm_ip, ["test", "-d", path], timeout=2)
        return exit_code == 0

    # Get initial state
    for path in paths:
        file_states[path] = await get_file_list(path)

    stop_event = asyncio.Event()

    async def poll_changes():
        while not stop_event.is_set():
            await asyncio.sleep(interval)
            for path in paths:
                try:
                    new_state = await get_file_list(path)
                    old_state = file_states.get(path, {})
                    old_files = set(old_state)
                    new_files = set(new_state)

                    for f in new_files - old_files:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": "CREATE",
                                "path": f,
                                "is_dir": await is_dir(f),
                            }
                        )
                    for f in old_files - new_files:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": "DELETE",
                                "path": f,
                                "is_dir": False,
                            }
                        )
                    for f in old_files & new_files:
                        if old_state[f] != new_state[f]:
                            await websocket.send_json(
                                {
                                    "type": "change",
                                    "event": "MODIFY",
                                    "path": f,
                                    "is_dir": await is_dir(f),
                                }
                            )
                    file_states[path] = new_state
                except Exception as e:
                    logger.warning(f"[FS Watch] VM poll error for {path}: {e}")

    async def handle_ws():
        try:
            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=1.0
                    )
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            stop_event.set()

    try:
        poll_task = asyncio.create_task(poll_changes())
        ws_task = asyncio.create_task(handle_ws())
        await asyncio.wait([poll_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()

    logger.info(f"[FS Watch] Stopped VM polling for task {task_id}")


async def _watch_with_inotify(
    websocket: WebSocket,
    container,
    paths: list[str],
    task_id: int,
):
    """
    Watch filesystem using inotifywait.
    """
    # Build inotifywait command
    # -m: monitor mode (continuous)
    # -r: recursive
    # -e: events to watch
    # --format: output format
    paths_str = " ".join(paths)
    cmd = [
        "inotifywait",
        "-m",
        "-r",
        "-e",
        "create,modify,delete,move",
        "--format",
        "%e|%w%f|%:e",
    ] + paths

    logger.info(f"[FS Watch] Using inotifywait for task {task_id}")

    # Notify client we're watching
    await websocket.send_json({"type": "watching", "paths": paths, "method": "inotify"})

    # Create exec instance for inotifywait
    exec_instance = container.client.api.exec_create(
        container.id,
        cmd=cmd,
        stdout=True,
        stderr=True,
        stdin=False,
        tty=False,
    )

    # Start exec and get socket
    socket_stream = container.client.api.exec_start(
        exec_instance["Id"],
        socket=True,
        stream=True,
        tty=False,
        demux=False,
    )

    if not hasattr(socket_stream, "_sock") or not socket_stream._sock:
        await websocket.send_json(
            {"type": "error", "message": "Failed to get socket for inotifywait."}
        )
        return

    raw_socket = socket_stream._sock
    raw_socket.settimeout(1.0)

    stop_event = asyncio.Event()

    async def read_inotify_output():
        """Read output from inotifywait and send to WebSocket."""
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

                    # Parse inotifywait output: EVENT|PATH|IS_DIR
                    parts = line.split("|")
                    if len(parts) >= 2:
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
                        elif "MODIFY" in events:
                            event_type = "MODIFY"

                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": event_type,
                                "path": file_path,
                                "is_dir": is_dir,
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

    async def handle_websocket_input():
        """Handle incoming WebSocket messages (for close/ping)."""
        try:
            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=1.0
                    )
                    # Handle ping
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            stop_event.set()

    # Run both tasks
    try:
        read_task = asyncio.create_task(read_inotify_output())
        ws_task = asyncio.create_task(handle_websocket_input())

        await asyncio.wait([read_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()
        try:
            raw_socket.close()
        except Exception:
            pass

    logger.info(f"[FS Watch] Stopped watching for task {task_id}")


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

    # State: path -> {name -> mtime}
    file_states: dict[str, dict[str, float]] = {}

    async def get_file_list(path: str) -> dict[str, float]:
        """Get files and mtimes in a directory."""
        cmd = ["find", path, "-maxdepth", "3", "-printf", "%p|%T@\\n"]
        exit_code, stdout, _ = await _exec_in_container(container, cmd, timeout=30)

        if exit_code != 0:
            # Fallback to simpler command
            cmd = ["find", path, "-maxdepth", "3"]
            exit_code, stdout, _ = await _exec_in_container(container, cmd, timeout=30)
            if exit_code != 0:
                return {}
            # No mtime available, use 0
            return {
                line.strip(): 0 for line in stdout.strip().split("\n") if line.strip()
            }

        result = {}
        for line in stdout.strip().split("\n"):
            if "|" in line:
                file_path, mtime_str = line.rsplit("|", 1)
                try:
                    result[file_path.strip()] = float(mtime_str.strip())
                except ValueError:
                    result[file_path.strip()] = 0
        return result

    # Get initial state
    for path in paths:
        file_states[path] = await get_file_list(path)

    stop_event = asyncio.Event()

    async def poll_changes():
        """Poll for file changes."""
        while not stop_event.is_set():
            await asyncio.sleep(interval)

            for path in paths:
                try:
                    new_state = await get_file_list(path)
                    old_state = file_states.get(path, {})

                    # Find changes
                    old_files = set(old_state)
                    new_files = set(new_state)

                    # Created files
                    for f in new_files - old_files:
                        is_dir = f.endswith("/") or await _is_directory(container, f)
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": "CREATE",
                                "path": f,
                                "is_dir": is_dir,
                            }
                        )

                    # Deleted files
                    for f in old_files - new_files:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": "DELETE",
                                "path": f,
                                "is_dir": False,  # Can't know for deleted
                            }
                        )

                    # Modified files
                    for f in old_files & new_files:
                        if old_state[f] != new_state[f]:
                            is_dir = await _is_directory(container, f)
                            await websocket.send_json(
                                {
                                    "type": "change",
                                    "event": "MODIFY",
                                    "path": f,
                                    "is_dir": is_dir,
                                }
                            )

                    file_states[path] = new_state

                except Exception as e:
                    logger.warning(f"[FS Watch] Poll error for {path}: {e}")

    async def handle_websocket_input():
        """Handle incoming WebSocket messages."""
        try:
            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=1.0
                    )
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            stop_event.set()

    # Run both tasks
    try:
        poll_task = asyncio.create_task(poll_changes())
        ws_task = asyncio.create_task(handle_websocket_input())

        await asyncio.wait([poll_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()

    logger.info(f"[FS Watch] Stopped polling for task {task_id}")


async def _is_directory(container, path: str) -> bool:
    """Check if path is a directory."""
    try:
        exit_code, _, _ = await _exec_in_container(
            container, ["test", "-d", path], timeout=2
        )
        return exit_code == 0
    except Exception:
        return False
