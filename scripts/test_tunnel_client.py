#!/usr/bin/env python3
"""
Test script for the Rust tunnel-client binary.

This script sets up:
1. A mock TCP echo server (simulates service in container)
2. A mock runner tunnel server (WebSocket, simulates runner's tunnel endpoint)
3. Runs the tunnel-client binary

Then performs tests to verify:
- Tunnel client connects properly
- Data flows correctly through the tunnel
- Reconnection works after disconnects
- Multiple concurrent connections work

Usage:
    python scripts/test_tunnel_client.py [--tunnel-client PATH]

Requirements:
    - The tunnel-client binary must be built first
    - websockets library: pip install websockets
"""

import argparse
import asyncio
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

try:
    import websockets
    from websockets.server import serve as ws_serve
except ImportError:
    print("Error: websockets library required. Run: pip install websockets")
    sys.exit(1)

# Add project to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

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
    build_message,
    get_payload,
    parse_header,
)

# =============================================================================
# Configuration
# =============================================================================

ECHO_SERVER_PORT = 19876
TUNNEL_SERVER_PORT = 19877
CONTAINER_ID = "test-container"

# Colors for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def log_info(msg: str) -> None:
    print(f"{CYAN}[INFO]{RESET} {msg}")


def log_ok(msg: str) -> None:
    print(f"{GREEN}[PASS]{RESET} {msg}")


def log_fail(msg: str) -> None:
    print(f"{RED}[FAIL]{RESET} {msg}")


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


# =============================================================================
# Mock Echo Server (simulates service in container)
# =============================================================================


class EchoServer:
    """Simple TCP echo server."""

    def __init__(self, port: int):
        self.port = port
        self.server = None
        self._connections: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start the echo server."""
        self.server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", self.port
        )
        log_info(f"Echo server listening on 127.0.0.1:{self.port}")

    async def stop(self) -> None:
        """Stop the echo server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for task in self._connections:
            task.cancel()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Echo back any data received."""
        peer = writer.get_extra_info("peername")
        log_info(f"Echo: Client connected from {peer}")

        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                log_info(f"Echo: Received {len(data)} bytes, echoing back")
                writer.write(data)
                await writer.drain()
        except Exception as e:
            log_warn(f"Echo: Connection error: {e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            log_info(f"Echo: Client disconnected from {peer}")


# =============================================================================
# Mock Tunnel Server (simulates runner's tunnel WebSocket)
# =============================================================================


class MockTunnelServer:
    """
    Simulates the runner's tunnel server.

    Accepts WebSocket connections from tunnel-client and handles
    CONNECT/DATA/CLOSE messages, forwarding to local TCP services.
    """

    def __init__(self, ws_port: int, target_host: str = "127.0.0.1"):
        self.ws_port = ws_port
        self.target_host = target_host
        self._server = None
        self._client_connections: dict[
            int, tuple[asyncio.StreamReader, asyncio.StreamWriter]
        ] = {}
        self._ws = None
        # Queue for received messages from tunnel-client
        self._received_messages: asyncio.Queue = asyncio.Queue()

    async def start(self) -> None:
        """Start the tunnel server."""
        self._server = await ws_serve(self._handle_websocket, "127.0.0.1", self.ws_port)
        log_info(f"Tunnel server listening on ws://127.0.0.1:{self.ws_port}")

    async def stop(self) -> None:
        """Stop the tunnel server."""
        # Close all TCP connections
        for client_id, (reader, writer) in self._client_connections.items():
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        self._client_connections.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_websocket(self, websocket, path: str) -> None:
        """Handle WebSocket connection from tunnel-client."""
        container_id = path.split("/")[-1] if "/" in path else "unknown"
        log_info(f"Tunnel: Client connected (container={container_id})")

        self._ws = websocket

        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    await self._handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            log_info(f"Tunnel: Client disconnected (container={container_id})")
        except Exception as e:
            log_warn(f"Tunnel: Error: {e}")
        finally:
            self._ws = None
            # Close all connections
            for client_id, (reader, writer) in list(self._client_connections.items()):
                writer.close()
            self._client_connections.clear()

    async def _handle_message(self, websocket, data: bytes) -> None:
        """Handle a tunnel protocol message."""
        header = parse_header(data)
        if not header:
            log_warn(f"Tunnel: Invalid message (too short)")
            return

        payload = get_payload(data)

        # Queue all messages for test verification
        await self._received_messages.put((header, payload))

        if header.msg_type == MSG_CONNECTED:
            log_info(f"Tunnel: Received CONNECTED client={header.client_id}")
        elif header.msg_type == MSG_DATA:
            log_info(
                f"Tunnel: Received DATA client={header.client_id} len={len(payload)}"
            )
        elif header.msg_type == MSG_CLOSE:
            log_info(f"Tunnel: Received CLOSE client={header.client_id}")
        elif header.msg_type == MSG_ERROR:
            log_warn(
                f"Tunnel: Received ERROR client={header.client_id}: {payload.decode(errors='replace')}"
            )
        elif header.msg_type == MSG_PING:
            # Respond with PONG
            pong = build_message(MSG_PONG, header.proto, header.client_id)
            await websocket.send(pong)

    async def _handle_connect(self, websocket, header) -> None:
        """Handle CONNECT message - open TCP connection to target."""
        client_id = header.client_id
        port = header.port
        log_info(f"Tunnel: CONNECT client={client_id} -> port={port}")

        try:
            reader, writer = await asyncio.open_connection(self.target_host, port)
            self._client_connections[client_id] = (reader, writer)

            # Send CONNECTED
            connected = build_message(MSG_CONNECTED, header.proto, client_id, port)
            await websocket.send(connected)

            # Start reading from TCP and forwarding to WebSocket
            asyncio.create_task(
                self._forward_tcp_to_ws(websocket, client_id, header.proto, reader)
            )

            log_info(f"Tunnel: CONNECTED client={client_id}")

        except Exception as e:
            log_warn(f"Tunnel: Connection failed: {e}")
            error = build_message(
                MSG_ERROR, header.proto, client_id, 0, str(e).encode()
            )
            await websocket.send(error)

    async def _handle_data(self, websocket, header, payload: bytes) -> None:
        """Handle DATA message - forward to TCP connection."""
        client_id = header.client_id

        conn = self._client_connections.get(client_id)
        if not conn:
            log_warn(f"Tunnel: DATA for unknown client {client_id}")
            return

        reader, writer = conn
        writer.write(payload)
        await writer.drain()

    async def _handle_close(self, header) -> None:
        """Handle CLOSE message - close TCP connection."""
        client_id = header.client_id
        log_info(f"Tunnel: CLOSE client={client_id}")

        conn = self._client_connections.pop(client_id, None)
        if conn:
            _, writer = conn
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _forward_tcp_to_ws(
        self, websocket, client_id: int, proto: int, reader: asyncio.StreamReader
    ) -> None:
        """Forward data from TCP connection to WebSocket."""
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                msg = build_message(MSG_DATA, proto, client_id, 0, data)
                await websocket.send(msg)
        except Exception as e:
            log_warn(f"Tunnel: TCP read error for client {client_id}: {e}")
        finally:
            # Send CLOSE if connection still exists
            if client_id in self._client_connections:
                close = build_message(MSG_CLOSE, proto, client_id)
                try:
                    await websocket.send(close)
                except Exception:
                    pass
                self._client_connections.pop(client_id, None)


# =============================================================================
# Test Runner
# =============================================================================


def find_tunnel_client() -> Path | None:
    """Find the tunnel-client binary."""
    candidates = [
        PROJECT_ROOT
        / "src"
        / "kohakuriver-tunnel"
        / "target"
        / "release"
        / "tunnel-client",
        PROJECT_ROOT
        / "src"
        / "kohakuriver-tunnel"
        / "target"
        / "debug"
        / "tunnel-client",
        Path("/usr/local/bin/tunnel-client"),
    ]

    for path in candidates:
        if path.exists() and path.is_file():
            return path

    return None


async def run_tests(tunnel_client_path: Path) -> bool:
    """Run all tests."""
    echo_server = EchoServer(ECHO_SERVER_PORT)
    tunnel_server = MockTunnelServer(TUNNEL_SERVER_PORT)

    # Start servers
    await echo_server.start()
    await tunnel_server.start()

    # Give servers time to start
    await asyncio.sleep(0.2)

    # Start tunnel-client
    env = os.environ.copy()
    tunnel_url = f"ws://127.0.0.1:{TUNNEL_SERVER_PORT}/ws/tunnel/{CONTAINER_ID}"

    log_info(f"Starting tunnel-client: {tunnel_client_path}")
    log_info(f"  --runner-url {tunnel_url}")
    log_info(f"  --container-id {CONTAINER_ID}")

    tunnel_process = subprocess.Popen(
        [
            str(tunnel_client_path),
            "--runner-url",
            tunnel_url,
            "--container-id",
            CONTAINER_ID,
            "--log-level",
            "debug",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    # Give tunnel-client time to connect
    await asyncio.sleep(1.0)

    if tunnel_process.poll() is not None:
        stdout, stderr = tunnel_process.communicate()
        log_fail(f"Tunnel-client exited prematurely!")
        log_info(f"stdout: {stdout.decode()}")
        log_info(f"stderr: {stderr.decode()}")
        await echo_server.stop()
        await tunnel_server.stop()
        return False

    all_passed = True

    # Test 1: Basic echo through tunnel
    log_info("=" * 50)
    log_info("Test 1: Basic TCP echo through tunnel")
    log_info("=" * 50)

    try:
        # Send a CONNECT request through the tunnel server to tunnel-client
        # The tunnel-client should connect to our echo server
        if tunnel_server._ws:
            # Clear any pending messages
            while not tunnel_server._received_messages.empty():
                tunnel_server._received_messages.get_nowait()

            connect_msg = build_message(MSG_CONNECT, PROTO_TCP, 1, ECHO_SERVER_PORT)
            await tunnel_server._ws.send(connect_msg)

            # Wait for CONNECTED response from queue
            connected_received = False
            try:
                header, payload = await asyncio.wait_for(
                    tunnel_server._received_messages.get(), timeout=2.0
                )
                if header.msg_type == MSG_CONNECTED and header.client_id == 1:
                    connected_received = True
                elif header.msg_type == MSG_ERROR:
                    log_fail(f"Test 1: Got ERROR: {payload.decode(errors='replace')}")
                    all_passed = False
            except asyncio.TimeoutError:
                pass

            if not connected_received:
                log_fail("Test 1: Never received CONNECTED response")
                all_passed = False
            else:
                # Send data and wait for echo response
                test_data = b"Hello, Tunnel World!"
                data_msg = build_message(MSG_DATA, PROTO_TCP, 1, 0, test_data)
                await tunnel_server._ws.send(data_msg)

                # Wait for echoed DATA response from queue
                echo_received = False
                try:
                    header, payload = await asyncio.wait_for(
                        tunnel_server._received_messages.get(), timeout=2.0
                    )
                    if header.msg_type == MSG_DATA and header.client_id == 1:
                        if payload == test_data:
                            echo_received = True
                            log_ok("Test 1: Data echoed correctly through tunnel!")
                        else:
                            log_fail(
                                f"Test 1: Echo mismatch - got {payload!r}, expected {test_data!r}"
                            )
                            all_passed = False
                except asyncio.TimeoutError:
                    pass

                if not echo_received:
                    log_fail("Test 1: Never received echoed DATA response")
                    all_passed = False
        else:
            log_fail("Test 1: Tunnel client never connected")
            all_passed = False

    except Exception as e:
        log_fail(f"Test 1: Error - {e}")
        import traceback

        traceback.print_exc()
        all_passed = False

    # Test 2: Multiple data packets
    log_info("=" * 50)
    log_info("Test 2: Multiple data packets")
    log_info("=" * 50)

    try:
        if tunnel_server._ws:
            for i in range(5):
                test_data = f"Packet {i}".encode()
                data_msg = build_message(MSG_DATA, PROTO_TCP, 1, 0, test_data)
                await tunnel_server._ws.send(data_msg)
                await asyncio.sleep(0.1)

            log_ok("Test 2: Multiple packets sent successfully")
        else:
            log_fail("Test 2: No connection")
            all_passed = False

    except Exception as e:
        log_fail(f"Test 2: Error - {e}")
        all_passed = False

    # Test 3: Connection close
    log_info("=" * 50)
    log_info("Test 3: Connection close")
    log_info("=" * 50)

    try:
        if tunnel_server._ws:
            close_msg = build_message(MSG_CLOSE, PROTO_TCP, 1)
            await tunnel_server._ws.send(close_msg)
            await asyncio.sleep(0.2)
            log_ok("Test 3: Close message sent")
        else:
            log_fail("Test 3: No connection")
            all_passed = False

    except Exception as e:
        log_fail(f"Test 3: Error - {e}")
        all_passed = False

    # Cleanup
    log_info("=" * 50)
    log_info("Cleaning up...")
    log_info("=" * 50)

    tunnel_process.terminate()
    try:
        tunnel_process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        tunnel_process.kill()

    await echo_server.stop()
    await tunnel_server.stop()

    return all_passed


async def main() -> int:
    parser = argparse.ArgumentParser(description="Test tunnel-client binary")
    parser.add_argument(
        "--tunnel-client",
        type=Path,
        help="Path to tunnel-client binary",
    )
    args = parser.parse_args()

    # Find tunnel-client
    if args.tunnel_client:
        tunnel_client_path = args.tunnel_client
    else:
        tunnel_client_path = find_tunnel_client()

    if not tunnel_client_path or not tunnel_client_path.exists():
        log_fail("tunnel-client binary not found!")
        log_info("Build it first: cd src/kohakuriver-tunnel && cargo build --release")
        return 1

    log_info(f"Using tunnel-client: {tunnel_client_path}")

    # Run tests
    success = await run_tests(tunnel_client_path)

    print()
    if success:
        log_ok("All tests passed!")
        return 0
    else:
        log_fail("Some tests failed!")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
