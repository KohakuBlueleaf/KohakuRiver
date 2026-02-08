"""
SSH Proxy Server for Host.

Handles incoming VPS SSH connections and routes them to the correct runner.
"""

import asyncio
import re

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.ssh_proxy.bind_connection import bind_reader_writer
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# Protocol constants
REQUEST_TUNNEL_PREFIX = b"REQUEST_TUNNEL "
SUCCESS_RESPONSE = b"SUCCESS\n"
ERROR_RESPONSE_PREFIX = b"ERROR "


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single incoming connection to the Host SSH proxy."""
    client_addr = writer.get_extra_info("peername")
    log_prefix = f"[Client {client_addr}]"
    logger.info(f"{log_prefix} New connection.")

    task_id_str = None
    proxy_reader = None
    proxy_writer = None

    try:
        # Read the initial request
        try:
            initial_request = await asyncio.wait_for(
                reader.readuntil(b"\n"), timeout=10.0
            )
            logger.debug(
                f"{log_prefix} Received initial request: {initial_request.strip()}"
            )

            if not initial_request.startswith(REQUEST_TUNNEL_PREFIX):
                logger.warning(f"{log_prefix} Invalid request format: Missing prefix.")
                raise ValueError("Invalid request format.")

            # Extract and validate task_id
            task_id_bytes = initial_request[len(REQUEST_TUNNEL_PREFIX) :].strip()

            if not re.fullmatch(rb"\d+", task_id_bytes):
                logger.warning(
                    f"{log_prefix} Invalid task ID format: "
                    f"{task_id_bytes.decode(errors='ignore')}"
                )
                raise ValueError("Invalid task ID format.")

            task_id_str = task_id_bytes.decode("ascii")

        except asyncio.TimeoutError:
            logger.warning(f"{log_prefix} Timeout waiting for initial request.")
            raise ValueError("Timeout waiting for request.")

        # Lookup Task in Database
        task = await asyncio.to_thread(
            Task.get_or_none, Task.task_id == int(task_id_str)
        )

        if not task:
            logger.warning(f"{log_prefix} Task ID {task_id_str} not found in DB.")
            raise ValueError(f"Task {task_id_str} not found.")

        if task.task_type != "vps":
            logger.warning(
                f"{log_prefix} Task ID {task_id_str} is not a VPS task "
                f"(type: {task.task_type})."
            )
            raise ValueError(f"Task {task_id_str} is not a VPS task.")

        active_vps_statuses = ["running", "paused"]
        if task.status not in active_vps_statuses:
            logger.warning(
                f"{log_prefix} VPS task {task_id_str} is not active "
                f"(status: {task.status})."
            )
            raise ValueError(
                f"VPS task {task_id_str} is not active (status: {task.status})."
            )

        if not task.assigned_node:
            logger.error(
                f"{log_prefix} VPS task {task_id_str} has no assigned node in DB."
            )
            raise ValueError(f"VPS task {task_id_str} has no assigned node.")

        if task.ssh_port is None or task.ssh_port <= 0:
            logger.error(
                f"{log_prefix} VPS task {task_id_str} has no valid SSH port: "
                f"{task.ssh_port}."
            )
            raise ValueError(f"VPS task {task_id_str} has no SSH port assigned.")

        # Get assigned node details
        node = await asyncio.to_thread(
            Node.get_or_none, Node.hostname == task.assigned_node
        )

        if not node or node.status != "online":
            logger.warning(
                f"{log_prefix} Assigned node {task.assigned_node} "
                f"for task {task_id_str} is not online."
            )
            raise ValueError(f"Assigned node for VPS task {task_id_str} is not online.")

        # Extract Runner IP from node URL
        try:
            url_parts = node.url.split("://")
            if len(url_parts) < 2:
                raise ValueError(f"Invalid runner URL format: {node.url}")
            host_port_part = url_parts[1]
            runner_ip = host_port_part.split(":")[0]
            ssh_port = task.ssh_port

            logger.info(
                f"{log_prefix} Task {task_id_str} validated. "
                f"Routing to {runner_ip}:{ssh_port}."
            )

        except Exception as url_e:
            logger.error(f"{log_prefix} Error parsing runner URL {node.url}: {url_e}")
            raise ValueError(
                f"Error parsing runner URL for node {node.hostname}."
            ) from url_e

        # Connect to the Runner/VPS SSH Port
        try:
            logger.debug(
                f"{log_prefix} Connecting to Runner/VPS at {runner_ip}:{ssh_port}..."
            )
            proxy_reader, proxy_writer = await asyncio.wait_for(
                asyncio.open_connection(runner_ip, ssh_port), timeout=15.0
            )
            logger.info(
                f"{log_prefix} Proxy connection established to {runner_ip}:{ssh_port}."
            )

        except asyncio.TimeoutError:
            logger.warning(
                f"{log_prefix} Timeout connecting to Runner/VPS at "
                f"{runner_ip}:{ssh_port}."
            )
            raise ValueError(f"Timeout connecting to Runner for task {task_id_str}.")
        except ConnectionRefusedError:
            logger.warning(
                f"{log_prefix} Connection refused by {runner_ip}:{ssh_port}. "
                "Is SSH daemon running in the container?"
            )
            raise ValueError(
                f"Connection refused by VPS task {task_id_str} on node "
                f"{node.hostname}."
            )

        # Send SUCCESS and start forwarding
        logger.debug(f"{log_prefix} Sending SUCCESS response to client proxy.")
        writer.write(SUCCESS_RESPONSE)
        await writer.drain()

        logger.info(f"{log_prefix} Starting bidirectional data forwarding.")

        task_client_to_proxy = asyncio.create_task(
            bind_reader_writer(reader, proxy_writer)
        )
        task_proxy_to_client = asyncio.create_task(
            bind_reader_writer(proxy_reader, writer)
        )

        await asyncio.gather(
            task_client_to_proxy, task_proxy_to_client, return_exceptions=True
        )
        logger.info(f"{log_prefix} Bidirectional forwarding ended.")

    except ValueError as e:
        error_message = f"{ERROR_RESPONSE_PREFIX.decode()}{str(e)}\n"
        logger.warning(
            f"{log_prefix} Sending error to client proxy: {error_message.strip()}"
        )
        try:
            writer.write(error_message.encode())
            await writer.drain()
        except OSError:
            pass

    except Exception as e:
        error_message = f"{ERROR_RESPONSE_PREFIX.decode()}Internal server error.\n"
        logger.exception(f"{log_prefix} Unexpected error in connection handler: {e}")
        try:
            writer.write(error_message.encode())
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
        if proxy_writer:
            proxy_writer.close()
            try:
                await asyncio.wait_for(proxy_writer.wait_closed(), timeout=1.0)
            except OSError:
                pass
        logger.info(f"{log_prefix} Connection handler finished.")


async def start_server(host: str, port: int):
    """
    Start the Host-side TCP server for VPS SSH proxying.

    Args:
        host: Host address to bind to.
        port: Port to listen on.
    """
    try:
        server = await asyncio.start_server(handle_connection, host, port)
        addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        logger.info(f"Host SSH Proxy server started on {addrs}")

        async with server:
            await server.serve_forever()

    except asyncio.CancelledError:
        logger.info("Host SSH Proxy server task cancelled.")
        raise
    except Exception as e:
        logger.critical(
            f"FATAL: Host SSH Proxy server failed to start on {host}:{port}: {e}",
            exc_info=True,
        )
        raise
