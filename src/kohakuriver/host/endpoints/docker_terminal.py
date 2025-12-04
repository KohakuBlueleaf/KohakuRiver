"""WebSocket terminal endpoint for Docker containers on the Host."""

import asyncio
import json

import docker
from docker.errors import APIError as DockerAPIError
from docker.errors import NotFound as DockerNotFound
from fastapi import Path, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from kohakuriver.docker.naming import ENV_PREFIX
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


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


def _resolve_container_name(client: docker.DockerClient, env_name: str) -> str | None:
    """Resolve environment name to actual container name."""
    # Try prefixed name first
    prefixed_name = f"{ENV_PREFIX}-{env_name}"
    try:
        client.containers.get(prefixed_name)
        return prefixed_name
    except DockerNotFound:
        pass

    # Fallback: try the name as-is
    try:
        client.containers.get(env_name)
        return env_name
    except DockerNotFound:
        pass

    return None


async def _send_error_and_close(
    websocket: WebSocket, message: str, code: int = 1011
) -> None:
    """Send error message to websocket and close connection."""
    await websocket.send_json(
        WebSocketOutputMessage(type="error", data=message).model_dump()
    )
    await websocket.close(code=code)


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

        # Kill the entire process group (negative PID)
        # This ensures child processes (scripts running in shell) are also killed
        # First try SIGHUP to process group, then SIGKILL
        exit_code, _ = await asyncio.to_thread(
            container.exec_run, f"kill -1 -{exec_pid}", demux=False
        )
        if exit_code != 0:
            # Process group kill failed, try direct kill
            await asyncio.to_thread(
                container.exec_run, f"kill -1 {exec_pid}", demux=False
            )

        # Give processes a moment to handle SIGHUP
        await asyncio.sleep(0.1)

        # Force kill if still running
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


async def _close_websocket(websocket: WebSocket) -> None:
    """Close websocket safely."""
    try:
        await websocket.close(code=1000)
    except Exception:
        pass


# --- Main Endpoint ---


async def terminal_websocket_endpoint(
    websocket: WebSocket,
    container_name: str = Path(
        ..., description="Name of the Host container to connect to."
    ),
):
    """
    Handle WebSocket connection for interacting with a Host container's shell.
    """
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for container '{container_name}'")

    socket_stream = None
    exec_id = None
    client = None
    actual_container_name = None

    try:
        # Initialize Docker client
        try:
            client = docker.from_env(timeout=None)
            client.ping()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            await _send_error_and_close(websocket, f"Docker connection error: {e}")
            return

        # Resolve container name
        actual_container_name = _resolve_container_name(client, container_name)
        if not actual_container_name:
            logger.warning(f"Container '{container_name}' not found")
            await _send_error_and_close(
                websocket, f"Container '{container_name}' not found.", 1008
            )
            return

        # Get the container
        try:
            container = client.containers.get(actual_container_name)
            if container.status != "running":
                await _send_error_and_close(
                    websocket,
                    f"Container '{container_name}' is not running (status: {container.status}).",
                    1008,
                )
                return
        except DockerNotFound:
            logger.warning(f"Container '{actual_container_name}' not found")
            await _send_error_and_close(
                websocket, f"Container '{container_name}' not found.", 1008
            )
            return

        # Detect shell
        shell_cmd = await _detect_shell(container)
        if not shell_cmd:
            logger.error(
                f"No suitable shell found in container '{actual_container_name}'"
            )
            await _send_error_and_close(
                websocket, "No suitable shell found in container."
            )
            return

        # Create and start exec session
        logger.info(
            f"Creating exec with shell '{shell_cmd}' for container '{actual_container_name}'"
        )
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
        logger.info(
            f"Exec started, socket obtained for container '{actual_container_name}'"
        )

        # Handle initial resize
        await _handle_initial_resize(websocket, client, exec_id)

        # Send acknowledgment
        await websocket.send_json(
            WebSocketOutputMessage(type="output", data="").model_dump()
        )

        # Run I/O loop
        await _run_terminal_io(
            websocket, raw_socket, client, exec_id, actual_container_name, socket_stream
        )

    except asyncio.CancelledError:
        logger.info(f"Terminal session cancelled for container '{container_name}'")
        raise
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected cleanly for container '{container_name}'")
    except DockerAPIError as e:
        logger.error(f"Docker API error for container '{container_name}': {e}")
        try:
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Docker API Error: {e}\r\n"
                ).model_dump()
            )
        except Exception:
            pass
    except Exception as e:
        logger.exception(
            f"Unexpected error in terminal for container '{container_name}': {e}"
        )
        try:
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Unexpected Server Error: {e}\r\n"
                ).model_dump()
            )
        except Exception:
            pass
    finally:
        await _cleanup_terminal_session(
            client,
            exec_id,
            actual_container_name,
            socket_stream,
            websocket,
            container_name,
        )


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


async def _run_terminal_io(
    websocket: WebSocket,
    raw_socket,
    client: docker.DockerClient,
    exec_id: str,
    container_name: str,
    socket_stream,
) -> None:
    """Run the terminal I/O loop."""
    stop_output = asyncio.Event()

    async def handle_output():
        while not stop_output.is_set():
            try:
                output = await asyncio.to_thread(raw_socket.recv, 4096)
                if not output:
                    logger.info(f"Container socket closed for '{container_name}'")
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
                    logger.info(f"Container socket error for '{container_name}': {e}")
                break
            except Exception as e:
                if not stop_output.is_set():
                    logger.error(
                        f"Error reading from container '{container_name}': {e}"
                    )
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
                logger.info(f"WebSocket disconnected (input) for '{container_name}'")
                break
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from WebSocket for '{container_name}'")
            except Exception as e:
                logger.error(f"Error in input handler for '{container_name}': {e}")
                break

    input_task = asyncio.create_task(handle_input())
    output_task = asyncio.create_task(handle_output())

    _, pending = await asyncio.wait(
        [input_task, output_task], return_when=asyncio.FIRST_COMPLETED
    )

    # Signal stop and close socket before cancelling tasks
    stop_output.set()
    _close_socket_stream(socket_stream, f"container '{container_name}'")

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    logger.info(f"I/O tasks finished for container '{container_name}'")


async def _cleanup_terminal_session(
    client: docker.DockerClient | None,
    exec_id: str | None,
    actual_container_name: str | None,
    socket_stream,
    websocket: WebSocket,
    container_name: str,
) -> None:
    """Clean up terminal session resources."""
    logger.info(f"Cleaning up terminal session for container '{container_name}'")

    # Kill exec process to terminate any running scripts
    if exec_id and client and actual_container_name:
        await _kill_exec_process(
            client, exec_id, actual_container_name, f"container '{container_name}'"
        )

    _close_socket_stream(socket_stream, f"container '{container_name}'")
    await _close_websocket(websocket)
