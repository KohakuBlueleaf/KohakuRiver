"""
Docker/container management commands.

This module provides CLI commands for managing Docker containers and
tarballs in the KohakuRiver cluster.

Commands:
    images          List KohakuRiver container images
    delete          Delete a Docker image
    container list  List host containers
    container create Create a new container
    container shell Open interactive shell in container
    tar list        List container tarballs
    tar create      Create tarball from container
"""

import asyncio
import json
import os
import signal
import sys
import termios
import tty
from datetime import datetime
from typing import Annotated

import typer
from rich.table import Table

from kohakuriver.cli import client, config as cli_config
from kohakuriver.cli.formatters.docker import format_image_table
from kohakuriver.cli.output import console, format_bytes, print_error, print_success

app = typer.Typer(help="Docker/container management commands")

# Subcommand groups
container_app = typer.Typer(help="Host container management")
tar_app = typer.Typer(help="Container tarball management")

app.add_typer(container_app, name="container")
app.add_typer(tar_app, name="tar")


# =============================================================================
# HakuRiver Images (hakuriver docker images)
# =============================================================================


@app.command("images")
def list_images():
    """List HakuRiver container images."""
    try:
        images = client.get_docker_images()

        if not images:
            console.print("[yellow]No images found.[/yellow]")
            return

        table = format_image_table(images)
        console.print(table)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
def delete_image(
    name: Annotated[str, typer.Argument(help="Image name to delete")],
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Force deletion")
    ] = False,
):
    """Delete a Docker image."""
    try:
        if not force:
            confirm = typer.confirm(f"Delete image '{name}'?")
            if not confirm:
                console.print("[dim]Cancelled.[/dim]")
                return

        result = client.delete_docker_image(name)

        if result.get("success") or result.get("deleted"):
            print_success(f"Image '{name}' deleted.")
        else:
            print_error(f"Failed to delete image: {result}")
            raise typer.Exit(1)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


# =============================================================================
# Host Container Management (hakuriver docker container ...)
# =============================================================================


@container_app.command("list")
def list_containers():
    """List Docker containers on the host."""
    try:
        containers = client.get_host_containers()

        if not containers:
            console.print("[yellow]No containers found.[/yellow]")
            return

        table = Table(title="Environment Containers (Host)", show_header=True)
        table.add_column("Environment", style="bold cyan")
        table.add_column("Image")
        table.add_column("Status", justify="center")
        table.add_column("Container Name", style="dim")

        for c in containers:
            status = c.get("status", "unknown")
            status_style = (
                "green"
                if status == "running"
                else "yellow" if status == "exited" else "dim"
            )

            # Show env_name (without prefix) as the primary name
            env_name = c.get("env_name", c.get("name", ""))

            table.add_row(
                env_name,
                c.get("image", ""),
                f"[{status_style}]{status}[/{status_style}]",
                c.get("name", ""),
            )

        console.print(table)
        console.print(
            f"\n[dim]Use environment name (first column) for commands like 'shell', 'tar create', etc.[/dim]"
        )

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@container_app.command("create")
def create_container(
    image: Annotated[str, typer.Argument(help="Base Docker image (e.g., python:3.11)")],
    name: Annotated[str, typer.Argument(help="Container name")],
):
    """Create a new container for environment setup."""
    try:
        console.print(f"[dim]Creating container '{name}' from '{image}'...[/dim]")

        result = client.create_docker_container(image, name)

        if result.get("message") or result.get("container_id"):
            print_success(f"Container '{name}' created successfully.")
            console.print(f"\n[bold]Next steps:[/bold]")
            console.print(f"  1. Enter the container:")
            console.print(f"     [cyan]hakuriver docker container shell {name}[/cyan]")
            console.print(f"  2. Install your packages and configure the environment")
            console.print(f"  3. Create tarball for distribution:")
            console.print(f"     [cyan]hakuriver docker tar create {name}[/cyan]")
        else:
            print_error(f"Failed to create container: {result}")
            raise typer.Exit(1)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@container_app.command("delete")
def delete_container(
    name: Annotated[str, typer.Argument(help="Container name to delete")],
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Force deletion")
    ] = False,
):
    """Delete a container on the host."""
    try:
        if not force:
            confirm = typer.confirm(f"Delete container '{name}'?")
            if not confirm:
                console.print("[dim]Cancelled.[/dim]")
                return

        result = client.delete_host_container(name)

        if result.get("message"):
            print_success(result["message"])
        else:
            print_error(f"Failed to delete container: {result}")
            raise typer.Exit(1)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@container_app.command("start")
def start_container(
    name: Annotated[str, typer.Argument(help="Container name to start")],
):
    """Start a stopped container."""
    try:
        result = client.start_host_container(name)

        if result.get("message"):
            print_success(result["message"])
        else:
            print_error(f"Failed to start container: {result}")
            raise typer.Exit(1)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@container_app.command("stop")
def stop_container(
    name: Annotated[str, typer.Argument(help="Container name to stop")],
):
    """Stop a running container."""
    try:
        result = client.stop_host_container(name)

        if result.get("message"):
            print_success(result["message"])
        else:
            print_error(f"Failed to stop container: {result}")
            raise typer.Exit(1)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@container_app.command("shell")
def container_shell(
    name: Annotated[str, typer.Argument(help="Environment name")],
):
    """Open a shell in a container for environment setup.

    Connects to the container via WebSocket terminal.
    """
    try:
        console.print(f"[dim]Opening shell in environment '{name}'...[/dim]")

        # First make sure the container is running
        containers = client.get_host_containers()
        # Look up by env_name (without prefix)
        container = next(
            (
                c
                for c in containers
                if c.get("env_name") == name or c.get("name") == name
            ),
            None,
        )

        if not container:
            print_error(f"Environment '{name}' not found.")
            raise typer.Exit(1)

        if container.get("status") != "running":
            console.print(f"[dim]Starting container...[/dim]")
            client.start_host_container(name)

        # Connect via WebSocket
        asyncio.run(_run_terminal_shell(name))

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


async def _run_terminal_shell(container_name: str):
    """
    Run interactive WebSocket terminal session with full TTY support.

    Supports:
        - Arrow keys, escape sequences
        - Ctrl+C (sent to container, not local)
        - TUI apps like vim, htop, nano, screen
        - Exit by typing 'exit' command in shell
    """
    import websockets

    ws_url = (
        f"ws://{cli_config.HOST_ADDRESS}:{cli_config.HOST_PORT}"
        f"/docker/host/containers/{container_name}/terminal"
    )
    console.print(f"[dim]Connecting to {ws_url}...[/dim]")

    old_settings = termios.tcgetattr(sys.stdin) if sys.stdin.isatty() else None

    try:
        async with websockets.connect(ws_url) as websocket:
            await _init_terminal_session(websocket)

            if old_settings:
                tty.setraw(sys.stdin.fileno())

            resize_queue = asyncio.Queue()
            _setup_resize_handler(resize_queue)

            await _run_terminal_tasks(websocket, resize_queue)

    except OSError as e:
        print_error(f"Connection error: {e}")
    except Exception as e:
        print_error(f"WebSocket error: {e}")
    finally:
        _cleanup_terminal(old_settings)


async def _init_terminal_session(websocket):
    """Send initial terminal size and wait for server acknowledgment."""
    if sys.stdout.isatty():
        try:
            size = os.get_terminal_size()
            resize_msg = {"type": "resize", "rows": size.lines, "cols": size.columns}
            await websocket.send(json.dumps(resize_msg))
        except OSError:
            pass

    try:
        await asyncio.wait_for(websocket.recv(), timeout=3.0)
    except asyncio.TimeoutError:
        pass


def _setup_resize_handler(resize_queue: asyncio.Queue):
    """Set up SIGWINCH handler for terminal resize events."""

    def handle_resize(signum, frame):
        if sys.stdout.isatty():
            try:
                size = os.get_terminal_size()
                resize_queue.put_nowait((size.lines, size.columns))
            except Exception:
                pass

    if hasattr(signal, "SIGWINCH"):
        signal.signal(signal.SIGWINCH, handle_resize)


async def _run_terminal_tasks(websocket, resize_queue: asyncio.Queue):
    """Run terminal I/O tasks concurrently."""
    tasks = [
        asyncio.create_task(_receive_terminal_output(websocket)),
        asyncio.create_task(_send_terminal_input(websocket)),
        asyncio.create_task(_send_resize_events(websocket, resize_queue)),
    ]

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def _receive_terminal_output(websocket):
    """Receive messages from WebSocket and write to stdout."""
    from websockets.exceptions import (
        ConnectionClosed,
        ConnectionClosedError,
        ConnectionClosedOK,
    )

    try:
        while True:
            message_text = await websocket.recv()
            try:
                message = json.loads(message_text)
                match message.get("type"):
                    case "output" if message.get("data"):
                        os.write(
                            sys.stdout.fileno(),
                            message["data"].encode("utf-8", errors="replace"),
                        )
                    case "error" if message.get("data"):
                        os.write(
                            sys.stdout.fileno(),
                            f"\r\nERROR: {message['data']}\r\n".encode(),
                        )
            except json.JSONDecodeError:
                os.write(sys.stdout.fileno(), message_text.encode())
    except (ConnectionClosedOK, ConnectionClosedError, ConnectionClosed):
        pass


async def _send_terminal_input(websocket):
    """Read raw input from stdin and send to WebSocket."""
    from websockets.exceptions import (
        ConnectionClosed,
        ConnectionClosedError,
        ConnectionClosedOK,
    )

    try:
        while True:
            data = await asyncio.to_thread(lambda: os.read(sys.stdin.fileno(), 1024))
            if not data:
                break
            message = {"type": "input", "data": data.decode("utf-8", errors="replace")}
            await websocket.send(json.dumps(message))
    except (ConnectionClosed, ConnectionClosedOK, ConnectionClosedError):
        pass


async def _send_resize_events(websocket, resize_queue: asyncio.Queue):
    """Send terminal resize events from queue."""
    try:
        while True:
            rows, cols = await resize_queue.get()
            msg = {"type": "resize", "rows": rows, "cols": cols}
            await websocket.send(json.dumps(msg))
    except Exception:
        pass


def _cleanup_terminal(old_settings):
    """Restore terminal settings and reset signal handler."""
    if old_settings:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    if hasattr(signal, "SIGWINCH"):
        signal.signal(signal.SIGWINCH, signal.SIG_DFL)
    console.print("\r\n[dim]Disconnected.[/dim]")


# =============================================================================
# Tarball Management (hakuriver docker tar ...)
# =============================================================================


@tar_app.command("list")
def list_tarballs():
    """List available container tarballs."""
    try:
        tarballs = client.get_tarballs()

        if not tarballs:
            console.print("[yellow]No tarballs found.[/yellow]")
            return

        table = Table(title="Container Tarballs", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Latest Version", style="bold")
        table.add_column("Size")
        table.add_column("Versions", justify="right")

        for name, info in sorted(tarballs.items()):
            timestamp = info.get("latest_timestamp", 0)
            try:
                dt = datetime.fromtimestamp(timestamp)
                latest_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError, OverflowError):
                latest_str = str(timestamp)

            versions = info.get("all_versions", [])
            latest_size = versions[0].get("size_bytes", 0) if versions else 0

            table.add_row(
                name,
                latest_str,
                format_bytes(latest_size),
                str(len(versions)),
            )

        console.print(table)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@tar_app.command("create")
def create_tarball(
    container_name: Annotated[
        str, typer.Argument(help="Container name to create tarball from")
    ],
):
    """Create a container tarball from a host container."""
    try:
        console.print(
            f"[dim]Creating tarball from container '{container_name}'...[/dim]"
        )
        console.print("[dim]This may take a while...[/dim]")

        result = client.create_tarball(container_name)

        if result.get("message") or result.get("tarball_path"):
            print_success(f"Tarball created from container '{container_name}'.")
            if result.get("tarball_path"):
                console.print(f"[dim]Path: {result['tarball_path']}[/dim]")
            console.print(f"\n[bold]Usage:[/bold]")
            console.print(f"  Use with tasks: --container {container_name}")
        else:
            print_error(f"Failed to create tarball: {result}")
            raise typer.Exit(1)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@tar_app.command("delete")
def delete_tarball(
    name: Annotated[str, typer.Argument(help="Tarball name to delete")],
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Force deletion")
    ] = False,
):
    """Delete a container tarball."""
    try:
        if not force:
            confirm = typer.confirm(f"Delete tarball '{name}' (all versions)?")
            if not confirm:
                console.print("[dim]Cancelled.[/dim]")
                return

        result = client.delete_tarball(name)

        if result.get("message"):
            print_success(result["message"])
        else:
            print_error(f"Failed to delete tarball: {result}")
            raise typer.Exit(1)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


# =============================================================================
# Migration command (hakuriver docker container migrate)
# =============================================================================


@container_app.command("migrate")
def migrate_container_cmd(
    name: Annotated[str, typer.Argument(help="Legacy container name to migrate")],
):
    """Migrate a legacy container to the new naming convention.

    Renames container from '{name}' to 'kohakuriver-env-{name}'.
    This allows existing environment containers to be managed by HakuRiver.
    """
    try:
        console.print(f"[dim]Migrating container '{name}'...[/dim]")

        result = client.migrate_container(name)

        if result.get("message"):
            print_success(result["message"])
            console.print(f"\n[bold]Container renamed:[/bold]")
            console.print(f"  Old: {result.get('old_name')}")
            console.print(f"  New: {result.get('new_name')}")
            console.print(f"\n[bold]Next steps:[/bold]")
            console.print(f"  - List containers: hakuriver docker container list")
            console.print(
                f"  - Shell into container: hakuriver docker container shell {result.get('env_name')}"
            )
        else:
            print_error(f"Failed to migrate container: {result}")
            raise typer.Exit(1)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
