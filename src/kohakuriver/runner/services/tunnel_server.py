"""
Tunnel server for the runner node.

Manages WebSocket tunnels from containers and handles port forward requests.
Each container maintains a single persistent WebSocket connection (tunnel),
through which multiple port forward connections are multiplexed.
"""

import asyncio

from fastapi import WebSocket, WebSocketDisconnect

from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.tunnel.protocol import (
    HEADER_SIZE,
    MSG_CLOSE,
    MSG_CONNECT,
    MSG_CONNECTED,
    MSG_DATA,
    MSG_ERROR,
    MSG_PING,
    MSG_PONG,
    PROTO_TCP,
    PROTO_UDP,
    build_message,
    get_payload,
    parse_header,
)
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# Module-level dependencies
_task_store: TaskStateStore | None = None

VM_CONTAINER_PREFIX = "vm-"


def set_dependencies(task_store: TaskStateStore):
    """Set module dependencies from app startup."""
    global _task_store
    _task_store = task_store


# =============================================================================
# Container Tunnel
# =============================================================================


class ContainerTunnel:
    """
    Manages a single tunnel connection to a container.

    Handles multiplexing of multiple port forward connections over one WebSocket.
    """

    def __init__(self, container_id: str, ws: WebSocket):
        """
        Initialize container tunnel.

        Args:
            container_id: Docker container ID or name
            ws: WebSocket connection from container's tunnel-client
        """
        self.container_id = container_id
        self.ws = ws
        self._next_client_id = 1
        self._lock = asyncio.Lock()

        # Map client_id -> user's WebSocket connection
        self._user_connections: dict[int, WebSocket] = {}

    async def allocate_client_id(self) -> int:
        """Allocate a unique client ID for a new connection."""
        async with self._lock:
            client_id = self._next_client_id
            self._next_client_id += 1
            return client_id

    async def register_user_connection(
        self, client_id: int, user_ws: WebSocket
    ) -> None:
        """Register a user's WebSocket for receiving data."""
        self._user_connections[client_id] = user_ws

    async def unregister_user_connection(self, client_id: int) -> None:
        """Unregister a user's WebSocket."""
        self._user_connections.pop(client_id, None)

    async def send_to_container(self, data: bytes) -> bool:
        """
        Send data to the container via tunnel.

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            await self.ws.send_bytes(data)
            return True
        except Exception as e:
            logger.error(f"[Tunnel {self.container_id}] Failed to send: {e}")
            return False

    async def handle_container_message(self, data: bytes) -> None:
        """
        Handle a message received from the container.

        Routes data to the appropriate user WebSocket based on client_id.
        """
        header = parse_header(data)
        if not header:
            logger.warning(
                f"[Tunnel {self.container_id}] Invalid message header (len={len(data)})"
            )
            return

        payload = get_payload(data)

        msg_type_names = {
            MSG_CONNECT: "CONNECT",
            MSG_CONNECTED: "CONNECTED",
            MSG_DATA: "DATA",
            MSG_CLOSE: "CLOSE",
            MSG_ERROR: "ERROR",
            MSG_PING: "PING",
            MSG_PONG: "PONG",
        }
        msg_name = msg_type_names.get(header.msg_type, f"UNKNOWN({header.msg_type})")
        logger.info(
            f"[Tunnel {self.container_id}] Container→Runner: {msg_name} "
            f"client_id={header.client_id} port={header.port} payload_len={len(payload)}"
        )

        # For messages that need to be forwarded to user, pass the full data (header + payload)
        if header.msg_type == MSG_CONNECTED:
            await self._on_connected(header, data)
        elif header.msg_type == MSG_DATA:
            await self._on_data(header, data)
        elif header.msg_type == MSG_CLOSE:
            await self._on_close(header, data)
        elif header.msg_type == MSG_ERROR:
            await self._on_error(header, data)
        elif header.msg_type == MSG_PONG:
            await self._on_pong(header, payload)
        else:
            logger.warning(
                f"[Tunnel {self.container_id}] Unknown message type: {header.msg_type}"
            )

    async def _on_connected(self, header, full_message: bytes) -> None:
        """Handle CONNECTED message - forward to user."""
        proto_name = "UDP" if header.proto == PROTO_UDP else "TCP"
        logger.info(
            f"[Tunnel {self.container_id}] Client {header.client_id} connected ({proto_name}), forwarding to user"
        )
        user_ws = self._user_connections.get(header.client_id)
        if user_ws:
            try:
                await user_ws.send_bytes(full_message)
            except Exception as e:
                logger.warning(
                    f"[Tunnel {self.container_id}] Failed to send CONNECTED to user: {e}"
                )

    async def _on_data(self, header, full_message: bytes) -> None:
        """Handle DATA message - forward full message to user WebSocket."""
        user_ws = self._user_connections.get(header.client_id)
        if not user_ws:
            logger.warning(
                f"[Tunnel {self.container_id}] No user connection for client_id={header.client_id}"
            )
            return
        try:
            payload_len = len(full_message) - HEADER_SIZE
            logger.info(
                f"[Tunnel {self.container_id}] Forwarding {payload_len} bytes to user for client_id={header.client_id}"
            )
            await user_ws.send_bytes(full_message)
        except Exception as e:
            logger.warning(
                f"[Tunnel {self.container_id}] Failed to send to user client_id={header.client_id}: {e}"
            )

    async def _on_close(self, header, full_message: bytes) -> None:
        """Handle CLOSE message - forward to user and clean up."""
        logger.info(
            f"[Tunnel {self.container_id}] Client {header.client_id} closed by container"
        )
        user_ws = self._user_connections.pop(header.client_id, None)
        if not user_ws:
            return
        try:
            # Forward the CLOSE message to user so they know connection ended
            await user_ws.send_bytes(full_message)
        except Exception:
            pass

    async def _on_error(self, header, full_message: bytes) -> None:
        """Handle ERROR message - forward to user and clean up."""
        payload = get_payload(full_message)
        error_msg = payload.decode("utf-8", errors="replace")
        logger.warning(
            f"[Tunnel {self.container_id}] Client {header.client_id} error: {error_msg}"
        )
        user_ws = self._user_connections.pop(header.client_id, None)
        if not user_ws:
            return
        try:
            # Forward the ERROR message to user
            await user_ws.send_bytes(full_message)
        except Exception:
            pass

    async def _on_pong(self, header, payload: bytes) -> None:
        """Handle PONG message - keepalive response, ignore."""
        pass


# =============================================================================
# Tunnel Server (Singleton)
# =============================================================================


class TunnelServer:
    """
    Manages all container tunnels on a runner node.

    Provides methods for:
    - Registering/unregistering container tunnels
    - Opening port forward connections through tunnels
    - Routing data between users and containers
    """

    def __init__(self):
        """Initialize tunnel server."""
        self._tunnels: dict[str, ContainerTunnel] = {}
        self._lock = asyncio.Lock()

    async def register_tunnel(
        self, container_id: str, ws: WebSocket
    ) -> ContainerTunnel:
        """
        Register a new container tunnel.

        Args:
            container_id: Container ID or name
            ws: WebSocket from container's tunnel-client

        Returns:
            The created ContainerTunnel instance
        """
        async with self._lock:
            # Close existing tunnel if any
            if container_id in self._tunnels:
                logger.warning(
                    f"[TunnelServer] Replacing existing tunnel for {container_id}"
                )

            tunnel = ContainerTunnel(container_id, ws)
            self._tunnels[container_id] = tunnel
            logger.info(f"[TunnelServer] Registered tunnel for {container_id}")
            return tunnel

    async def unregister_tunnel(self, container_id: str) -> None:
        """Unregister a container tunnel."""
        async with self._lock:
            if container_id in self._tunnels:
                del self._tunnels[container_id]
                logger.info(f"[TunnelServer] Unregistered tunnel for {container_id}")

    def get_tunnel(self, container_id: str) -> ContainerTunnel | None:
        """Get a tunnel by container ID."""
        return self._tunnels.get(container_id)

    def has_tunnel(self, container_id: str) -> bool:
        """Check if a tunnel exists for a container."""
        return container_id in self._tunnels


# Global tunnel server instance
tunnel_server = TunnelServer()


# =============================================================================
# WebSocket Handler for Container Tunnels
# =============================================================================


async def handle_container_tunnel(websocket: WebSocket, container_id: str) -> None:
    """
    Handle WebSocket connection from a container's tunnel-client.

    This is called when a container connects to /ws/tunnel/{container_id}.
    The connection is kept alive and messages are routed to user connections.

    Args:
        websocket: WebSocket connection from container
        container_id: Container ID or name
    """
    await websocket.accept()
    logger.info(f"[Tunnel] Container {container_id} connected")

    tunnel = await tunnel_server.register_tunnel(container_id, websocket)

    try:
        while True:
            data = await websocket.receive_bytes()
            await tunnel.handle_container_message(data)
    except WebSocketDisconnect:
        logger.info(f"[Tunnel] Container {container_id} disconnected")
    except Exception as e:
        logger.error(f"[Tunnel] Container {container_id} error: {e}")
    finally:
        await tunnel_server.unregister_tunnel(container_id)


# =============================================================================
# WebSocket Handler for Port Forward Requests
# =============================================================================


async def handle_port_forward(
    websocket: WebSocket,
    container_id: str,
    port: int,
    proto: int = PROTO_TCP,
) -> None:
    """
    Handle a port forward session from host/CLI.

    This maintains a single persistent WebSocket connection and handles
    multiplexed CONNECT/DATA/CLOSE messages for multiple local connections.

    Detects VM tasks (container_id starts with "vm-") and uses direct TCP
    instead of container tunnel.

    Args:
        websocket: Host's WebSocket connection
        container_id: Target container ID or name
        port: Target port in container (used for initial validation)
        proto: Protocol type (PROTO_TCP or PROTO_UDP)
    """
    # Check if this is a VM task
    if container_id.startswith(VM_CONTAINER_PREFIX):
        await _handle_vm_port_forward(websocket, container_id, port, proto)
        return

    await websocket.accept()

    proto_name = "UDP" if proto == PROTO_UDP else "TCP"
    logger.info(
        f"[Forward] New {proto_name} forward session: container={container_id}, port={port}"
    )

    # Get tunnel for this container
    tunnel = tunnel_server.get_tunnel(container_id)
    if not tunnel:
        error_msg = f"Container tunnel not connected (container={container_id})"
        logger.warning(f"[Forward] {error_msg}")
        await websocket.send_text(f"Error: {error_msg}")
        await websocket.close(code=1011)
        return

    logger.info(f"[Forward] Found tunnel for container={container_id}")

    # Track active client IDs for this session
    active_clients: set[int] = set()

    try:
        # Send CONNECTED to confirm tunnel is available
        await websocket.send_text("CONNECTED")
        logger.info(f"[Forward] Session established for {container_id}:{port}")

        # Message type names for logging
        msg_type_names = {
            MSG_CONNECT: "CONNECT",
            MSG_CONNECTED: "CONNECTED",
            MSG_DATA: "DATA",
            MSG_CLOSE: "CLOSE",
            MSG_ERROR: "ERROR",
        }

        # Handle multiplexed messages from host/CLI
        while True:
            data = await websocket.receive_bytes()

            header = parse_header(data)
            if not header:
                logger.warning(f"[Forward] Invalid message header (len={len(data)})")
                continue

            msg_type = header.msg_type
            client_id = header.client_id
            msg_port = header.port
            payload = get_payload(data)

            msg_name = msg_type_names.get(msg_type, f"UNKNOWN({msg_type})")
            logger.info(
                f"[Forward] Host→Runner: {msg_name} client_id={client_id} "
                f"port={msg_port} payload_len={len(payload)}"
            )

            if msg_type == MSG_CONNECT:
                # New connection request from CLI
                active_clients.add(client_id)
                logger.info(
                    f"[Forward] CONNECT client_id={client_id} -> port={msg_port}"
                )

                # Forward to container tunnel
                logger.info(f"[Forward] Sending CONNECT to container tunnel...")
                success = await tunnel.send_to_container(data)
                logger.info(f"[Forward] CONNECT send_to_container result: {success}")
                if not success:
                    logger.error(f"[Forward] Failed to send CONNECT to container")
                    error_msg = build_message(
                        MSG_ERROR, proto, client_id, 0, b"Tunnel send failed"
                    )
                    await websocket.send_bytes(error_msg)
                    active_clients.discard(client_id)
                else:
                    logger.info(
                        f"[Forward] CONNECT sent to container, registering user connection"
                    )

                # Register this websocket to receive responses for this client_id
                await tunnel.register_user_connection(client_id, websocket)

            elif msg_type == MSG_DATA:
                # Data from CLI to container
                if client_id not in active_clients:
                    logger.warning(f"[Forward] DATA for unknown client_id={client_id}")
                    continue

                logger.info(
                    f"[Forward] Forwarding {len(payload)} bytes to container tunnel for client_id={client_id}"
                )
                success = await tunnel.send_to_container(data)
                logger.info(f"[Forward] send_to_container result: {success}")
                if not success:
                    logger.warning(
                        f"[Forward] Failed to send DATA for client_id={client_id}"
                    )

            elif msg_type == MSG_CLOSE:
                # Close request from CLI
                logger.info(f"[Forward] CLOSE client_id={client_id}")
                active_clients.discard(client_id)
                await tunnel.unregister_user_connection(client_id)
                await tunnel.send_to_container(data)

            else:
                # Forward unknown message types
                logger.debug(f"[Forward] Forwarding unknown message type {msg_type}")
                await tunnel.send_to_container(data)

    except WebSocketDisconnect:
        logger.info(f"[Forward] Host disconnected (container={container_id})")
    except Exception as e:
        logger.error(f"[Forward] Error: {e}")
    finally:
        # Clean up all active connections
        for client_id in active_clients:
            close_msg = build_message(MSG_CLOSE, proto, client_id)
            await tunnel.send_to_container(close_msg)
            await tunnel.unregister_user_connection(client_id)

        logger.info(f"[Forward] Session closed (container={container_id})")


# =============================================================================
# VM Port Forward Handler
# =============================================================================


async def _handle_vm_port_forward(
    websocket: WebSocket,
    container_id: str,
    port: int,
    proto: int = PROTO_TCP,
) -> None:
    """
    Handle port forwarding for a VM via direct TCP.

    Instead of using a tunnel-client inside the VM, the runner opens direct
    TCP connections to vm_ip:port and bridges them with the binary WebSocket
    protocol from the host.

    Each MSG_CONNECT opens a new TCP connection to the VM.
    MSG_DATA forwards data bidirectionally.
    MSG_CLOSE closes the TCP connection.
    """
    await websocket.accept()

    proto_name = "UDP" if proto == PROTO_UDP else "TCP"

    # Extract task_id from container_id (format: "vm-{task_id}")
    try:
        task_id = int(container_id[len(VM_CONTAINER_PREFIX) :])
    except (ValueError, IndexError):
        logger.warning(f"[VM Forward] Invalid VM container_id: {container_id}")
        await websocket.send_text(f"Error: Invalid VM identifier: {container_id}")
        await websocket.close(code=1011)
        return

    # Get VM IP from task store
    if not _task_store:
        await websocket.send_text("Error: Task store not available")
        await websocket.close(code=1011)
        return

    task_data = _task_store.get_task(task_id)
    if not task_data:
        await websocket.send_text(f"Error: VM {task_id} not found")
        await websocket.close(code=1011)
        return

    vm_ip = task_data.get("vm_ip")
    if not vm_ip:
        await websocket.send_text(f"Error: VM {task_id} has no IP address")
        await websocket.close(code=1011)
        return

    logger.info(
        f"[VM Forward] New {proto_name} forward session: VM {task_id} ({vm_ip}), port={port}"
    )

    # Track active TCP connections: client_id -> (reader, writer, read_task)
    active_connections: dict[
        int, tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.Task]
    ] = {}
    stop_event = asyncio.Event()

    async def _forward_vm_to_ws(
        client_id: int,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """Read from VM TCP and send to WebSocket as MSG_DATA."""
        try:
            while not stop_event.is_set():
                data = await reader.read(65536)
                if not data:
                    # TCP connection closed by VM
                    logger.debug(
                        f"[VM Forward] VM closed TCP for client_id={client_id}"
                    )
                    close_msg = build_message(MSG_CLOSE, proto, client_id, 0)
                    try:
                        await websocket.send_bytes(close_msg)
                    except Exception:
                        pass
                    break

                msg = build_message(MSG_DATA, proto, client_id, 0, data)
                await websocket.send_bytes(msg)
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        except Exception as e:
            if not stop_event.is_set():
                logger.debug(f"[VM Forward] Read error client_id={client_id}: {e}")
                error_msg = build_message(
                    MSG_ERROR, proto, client_id, 0, str(e).encode()
                )
                try:
                    await websocket.send_bytes(error_msg)
                except Exception:
                    pass
        finally:
            # Clean up connection
            try:
                writer.close()
            except Exception:
                pass
            active_connections.pop(client_id, None)

    try:
        # Send CONNECTED to confirm VM is available
        await websocket.send_text("CONNECTED")
        logger.info(f"[VM Forward] Session established for VM {task_id}:{port}")

        while True:
            data = await websocket.receive_bytes()

            header = parse_header(data)
            if not header:
                logger.warning(f"[VM Forward] Invalid message header (len={len(data)})")
                continue

            msg_type = header.msg_type
            client_id = header.client_id
            msg_port = header.port or port
            payload = get_payload(data)

            if msg_type == MSG_CONNECT:
                # Open direct TCP connection to VM
                logger.info(
                    f"[VM Forward] CONNECT client_id={client_id} -> {vm_ip}:{msg_port}"
                )
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(vm_ip, msg_port),
                        timeout=10.0,
                    )
                except Exception as e:
                    logger.warning(
                        f"[VM Forward] TCP connect failed for client_id={client_id}: {e}"
                    )
                    error_msg = build_message(
                        MSG_ERROR,
                        proto,
                        client_id,
                        msg_port,
                        f"Connection failed: {e}".encode(),
                    )
                    await websocket.send_bytes(error_msg)
                    continue

                # Start reading from VM in background
                read_task = asyncio.create_task(
                    _forward_vm_to_ws(client_id, reader, writer)
                )
                active_connections[client_id] = (reader, writer, read_task)

                # Send CONNECTED back
                connected_msg = build_message(MSG_CONNECTED, proto, client_id, msg_port)
                await websocket.send_bytes(connected_msg)
                logger.info(f"[VM Forward] TCP connected for client_id={client_id}")

            elif msg_type == MSG_DATA:
                # Forward data to VM TCP connection
                conn = active_connections.get(client_id)
                if not conn:
                    logger.warning(
                        f"[VM Forward] DATA for unknown client_id={client_id}"
                    )
                    continue

                _, writer, _ = conn
                try:
                    writer.write(payload)
                    await writer.drain()
                except Exception as e:
                    logger.warning(
                        f"[VM Forward] TCP write failed client_id={client_id}: {e}"
                    )

            elif msg_type == MSG_CLOSE:
                # Close TCP connection
                logger.info(f"[VM Forward] CLOSE client_id={client_id}")
                conn = active_connections.pop(client_id, None)
                if conn:
                    _, writer, read_task = conn
                    read_task.cancel()
                    try:
                        writer.close()
                    except Exception:
                        pass

    except WebSocketDisconnect:
        logger.info(f"[VM Forward] Host disconnected (VM {task_id})")
    except Exception as e:
        logger.error(f"[VM Forward] Error: {e}")
    finally:
        # Clean up all TCP connections
        stop_event.set()
        for client_id, (_, writer, read_task) in active_connections.items():
            read_task.cancel()
            try:
                writer.close()
            except Exception:
                pass
        active_connections.clear()

        logger.info(f"[VM Forward] Session closed (VM {task_id})")
