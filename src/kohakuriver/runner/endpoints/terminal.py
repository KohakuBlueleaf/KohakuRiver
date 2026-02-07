"""WebSocket terminal endpoint for task/VPS containers and VMs on the Runner."""

import asyncio
import json

import docker
from docker.errors import APIError as DockerAPIError
from docker.errors import NotFound as DockerNotFound
from fastapi import Path, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from kohakuriver.runner.services.vm_ssh import ssh_connect
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# Module-level dependencies (set by app on startup)
_task_store: TaskStateStore | None = None

VM_CONTAINER_PREFIX = "vm-"


def set_dependencies(task_store: TaskStateStore):
    """Set module dependencies from app startup."""
    global _task_store
    _task_store = task_store


# --- WebSocket Message Models ---


class WebSocketInputMessage(BaseModel):
    """Model for messages received FROM the client over WebSocket."""

    type: str  # "input" or "resize"
    data: str | None = None  # Terminal input
    rows: int | None = None  # For resize
    cols: int | None = None  # For resize


class WebSocketOutputMessage(BaseModel):
    """Model for messages sent TO the client over WebSocket."""

    type: str  # "output" or "error"
    data: str


# --- Helper Functions ---


def _resolve_task_data(task_id: int) -> dict | None:
    """Resolve task_id to task data from task_store."""
    if not _task_store:
        return None
    return _task_store.get_task(task_id)


def _is_vm_task(task_data: dict) -> bool:
    """Check if task is a VM (not Docker)."""
    container_name = task_data.get("container_name", "")
    return container_name.startswith(VM_CONTAINER_PREFIX)


def _get_vm_ip(task_data: dict) -> str | None:
    """Get VM IP from task data."""
    return task_data.get("vm_ip")


async def _send_error_and_close(
    websocket: WebSocket, message: str, code: int = 1011
) -> None:
    """Send error message to websocket and close connection."""
    await websocket.send_json(
        WebSocketOutputMessage(type="error", data=message).model_dump()
    )
    await websocket.close(code=code)


async def _close_websocket(websocket: WebSocket) -> None:
    """Close websocket safely."""
    try:
        await websocket.close(code=1000)
    except Exception:
        pass


# =============================================================================
# Main Endpoint (dispatches to Docker or VM handler)
# =============================================================================


async def task_terminal_websocket_endpoint(
    websocket: WebSocket,
    task_id: int = Path(..., description="Task or VPS ID to connect to."),
):
    """
    Handle WebSocket connection for interacting with a task/VPS shell.

    Detects whether the task is Docker-based or VM-based and dispatches
    to the appropriate handler.
    """
    await websocket.accept()
    logger.info(f"WebSocket terminal connection accepted for task {task_id}")

    task_data = _resolve_task_data(task_id)
    if not task_data:
        logger.warning(f"Task {task_id} not found on this runner")
        await _send_error_and_close(
            websocket, f"Task {task_id} not found on this runner.", 1008
        )
        return

    if _is_vm_task(task_data):
        vm_ip = _get_vm_ip(task_data)
        if not vm_ip:
            await _send_error_and_close(
                websocket, f"VM {task_id} has no IP address.", 1008
            )
            return
        await _handle_vm_terminal(websocket, task_id, vm_ip)
    else:
        container_name = task_data.get("container_name")
        if not container_name:
            await _send_error_and_close(
                websocket, f"Task {task_id} has no container.", 1008
            )
            return
        await _handle_docker_terminal(websocket, task_id, container_name)


# =============================================================================
# VM Terminal (SSH-based)
# =============================================================================


async def _handle_vm_terminal(websocket: WebSocket, task_id: int, vm_ip: str) -> None:
    """Handle terminal for VM via SSH using asyncssh."""
    conn = None
    process = None

    try:
        logger.info(f"Opening SSH terminal to VM {task_id} at {vm_ip}")
        try:
            conn = await ssh_connect(vm_ip, timeout=15.0)
        except Exception as e:
            logger.error(f"SSH connection failed for VM {task_id}: {e}")
            await _send_error_and_close(websocket, f"SSH connection failed: {e}")
            return

        # Handle initial resize to get terminal size
        term_width, term_height = 80, 24
        try:
            initial_msg = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            initial_data = json.loads(initial_msg)
            if initial_data.get("type") == "resize":
                term_width = initial_data.get("cols", 80)
                term_height = initial_data.get("rows", 24)
        except (asyncio.TimeoutError, Exception):
            pass

        # Open interactive shell session
        process = await conn.create_process(
            term_type="xterm-256color",
            term_size=(term_width, term_height),
        )

        # Send acknowledgment
        await websocket.send_json(
            WebSocketOutputMessage(type="output", data="").model_dump()
        )

        # Run I/O loop
        await _run_vm_terminal_io(websocket, process, task_id)

    except asyncio.CancelledError:
        logger.info(f"VM terminal session cancelled for task {task_id}")
        raise
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected cleanly for VM {task_id}")
    except Exception as e:
        logger.exception(f"Unexpected error in VM terminal for task {task_id}: {e}")
        try:
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Error: {e}\r\n"
                ).model_dump()
            )
        except Exception:
            pass
    finally:
        logger.info(f"Cleaning up VM terminal session for task {task_id}")
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
        await _close_websocket(websocket)


async def _run_vm_terminal_io(
    websocket: WebSocket,
    process,
    task_id: int,
) -> None:
    """Run the VM terminal I/O loop via SSH process."""
    stop_event = asyncio.Event()

    async def handle_output():
        """Read from SSH process stdout and send to WebSocket."""
        try:
            while not stop_event.is_set():
                data = await process.stdout.read(4096)
                if not data:
                    logger.info(f"SSH session closed for VM {task_id}")
                    break
                await websocket.send_json(
                    WebSocketOutputMessage(type="output", data=data).model_dump()
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not stop_event.is_set():
                logger.info(f"SSH output error for VM {task_id}: {e}")

    async def handle_input():
        """Read from WebSocket and write to SSH process stdin."""
        try:
            while not stop_event.is_set():
                message_text = await websocket.receive_text()
                message_data = json.loads(message_text)
                msg = WebSocketInputMessage(**message_data)

                if msg.type == "input" and msg.data:
                    process.stdin.write(msg.data)
                elif msg.type == "resize" and msg.rows and msg.cols:
                    try:
                        process.change_terminal_size(msg.cols, msg.rows)
                    except Exception as e:
                        logger.debug(f"Failed to resize VM terminal: {e}")

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected (input) for VM {task_id}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not stop_event.is_set():
                logger.error(f"Error in VM input handler for task {task_id}: {e}")

    input_task = asyncio.create_task(handle_input())
    output_task = asyncio.create_task(handle_output())

    _, pending = await asyncio.wait(
        [input_task, output_task], return_when=asyncio.FIRST_COMPLETED
    )

    stop_event.set()
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    logger.info(f"VM terminal I/O finished for task {task_id}")


# =============================================================================
# Docker Terminal (existing docker exec-based approach)
# =============================================================================


async def _detect_shell(container) -> str | None:
    """Detect available shell in container. Returns shell path or None."""
    for shell in ["/bin/bash", "/bin/sh"]:
        try:
            exit_code, _ = container.exec_run(
                cmd=f"which {shell}", demux=False, stream=False
            )
            if exit_code == 0:
                return shell
        except DockerAPIError:
            continue
    return None


async def _kill_exec_process(
    client: docker.DockerClient,
    exec_id: str,
    container_name: str,
    identifier: str,
) -> None:
    """Kill exec process and all children on disconnect."""
    try:
        exec_info = await asyncio.to_thread(client.api.exec_inspect, exec_id)
        exec_pid = exec_info.get("Pid", 0)
        exec_running = exec_info.get("Running", False)

        if not exec_running:
            logger.debug(f"Exec process already stopped for {identifier}")
            return

        if exec_pid <= 0:
            logger.debug(f"No valid PID for exec process {identifier}")
            return

        logger.debug(
            f"Killing exec process (PID {exec_pid}) and children for {identifier}"
        )
        container = client.containers.get(container_name)

        exit_code, _ = await asyncio.to_thread(
            container.exec_run, f"kill -1 -{exec_pid}", demux=False
        )
        if exit_code != 0:
            await asyncio.to_thread(
                container.exec_run, f"kill -1 {exec_pid}", demux=False
            )

        await asyncio.sleep(0.1)

        await asyncio.to_thread(
            container.exec_run,
            f"kill -9 -{exec_pid} 2>/dev/null || kill -9 {exec_pid} 2>/dev/null || true",
            demux=False,
        )

        logger.info(f"Terminated exec process (PID {exec_pid}) for {identifier}")

    except DockerNotFound:
        logger.debug(f"Container not found when killing exec for {identifier}")
    except Exception as e:
        logger.debug(f"Could not kill exec process for {identifier}: {e}")


def _close_socket_stream(socket_stream, identifier: str) -> None:
    """Close socket stream safely."""
    if not socket_stream:
        return
    if not hasattr(socket_stream, "_sock") or not socket_stream._sock:
        return
    try:
        socket_stream._sock.close()
        logger.debug(f"Closed Docker exec socket for {identifier}.")
    except Exception as e:
        logger.warning(f"Error closing Docker exec socket for {identifier}: {e}")


async def _handle_docker_terminal(
    websocket: WebSocket, task_id: int, container_name: str
) -> None:
    """Handle terminal for Docker container via docker exec."""
    socket_stream = None
    exec_id = None
    client = None

    try:
        # Initialize Docker client
        try:
            client = docker.from_env(timeout=None)
            client.ping()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            await _send_error_and_close(websocket, f"Docker connection error: {e}")
            return

        # Get the container
        try:
            container = client.containers.get(container_name)
            if container.status != "running":
                await _send_error_and_close(
                    websocket,
                    f"Container is not running (status: {container.status}).",
                    1008,
                )
                return
        except DockerNotFound:
            logger.warning(f"Container '{container_name}' not found")
            await _send_error_and_close(websocket, "Container not found.", 1008)
            return

        # Detect shell
        shell_cmd = await _detect_shell(container)
        if not shell_cmd:
            logger.error("No suitable shell found in container")
            await _send_error_and_close(websocket, "No suitable shell found.")
            return

        # Create and start exec session
        logger.info(f"Creating exec with shell '{shell_cmd}' for task {task_id}")
        exec_instance = client.api.exec_create(
            container.id,
            cmd=shell_cmd,
            stdin=True,
            stdout=True,
            stderr=True,
            tty=True,
        )
        exec_id = exec_instance["Id"]

        socket_stream = client.api.exec_start(
            exec_id, socket=True, stream=True, tty=True, demux=False
        )
        if not hasattr(socket_stream, "_sock") or not socket_stream._sock:
            raise RuntimeError("Failed to get raw socket from exec_start")

        raw_socket = socket_stream._sock
        raw_socket.settimeout(1.0)
        logger.info(f"Exec started, socket obtained for task {task_id}")

        # Handle initial resize
        await _handle_initial_resize(websocket, client, exec_id)

        # Send acknowledgment
        await websocket.send_json(
            WebSocketOutputMessage(type="output", data="").model_dump()
        )

        # Run I/O loop
        await _run_docker_terminal_io(
            websocket, raw_socket, client, exec_id, task_id, socket_stream
        )

    except asyncio.CancelledError:
        logger.info(f"Terminal session cancelled for task {task_id}")
        raise
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected cleanly for task {task_id}")
    except DockerAPIError as e:
        logger.error(f"Docker API error for task {task_id}: {e}")
        try:
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Docker API Error: {e}\r\n"
                ).model_dump()
            )
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"Unexpected error in terminal for task {task_id}: {e}")
        try:
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Unexpected Server Error: {e}\r\n"
                ).model_dump()
            )
        except Exception:
            pass
    finally:
        logger.info(f"Cleaning up terminal session for task {task_id}")
        if exec_id and client and container_name:
            await _kill_exec_process(client, exec_id, container_name, f"task {task_id}")
        _close_socket_stream(socket_stream, f"task {task_id}")
        await _close_websocket(websocket)


async def _handle_initial_resize(
    websocket: WebSocket, client: docker.DockerClient, exec_id: str
) -> None:
    """Wait for initial resize message and apply it."""
    try:
        initial_msg = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
        initial_data = json.loads(initial_msg)
        if initial_data.get("type") == "resize":
            rows = initial_data.get("rows")
            cols = initial_data.get("cols")
            if rows and cols:
                await asyncio.to_thread(
                    client.api.exec_resize, exec_id, height=rows, width=cols
                )
                logger.debug(f"Initial terminal resize to {rows}x{cols}")
    except asyncio.TimeoutError:
        logger.debug("No initial resize message received")
    except Exception as e:
        logger.debug(f"Error processing initial resize: {e}")


async def _run_docker_terminal_io(
    websocket: WebSocket,
    raw_socket,
    client: docker.DockerClient,
    exec_id: str,
    task_id: int,
    socket_stream,
) -> None:
    """Run the Docker terminal I/O loop."""
    stop_output = asyncio.Event()

    async def handle_output():
        while not stop_output.is_set():
            try:
                output = await asyncio.to_thread(raw_socket.recv, 4096)
                if not output:
                    logger.info(f"Container socket closed for task {task_id}")
                    break
                await websocket.send_json(
                    WebSocketOutputMessage(
                        type="output", data=output.decode("utf-8", errors="replace")
                    ).model_dump()
                )
            except TimeoutError:
                continue
            except OSError as e:
                if not stop_output.is_set():
                    logger.info(f"Container socket error for task {task_id}: {e}")
                break
            except Exception as e:
                if not stop_output.is_set():
                    logger.error(f"Error reading from container {task_id}: {e}")
                break

    async def handle_input():
        while True:
            try:
                message_text = await websocket.receive_text()
                message_data = json.loads(message_text)
                input_msg = WebSocketInputMessage(**message_data)

                if input_msg.type == "input" and input_msg.data:
                    await asyncio.to_thread(
                        raw_socket.sendall, input_msg.data.encode("utf-8")
                    )
                elif input_msg.type == "resize" and input_msg.rows and input_msg.cols:
                    try:
                        await asyncio.to_thread(
                            client.api.exec_resize,
                            exec_id,
                            height=input_msg.rows,
                            width=input_msg.cols,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to resize terminal: {e}")

            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected (input) for task {task_id}")
                break
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from WebSocket for task {task_id}")
            except Exception as e:
                logger.error(f"Error in input handler for task {task_id}: {e}")
                break

    input_task = asyncio.create_task(handle_input())
    output_task = asyncio.create_task(handle_output())

    _, pending = await asyncio.wait(
        [input_task, output_task], return_when=asyncio.FIRST_COMPLETED
    )

    stop_output.set()
    _close_socket_stream(socket_stream, f"task {task_id}")

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    logger.info(f"I/O tasks finished for task {task_id}")
