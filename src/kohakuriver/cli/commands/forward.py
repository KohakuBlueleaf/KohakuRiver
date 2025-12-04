"""
Port forwarding command for accessing container services.

This command creates a local TCP/UDP server that forwards connections
through a single persistent WebSocket tunnel to reach services running
inside Docker containers without port mapping.

Architecture:
    CLI (single WS) ←→ Host (single WS) ←→ Runner ←→ Container tunnel-client
         ↑
    Local TCP/UDP connections multiplexed with client_id

Example:
    # Forward local port 8080 to container port 80
    kohakuriver forward 12345 80 --local-port 8080

    # Forward with UDP protocol
    kohakuriver forward 12345 5353 --proto udp --local-port 5353
"""

import asyncio
import struct
from typing import Annotated

import typer
import websockets

from kohakuriver.cli import client, config as cli_config
from kohakuriver.cli.output import console, print_error

app = typer.Typer(help="Forward local ports to container services")

# Protocol header format (matches tunnel protocol)
# type(1) + proto(1) + client_id(4) + port(2) = 8 bytes
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
    """Parse header from message. Returns (msg_type, proto, client_id, port) or None."""
    if len(data) < HEADER_SIZE:
        return None
    return struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])


def get_payload(data: bytes) -> bytes:
    """Extract payload from message."""
    return data[HEADER_SIZE:] if len(data) > HEADER_SIZE else b""


@app.callback(invoke_without_command=True)
def forward(
    task_id: Annotated[str, typer.Argument(help="Task or VPS ID of the container")],
    remote_port: Annotated[
        int, typer.Argument(help="Port in the container to forward to")
    ],
    local_port: Annotated[
        int | None,
        typer.Option(
            "--local-port",
            "-l",
            help="Local port to listen on (default: same as remote)",
        ),
    ] = None,
    local_host: Annotated[
        str,
        typer.Option(
            "--local-host",
            "-H",
            help="Local address to bind to",
        ),
    ] = "127.0.0.1",
    proto: Annotated[
        str,
        typer.Option(
            "--proto",
            "-p",
            help="Protocol: tcp or udp",
        ),
    ] = "tcp",
):
    """
    Forward a local port to a container service.

    Creates a local server that forwards all connections through the
    KohakuRiver tunnel system to reach services running inside containers.
    """
    proto_lower = proto.lower()
    if proto_lower not in ("tcp", "udp"):
        print_error(f"Invalid protocol: {proto}. Use 'tcp' or 'udp'.")
        raise typer.Exit(1)

    if local_port is None:
        local_port = remote_port

    try:
        # Validate task exists and is running
        task = client.get_task_status(task_id)

        if not task:
            print_error(f"Task {task_id} not found.")
            raise typer.Exit(1)

        task_type = task.get("task_type")
        if task_type not in ("vps", "command"):
            print_error(f"Task {task_id} is not a container task (type: {task_type})")
            raise typer.Exit(1)

        status = task.get("status")
        if status != "running":
            print_error(f"Task is not running (status: {status})")
            raise typer.Exit(1)

        console.print(
            f"[bold green]Forwarding[/bold green] "
            f"[cyan]{local_host}:{local_port}[/cyan] "
            f"[dim]→[/dim] "
            f"[yellow]container:{remote_port}[/yellow] "
            f"[dim]({proto_lower.upper()})[/dim]"
        )
        console.print("[dim]Press Ctrl+C to stop.[/dim]")

        if proto_lower == "tcp":
            asyncio.run(
                _run_tcp_forwarder(task_id, remote_port, local_host, local_port)
            )
        else:
            asyncio.run(
                _run_udp_forwarder(task_id, remote_port, local_host, local_port)
            )

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
    except OSError as e:
        if "Address already in use" in str(e):
            print_error(f"Port {local_port} is already in use.")
        else:
            print_error(f"Error: {e}")
        raise typer.Exit(1)


class TunnelForwarder:
    """
    Manages a single persistent WebSocket connection for port forwarding.

    Multiplexes multiple local TCP/UDP connections over the single WebSocket.
    """

    def __init__(self, task_id: str, remote_port: int, proto: int):
        self.task_id = task_id
        self.remote_port = remote_port
        self.proto = proto
        self.ws = None
        self._next_client_id = 1
        self._lock = asyncio.Lock()
        # Map client_id -> (reader, writer) for TCP or (queue, addr) for UDP
        self._connections: dict[int, tuple] = {}
        self._connected = asyncio.Event()
        self._error: str | None = None

    async def connect(self) -> bool:
        """Establish the persistent WebSocket connection."""
        ws_url = (
            f"ws://{cli_config.HOST_ADDRESS}:{cli_config.HOST_PORT}"
            f"/ws/forward/{self.task_id}/{self.remote_port}"
            f"?proto={'udp' if self.proto == PROTO_UDP else 'tcp'}"
        )

        try:
            self.ws = await websockets.connect(ws_url)

            # Wait for CONNECTED signal
            first_msg = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            if isinstance(first_msg, str):
                if first_msg == "CONNECTED":
                    console.print("[green]Tunnel established[/green]")
                    self._connected.set()
                    return True
                elif first_msg.startswith("Error:"):
                    console.print(f"[red]{first_msg}[/red]")
                    self._error = first_msg
                    return False
                else:
                    console.print(f"[yellow]Server: {first_msg}[/yellow]")
                    return False
            else:
                console.print("[red]Unexpected binary response[/red]")
                return False

        except asyncio.TimeoutError:
            console.print("[red]Timeout waiting for tunnel connection[/red]")
            return False
        except Exception as e:
            console.print(f"[red]Failed to connect: {e}[/red]")
            return False

    async def allocate_client_id(self) -> int:
        """Allocate a unique client ID."""
        async with self._lock:
            client_id = self._next_client_id
            self._next_client_id += 1
            return client_id

    async def send_connect(self, client_id: int) -> bool:
        """Send CONNECT message for a new local connection."""
        if not self.ws:
            return False
        msg = build_message(MSG_CONNECT, self.proto, client_id, self.remote_port)
        try:
            await self.ws.send(msg)
            return True
        except Exception as e:
            console.print(f"[red]Failed to send CONNECT: {e}[/red]")
            return False

    async def send_data(self, client_id: int, data: bytes) -> bool:
        """Send DATA message."""
        if not self.ws:
            return False
        msg = build_message(MSG_DATA, self.proto, client_id, 0, data)
        try:
            await self.ws.send(msg)
            return True
        except Exception:
            return False

    async def send_close(self, client_id: int) -> None:
        """Send CLOSE message."""
        if not self.ws:
            return
        msg = build_message(MSG_CLOSE, self.proto, client_id)
        try:
            await self.ws.send(msg)
        except Exception:
            pass

    async def receive_loop(self) -> None:
        """Receive messages from WebSocket and dispatch to local connections."""
        if not self.ws:
            return

        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    await self._handle_message(message)
                elif isinstance(message, str):
                    if message.startswith("Error:"):
                        console.print(f"[red]{message}[/red]")
                    else:
                        console.print(f"[dim]Server: {message}[/dim]")
        except websockets.exceptions.ConnectionClosed:
            console.print("[yellow]Tunnel connection closed[/yellow]")
        except Exception as e:
            console.print(f"[red]Receive error: {e}[/red]")

    async def _handle_message(self, data: bytes) -> None:
        """Handle a received tunnel message."""
        header = parse_header(data)
        if not header:
            return

        msg_type, proto, client_id, port = header
        payload = get_payload(data)

        if msg_type == MSG_CONNECTED:
            console.print(f"[dim]Connection {client_id} established[/dim]")

        elif msg_type == MSG_DATA:
            console.print(
                f"[green]← Received {len(payload)} bytes from tunnel (client_id={client_id})[/green]"
            )
            conn = self._connections.get(client_id)
            if conn:
                reader, writer = conn
                try:
                    writer.write(payload)
                    await writer.drain()
                except Exception as e:
                    console.print(f"[red]Failed to write to local: {e}[/red]")

        elif msg_type == MSG_CLOSE:
            console.print(f"[dim]Connection {client_id} closed by server[/dim]")
            conn = self._connections.pop(client_id, None)
            if conn:
                _, writer = conn
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        elif msg_type == MSG_ERROR:
            error_msg = payload.decode("utf-8", errors="replace")
            console.print(f"[red]Connection {client_id} error: {error_msg}[/red]")
            conn = self._connections.pop(client_id, None)
            if conn:
                _, writer = conn
                writer.close()

    def register_connection(self, client_id: int, reader, writer) -> None:
        """Register a local TCP connection."""
        self._connections[client_id] = (reader, writer)

    def unregister_connection(self, client_id: int) -> None:
        """Unregister a local connection."""
        self._connections.pop(client_id, None)

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass


async def _run_tcp_forwarder(
    task_id: str,
    remote_port: int,
    local_host: str,
    local_port: int,
) -> None:
    """Run TCP port forwarder with single persistent WebSocket."""

    forwarder = TunnelForwarder(task_id, remote_port, PROTO_TCP)

    # Establish persistent connection first
    if not await forwarder.connect():
        return

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a single TCP client connection."""
        peer = writer.get_extra_info("peername")
        client_id = await forwarder.allocate_client_id()

        console.print(f"[dim]New connection from {peer} (id={client_id})[/dim]")

        # Register and send CONNECT
        forwarder.register_connection(client_id, reader, writer)

        if not await forwarder.send_connect(client_id):
            console.print(f"[red]Failed to open tunnel for {peer}[/red]")
            forwarder.unregister_connection(client_id)
            writer.close()
            return

        try:
            # Read from local and send to tunnel
            while True:
                data = await reader.read(65536)
                if not data:
                    console.print(
                        f"[dim]Connection {client_id}: local closed (EOF)[/dim]"
                    )
                    break
                console.print(
                    f"[cyan]→ Sending {len(data)} bytes to tunnel (client_id={client_id})[/cyan]"
                )
                if not await forwarder.send_data(client_id, data):
                    console.print(f"[red]Failed to send data to tunnel[/red]")
                    break
        except Exception as e:
            console.print(f"[dim]Connection {client_id} error: {e}[/dim]")
        finally:
            await forwarder.send_close(client_id)
            forwarder.unregister_connection(client_id)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            console.print(f"[dim]Connection from {peer} closed (id={client_id})[/dim]")

    # Start TCP server
    server = await asyncio.start_server(handle_client, local_host, local_port)

    console.print(f"[green]Listening on {local_host}:{local_port}[/green]")

    # Run server and receive loop concurrently
    async with server:
        receive_task = asyncio.create_task(forwarder.receive_loop())
        serve_task = asyncio.create_task(server.serve_forever())

        try:
            done, pending = await asyncio.wait(
                [receive_task, serve_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in [receive_task, serve_task]:
                t.cancel()
            await asyncio.gather(receive_task, serve_task, return_exceptions=True)
            await forwarder.close()


async def _run_udp_forwarder(
    task_id: str,
    remote_port: int,
    local_host: str,
    local_port: int,
) -> None:
    """Run UDP port forwarder with single persistent WebSocket."""

    forwarder = TunnelForwarder(task_id, remote_port, PROTO_UDP)

    # Establish persistent connection first
    if not await forwarder.connect():
        return

    loop = asyncio.get_running_loop()

    # Track UDP clients: addr -> client_id
    udp_clients: dict[tuple, int] = {}
    transport: asyncio.DatagramTransport | None = None

    class UDPProtocol(asyncio.DatagramProtocol):
        def connection_made(self, t: asyncio.DatagramTransport) -> None:
            nonlocal transport
            transport = t

        def datagram_received(self, data: bytes, addr: tuple) -> None:
            # Get or create client_id for this address
            if addr not in udp_clients:
                client_id = loop.run_until_complete(forwarder.allocate_client_id())
                udp_clients[addr] = client_id
                console.print(f"[dim]New UDP client from {addr} (id={client_id})[/dim]")
                # Send CONNECT
                loop.create_task(forwarder.send_connect(client_id))

            client_id = udp_clients[addr]
            loop.create_task(forwarder.send_data(client_id, data))

        def error_received(self, exc: Exception) -> None:
            console.print(f"[red]UDP error: {exc}[/red]")

    # Override handle_message for UDP
    original_handle = forwarder._handle_message

    async def udp_handle_message(data: bytes) -> None:
        header = parse_header(data)
        if not header:
            return

        msg_type, proto, client_id, port = header
        payload = get_payload(data)

        if msg_type == MSG_DATA and transport:
            # Find addr for this client_id
            for addr, cid in udp_clients.items():
                if cid == client_id:
                    transport.sendto(payload, addr)
                    break
        elif msg_type == MSG_CLOSE:
            # Remove client mapping
            for addr, cid in list(udp_clients.items()):
                if cid == client_id:
                    del udp_clients[addr]
                    console.print(
                        f"[dim]UDP client {addr} closed (id={client_id})[/dim]"
                    )
                    break
        else:
            await original_handle(data)

    forwarder._handle_message = udp_handle_message

    # Create UDP endpoint
    transport, protocol = await loop.create_datagram_endpoint(
        UDPProtocol,
        local_addr=(local_host, local_port),
    )

    console.print(f"[green]Listening on {local_host}:{local_port} (UDP)[/green]")

    try:
        # Run receive loop
        await forwarder.receive_loop()
    finally:
        transport.close()
        await forwarder.close()
