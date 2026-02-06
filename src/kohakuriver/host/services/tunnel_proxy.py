"""
Tunnel proxy service for the host.

Proxies port forward requests from users to the appropriate runner node.
Uses a single persistent WebSocket connection per task, multiplexing
multiple user connections over it using client_id.

Architecture:
    CLI (single WS) ←→ Host (single WS) ←→ Runner ←→ Container tunnel-client
"""

import asyncio
import struct
from urllib.parse import urlparse

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.docker.naming import task_container_name, vps_container_name
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# Protocol header format
HEADER_FORMAT = ">BBIH"
HEADER_SIZE = 8

# Message types
MSG_CONNECT = 0x01
MSG_CONNECTED = 0x02
MSG_DATA = 0x03
MSG_CLOSE = 0x04
MSG_ERROR = 0x05

# Protocol types
PROTO_TCP = 0x00
PROTO_UDP = 0x01


def build_message(
    msg_type: int, proto: int, client_id: int, port: int = 0, payload: bytes = b""
) -> bytes:
    """Build a tunnel protocol message."""
    header = struct.pack(HEADER_FORMAT, msg_type, proto, client_id, port)
    return header + payload


def parse_header(data: bytes) -> tuple[int, int, int, int] | None:
    """Parse header. Returns (msg_type, proto, client_id, port) or None."""
    if len(data) < HEADER_SIZE:
        return None
    return struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])


def get_payload(data: bytes) -> bytes:
    """Extract payload from message."""
    return data[HEADER_SIZE:] if len(data) > HEADER_SIZE else b""


async def get_task_runner_info(
    task_id: int,
) -> tuple[Task | None, Node | None, str | None]:
    """
    Look up task and its runner node.

    Returns:
        Tuple of (task, node, error_message). If error_message is not None,
        task and node will be None.
    """
    task = await asyncio.to_thread(Task.get_or_none, Task.task_id == task_id)

    if not task:
        return None, None, f"Task {task_id} not found"

    if task.status != "running":
        return None, None, f"Task is not running (status: {task.status})"

    if not task.assigned_node:
        return None, None, f"Task {task_id} has no assigned node"

    node = await asyncio.to_thread(
        Node.get_or_none, Node.hostname == task.assigned_node
    )

    if not node:
        return None, None, f"Runner node '{task.assigned_node}' not found"

    if node.status != "online":
        return None, None, f"Runner node '{task.assigned_node}' is offline"

    return task, node, None


async def forward_port_proxy(
    websocket: WebSocket,
    task_id: int,
    port: int,
    proto: int = PROTO_TCP,
) -> None:
    """
    Proxy a port forward session from CLI to runner.

    This maintains a single persistent WebSocket to the runner and
    forwards all multiplexed messages bidirectionally.
    """
    await websocket.accept()

    proto_name = "UDP" if proto == PROTO_UDP else "TCP"
    logger.info(
        f"[ForwardProxy] New {proto_name} forward session: task={task_id}, port={port}"
    )

    runner_ws = None

    try:
        # 1. Look up task and runner
        task, node, error = await get_task_runner_info(task_id)

        if error:
            logger.warning(f"[ForwardProxy] {error}")
            await websocket.send_text(f"Error: {error}")
            await websocket.close(code=1008)
            return

        # 2. Get container name
        if task.task_type == "vps":
            if getattr(task, "vps_backend", "docker") == "qemu":
                container_name = f"vm-{task_id}"
            else:
                container_name = vps_container_name(task_id)
        else:
            container_name = task_container_name(task_id)

        # 3. Build runner WebSocket URL
        parsed = urlparse(node.url)
        proto_param = "udp" if proto == PROTO_UDP else "tcp"
        runner_ws_url = f"ws://{parsed.netloc}/ws/forward/{container_name}/{port}?proto={proto_param}"

        logger.info(
            f"[ForwardProxy] Task {task_id} on node '{node.hostname}', "
            f"container={container_name}"
        )
        logger.info(f"[ForwardProxy] Connecting to runner: {runner_ws_url}")

        # 4. Connect to runner
        try:
            runner_ws = await websockets.connect(runner_ws_url)
        except Exception as e:
            logger.error(f"[ForwardProxy] Failed to connect to runner: {e}")
            await websocket.send_text(f"Error: Failed to connect to runner: {e}")
            await websocket.close(code=1011)
            return

        logger.debug(f"[ForwardProxy] Connected to runner WebSocket")

        # 5. Wait for CONNECTED signal from runner
        try:
            first_msg = await asyncio.wait_for(runner_ws.recv(), timeout=10.0)
            if isinstance(first_msg, str):
                if first_msg == "CONNECTED":
                    logger.info(
                        f"[ForwardProxy] Tunnel established for task {task_id}:{port}"
                    )
                    await websocket.send_text("CONNECTED")
                elif first_msg.startswith("Error:"):
                    logger.error(f"[ForwardProxy] Runner error: {first_msg}")
                    await websocket.send_text(first_msg)
                    await websocket.close(code=1011)
                    return
                else:
                    logger.warning(f"[ForwardProxy] Unexpected: {first_msg}")
                    await websocket.send_text(first_msg)
            else:
                logger.warning(f"[ForwardProxy] Binary before CONNECTED")
                await websocket.send_bytes(first_msg)
        except asyncio.TimeoutError:
            logger.error(f"[ForwardProxy] Timeout waiting for runner CONNECTED")
            await websocket.send_text("Error: Timeout connecting to container tunnel")
            await websocket.close(code=1011)
            return

        # 6. Bidirectional proxy - just forward everything
        async def cli_to_runner():
            """Forward messages from CLI to runner."""
            try:
                while True:
                    # CLI sends binary protocol messages
                    data = await websocket.receive_bytes()
                    header = parse_header(data)
                    if header:
                        msg_type, proto, client_id, port = header
                        msg_names = {
                            MSG_CONNECT: "CONNECT",
                            MSG_DATA: "DATA",
                            MSG_CLOSE: "CLOSE",
                        }
                        msg_name = msg_names.get(msg_type, f"TYPE_{msg_type}")
                        payload_len = len(data) - HEADER_SIZE
                        logger.info(
                            f"[ForwardProxy] CLI→Runner: {msg_name} client_id={client_id} payload={payload_len}b"
                        )
                    await runner_ws.send(data)
            except WebSocketDisconnect:
                logger.debug(f"[ForwardProxy] CLI disconnected (task={task_id})")
            except Exception as e:
                logger.debug(f"[ForwardProxy] CLI→Runner error: {e}")

        async def runner_to_cli():
            """Forward messages from runner to CLI."""
            try:
                async for msg in runner_ws:
                    if isinstance(msg, bytes):
                        header = parse_header(msg)
                        if header:
                            msg_type, proto, client_id, port = header
                            msg_names = {
                                MSG_CONNECT: "CONNECT",
                                MSG_CONNECTED: "CONNECTED",
                                MSG_DATA: "DATA",
                                MSG_CLOSE: "CLOSE",
                                MSG_ERROR: "ERROR",
                            }
                            msg_name = msg_names.get(msg_type, f"TYPE_{msg_type}")
                            payload_len = len(msg) - HEADER_SIZE
                            logger.info(
                                f"[ForwardProxy] Runner→CLI: {msg_name} client_id={client_id} payload={payload_len}b"
                            )
                        await websocket.send_bytes(msg)
                    else:
                        logger.info(f"[ForwardProxy] Runner→CLI: text={msg}")
                        await websocket.send_text(msg)
            except websockets.exceptions.ConnectionClosed:
                logger.debug(f"[ForwardProxy] Runner closed (task={task_id})")
            except Exception as e:
                logger.debug(f"[ForwardProxy] Runner→CLI error: {e}")

        # Run both directions
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(cli_to_runner()),
                asyncio.create_task(runner_to_cli()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        logger.info(f"[ForwardProxy] Session ended (task={task_id}:{port})")

    except WebSocketDisconnect:
        logger.info(f"[ForwardProxy] CLI disconnected cleanly (task={task_id})")
    except Exception as e:
        logger.exception(f"[ForwardProxy] Unexpected error: {e}")
        try:
            await websocket.send_text(f"Error: {e}")
        except Exception:
            pass
    finally:
        if runner_ws:
            try:
                await runner_ws.close()
            except Exception:
                pass

        try:
            await websocket.close(code=1000)
        except Exception:
            pass

        logger.debug(f"[ForwardProxy] Cleanup complete (task={task_id}:{port})")
