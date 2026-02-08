"""
Tunnel server for the runner node.

Manages WebSocket tunnels from containers and handles port forward requests.
Each container maintains a single persistent WebSocket connection (tunnel),
through which multiple port forward connections are multiplexed.
"""

import asyncio

from fastapi import WebSocket, WebSocketDisconnect

from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.tunnel import protocol as proto_mod
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
        match header.msg_type:
            case proto_mod.MSG_CONNECTED:
                await self._on_connected(header, data)
            case proto_mod.MSG_DATA:
                await self._on_data(header, data)
            case proto_mod.MSG_CLOSE:
                await self._on_close(header, data)
            case proto_mod.MSG_ERROR:
                await self._on_error(header, data)
            case proto_mod.MSG_PONG:
                await self._on_pong(header, payload)
            case _:
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


async def _handle_pf_message(
    msg_type: int,
    header,
    payload: bytes,
    data: bytes,
    tunnel: ContainerTunnel,
    websocket: WebSocket,
    active_clients: set[int],
    proto: int,
) -> None:
    """
    Handle a single multiplexed message in a port forward session.

    Dispatches MSG_CONNECT, MSG_DATA, MSG_CLOSE, and unknown message types
    to the appropriate handler logic.

    Args:
        msg_type: The parsed message type
        header: The parsed message header
        payload: The message payload (data after header)
        data: The full raw message (header + payload)
        tunnel: The container tunnel to forward messages through
        websocket: The host/CLI WebSocket connection
        active_clients: Set of active client IDs for this session
        proto: Protocol type (PROTO_TCP or PROTO_UDP)
    """
    client_id = header.client_id
    msg_port = header.port

    match msg_type:
        case proto_mod.MSG_CONNECT:
            # New connection request from CLI
            active_clients.add(client_id)
            logger.info(f"[Forward] CONNECT client_id={client_id} -> port={msg_port}")

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

        case proto_mod.MSG_DATA:
            # Data from CLI to container
            if client_id not in active_clients:
                logger.warning(f"[Forward] DATA for unknown client_id={client_id}")
                return

            logger.info(
                f"[Forward] Forwarding {len(payload)} bytes to container tunnel for client_id={client_id}"
            )
            success = await tunnel.send_to_container(data)
            logger.info(f"[Forward] send_to_container result: {success}")
            if not success:
                logger.warning(
                    f"[Forward] Failed to send DATA for client_id={client_id}"
                )

        case proto_mod.MSG_CLOSE:
            # Close request from CLI
            logger.info(f"[Forward] CLOSE client_id={client_id}")
            active_clients.discard(client_id)
            await tunnel.unregister_user_connection(client_id)
            await tunnel.send_to_container(data)

        case _:
            # Forward unknown message types
            logger.debug(f"[Forward] Forwarding unknown message type {msg_type}")
            await tunnel.send_to_container(data)


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
            payload = get_payload(data)

            msg_name = msg_type_names.get(msg_type, f"UNKNOWN({msg_type})")
            logger.info(
                f"[Forward] Host→Runner: {msg_name} client_id={header.client_id} "
                f"port={header.port} payload_len={len(payload)}"
            )

            await _handle_pf_message(
                msg_type,
                header,
                payload,
                data,
                tunnel,
                websocket,
                active_clients,
                proto,
            )

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
# VM Port Forward Helpers
# =============================================================================


def _resolve_vm_target(
    container_id: str, task_store: TaskStateStore
) -> tuple[int, str] | None:
    """
    Resolve a VM container_id to its task_id and IP address.

    Parses the task_id from the container_id (format: "vm-{task_id}"),
    looks up the task in the store, and validates it has a VM IP.

    Args:
        container_id: Container identifier (e.g. "vm-123")
        task_store: The task state store to look up the task

    Returns:
        A tuple of (task_id, vm_ip) on success, or None on any failure.
    """
    # Extract task_id from container_id (format: "vm-{task_id}")
    try:
        task_id = int(container_id[len(VM_CONTAINER_PREFIX) :])
    except (ValueError, IndexError):
        logger.warning(f"[VM Forward] Invalid VM container_id: {container_id}")
        return None

    task_data = task_store.get_task(task_id)
    if not task_data:
        logger.warning(f"[VM Forward] VM {task_id} not found in task store")
        return None

    vm_ip = task_data.get("vm_ip")
    if not vm_ip:
        logger.warning(f"[VM Forward] VM {task_id} has no IP address")
        return None

    return (task_id, vm_ip)


async def _forward_vm_tcp_to_ws(
    client_id: int,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    websocket: WebSocket,
    stop_event: asyncio.Event,
    active_connections: dict[
        int, tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.Task]
    ],
    proto: int = PROTO_TCP,
) -> None:
    """
    Read from a VM TCP connection and forward data to the WebSocket as MSG_DATA.

    Runs as a background task for each active TCP connection. When the VM closes
    the TCP connection or an error occurs, sends the appropriate protocol message
    back through the WebSocket and cleans up.

    Args:
        client_id: The client connection identifier
        reader: TCP stream reader connected to the VM
        writer: TCP stream writer connected to the VM
        websocket: The WebSocket connection to the host/CLI
        stop_event: Event signalling that the session is shutting down
        active_connections: Shared dict tracking all active TCP connections
        proto: Protocol type (PROTO_TCP or PROTO_UDP)
    """
    try:
        while not stop_event.is_set():
            data = await reader.read(65536)
            if not data:
                # TCP connection closed by VM
                logger.debug(f"[VM Forward] VM closed TCP for client_id={client_id}")
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
            error_msg = build_message(MSG_ERROR, proto, client_id, 0, str(e).encode())
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


async def _handle_vm_connect(
    client_id: int,
    vm_ip: str,
    msg_port: int,
    proto: int,
    websocket: WebSocket,
    active_connections: dict[
        int, tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.Task]
    ],
    stop_event: asyncio.Event,
) -> None:
    """
    Handle a MSG_CONNECT for a VM port forward session.

    Opens a direct TCP connection to the VM, starts a background task to
    forward data from the VM back to the WebSocket, and sends a CONNECTED
    response.

    Args:
        client_id: The client connection identifier
        vm_ip: The VM's IP address
        msg_port: The target port on the VM
        proto: Protocol type (PROTO_TCP or PROTO_UDP)
        websocket: The WebSocket connection to the host/CLI
        active_connections: Shared dict tracking all active TCP connections
        stop_event: Event signalling that the session is shutting down
    """
    logger.info(f"[VM Forward] CONNECT client_id={client_id} -> {vm_ip}:{msg_port}")
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
        return

    # Start reading from VM in background
    read_task = asyncio.create_task(
        _forward_vm_tcp_to_ws(
            client_id,
            reader,
            writer,
            websocket,
            stop_event,
            active_connections,
            proto,
        )
    )
    active_connections[client_id] = (reader, writer, read_task)

    # Send CONNECTED back
    connected_msg = build_message(MSG_CONNECTED, proto, client_id, msg_port)
    await websocket.send_bytes(connected_msg)
    logger.info(f"[VM Forward] TCP connected for client_id={client_id}")


async def _cleanup_vm_connections(
    active_connections: dict[
        int, tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.Task]
    ],
    stop_event: asyncio.Event,
) -> None:
    """
    Clean up all active VM TCP connections.

    Sets the stop event to signal background read tasks to stop, cancels
    all read tasks, and closes all TCP writers.

    Args:
        active_connections: Shared dict tracking all active TCP connections
        stop_event: Event signalling that the session is shutting down
    """
    stop_event.set()
    for client_id, (_, writer, read_task) in active_connections.items():
        read_task.cancel()
        try:
            writer.close()
        except Exception:
            pass
    active_connections.clear()


# =============================================================================
# VM Port Forward Handler
# =============================================================================


async def _handle_vm_pf_message(
    msg_type: int,
    header,
    payload: bytes,
    data: bytes,
    port: int,
    vm_ip: str,
    proto: int,
    websocket: WebSocket,
    active_connections: dict[
        int, tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.Task]
    ],
    stop_event: asyncio.Event,
) -> None:
    """
    Handle a single multiplexed message in a VM port forward session.

    Dispatches MSG_CONNECT, MSG_DATA, and MSG_CLOSE to the appropriate
    handler logic for direct TCP connections to VMs.

    Args:
        msg_type: The parsed message type
        header: The parsed message header
        payload: The message payload (data after header)
        data: The full raw message (header + payload)
        port: The default target port
        vm_ip: The VM's IP address
        proto: Protocol type (PROTO_TCP or PROTO_UDP)
        websocket: The WebSocket connection to the host/CLI
        active_connections: Shared dict tracking all active TCP connections
        stop_event: Event signalling that the session is shutting down
    """
    client_id = header.client_id
    msg_port = header.port or port

    match msg_type:
        case proto_mod.MSG_CONNECT:
            await _handle_vm_connect(
                client_id,
                vm_ip,
                msg_port,
                proto,
                websocket,
                active_connections,
                stop_event,
            )

        case proto_mod.MSG_DATA:
            # Forward data to VM TCP connection
            conn = active_connections.get(client_id)
            if not conn:
                logger.warning(f"[VM Forward] DATA for unknown client_id={client_id}")
                return

            _, writer, _ = conn
            try:
                writer.write(payload)
                await writer.drain()
            except Exception as e:
                logger.warning(
                    f"[VM Forward] TCP write failed client_id={client_id}: {e}"
                )

        case proto_mod.MSG_CLOSE:
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

    # Resolve VM target (task_id, vm_ip)
    if not _task_store:
        await websocket.send_text("Error: Task store not available")
        await websocket.close(code=1011)
        return

    resolved = _resolve_vm_target(container_id, _task_store)
    if resolved is None:
        await websocket.send_text(f"Error: Cannot resolve VM target: {container_id}")
        await websocket.close(code=1011)
        return

    task_id, vm_ip = resolved

    logger.info(
        f"[VM Forward] New {proto_name} forward session: VM {task_id} ({vm_ip}), port={port}"
    )

    # Track active TCP connections: client_id -> (reader, writer, read_task)
    active_connections: dict[
        int, tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.Task]
    ] = {}
    stop_event = asyncio.Event()

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
            payload = get_payload(data)

            await _handle_vm_pf_message(
                msg_type,
                header,
                payload,
                data,
                port,
                vm_ip,
                proto,
                websocket,
                active_connections,
                stop_event,
            )

    except WebSocketDisconnect:
        logger.info(f"[VM Forward] Host disconnected (VM {task_id})")
    except Exception as e:
        logger.error(f"[VM Forward] Error: {e}")
    finally:
        await _cleanup_vm_connections(active_connections, stop_event)
        logger.info(f"[VM Forward] Session closed (VM {task_id})")
