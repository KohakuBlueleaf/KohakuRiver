"""
SSH Proxy Client.

Client-side proxy that connects local SSH client to VPS through the host proxy.
"""

import asyncio
import socket

from kohakuriver.ssh_proxy.bind_connection import bind_reader_writer
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


class ClientProxy:
    """Manages the client-side SSH proxy server and connection to Host."""

    def __init__(
        self,
        task_id: str,
        host: str,
        proxy_port: int,
        local_port: int = 0,
        user: str = "root",
    ):
        """
        Initialize client proxy.

        Args:
            task_id: VPS task ID to connect to.
            host: Host server address.
            proxy_port: Host SSH proxy port.
            local_port: Local port to listen on (0 for auto).
            user: SSH username for display.
        """
        self.task_id = task_id
        self.host = host
        self.proxy_port = proxy_port
        self.local_port = local_port
        self.user = user
        self._local_server = None

        if not self.local_port:
            # Find free port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                self.local_port = s.getsockname()[1]

    async def _handle_local_ssh_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """Handle a single incoming connection from the local SSH client."""
        local_client_addr = writer.get_extra_info("peername")
        log_prefix = f"[Local SSH {local_client_addr}]"
        logger.info(f"{log_prefix} New local SSH connection.")

        host_reader = None
        host_writer = None

        try:
            # Connect to Host Proxy
            logger.debug(
                f"{log_prefix} Connecting to Host proxy "
                f"{self.host}:{self.proxy_port}..."
            )
            host_reader, host_writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.proxy_port), timeout=15.0
            )
            logger.debug(f"{log_prefix} Connection to Host proxy established.")

            # Send tunnel request
            request_line = f"REQUEST_TUNNEL {self.task_id}\n"
            logger.debug(f"{log_prefix} Sending request: {request_line.strip()}")
            host_writer.write(request_line.encode())
            await host_writer.drain()

            # Wait for response
            logger.debug(f"{log_prefix} Waiting for response from Host proxy...")
            response = await asyncio.wait_for(
                host_reader.readuntil(b"\n"), timeout=10.0
            )
            response_str = response.strip().decode("utf-8", errors="replace")
            logger.debug(f"{log_prefix} Received response: {response_str}")

            if response.startswith(b"SUCCESS"):
                logger.info(
                    f"{log_prefix} Host proxy reported SUCCESS. "
                    "Starting bidirectional data forwarding."
                )

                # Start bidirectional forwarding
                task_local_to_host = asyncio.create_task(
                    bind_reader_writer(reader, host_writer)
                )
                task_host_to_local = asyncio.create_task(
                    bind_reader_writer(host_reader, writer)
                )

                await asyncio.gather(
                    task_local_to_host, task_host_to_local, return_exceptions=True
                )
                logger.info(f"{log_prefix} Bidirectional forwarding ended.")

            elif response.startswith(b"ERROR"):
                error_message = response_str[len("ERROR ") :]
                logger.error(f"{log_prefix} Host proxy returned error: {error_message}")
                writer.write(f"Proxy Error: {error_message}\r\n".encode())
                await writer.drain()

            else:
                logger.error(
                    f"{log_prefix} Unexpected response from Host proxy: {response_str}"
                )
                writer.write(b"Proxy Error: Unexpected response from server.\r\n")
                await writer.drain()

        except asyncio.TimeoutError:
            logger.error(f"{log_prefix} Timeout during communication with Host proxy.")
            writer.write(b"Proxy Error: Timeout communicating with server.\r\n")
            try:
                await writer.drain()
            except OSError:
                pass

        except ConnectionRefusedError:
            logger.error(
                f"{log_prefix} Connection refused by Host proxy at "
                f"{self.host}:{self.proxy_port}."
            )
            writer.write(b"Proxy Error: Connection refused by server.\r\n")
            try:
                await writer.drain()
            except OSError:
                pass

        except Exception as e:
            logger.exception(f"{log_prefix} Unexpected error during local handler: {e}")
            writer.write(b"Proxy Error: Internal client proxy error.\r\n")
            try:
                await writer.drain()
            except OSError:
                pass

        finally:
            logger.debug(f"{log_prefix} Cleaning up connections.")
            if writer:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
                except OSError:
                    pass
            if host_writer:
                host_writer.close()
                try:
                    await asyncio.wait_for(host_writer.wait_closed(), timeout=1.0)
                except OSError:
                    pass
            logger.info(f"{log_prefix} Local SSH connection handler finished.")

    async def start_local_server(self):
        """Start the local TCP server to listen for the SSH client."""
        try:
            self._local_server = await asyncio.start_server(
                self._handle_local_ssh_client, host="127.0.0.1", port=self.local_port
            )

            addrs = ", ".join(
                str(sock.getsockname()) for sock in self._local_server.sockets
            )
            logger.info(f"Client proxy listening on {addrs}")

            # Print the SSH command for the user
            logger.info("Tunnel established. Connect via SSH:")
            print(f"    ssh {self.user}@127.0.0.1 -p {self.local_port}")

            async with self._local_server:
                await self._local_server.serve_forever()

        except asyncio.CancelledError:
            logger.info("Client proxy server task cancelled.")
            raise
        except OSError as e:
            if e.errno in (98, 48):  # Address already in use (Linux 98, macOS 48)
                logger.error(
                    f"Failed to bind to local port {self.local_port}: "
                    "Address already in use."
                )
                logger.error(
                    "Please choose a different local port using '--local-port'."
                )
            else:
                logger.exception(
                    f"Failed to start client proxy on port {self.local_port}: {e}"
                )
            raise
        except Exception as e:
            logger.critical(
                f"FATAL: Client proxy failed to start on port {self.local_port}: {e}",
                exc_info=True,
            )
            raise

    def close(self):
        """Shut down the local server."""
        if self._local_server:
            self._local_server.close()
            logger.info(f"Client proxy server shutting down on port {self.local_port}.")
