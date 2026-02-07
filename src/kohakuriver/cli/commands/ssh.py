"""SSH commands."""

import asyncio
import os
import sys
from typing import Annotated

import typer

from kohakuriver.cli import client, config as cli_config
from kohakuriver.cli.output import console, print_error, print_success
from kohakuriver.ssh_proxy.client import ClientProxy
from kohakuriver.utils.ssh_key import get_default_key_output_path

app = typer.Typer(help="SSH commands")


async def _run_ssh_with_proxy(
    task_id: str,
    host: str,
    proxy_port: int,
    local_port: int,
    user: str,
    key_file: str | None,
):
    """
    Start the client proxy server and the local SSH subprocess concurrently.
    """
    proxy = ClientProxy(task_id, host, proxy_port, local_port, user)
    if not local_port:
        local_port = proxy.local_port

    # Start the local proxy server as a background task
    proxy_server_task = asyncio.create_task(proxy.start_local_server())

    # Wait briefly for the server to start
    await asyncio.sleep(0.1)

    # Construct the SSH command
    local_bind_address = "127.0.0.1"
    ssh_cmd = ["ssh"]

    # Add key file if provided
    if key_file:
        ssh_cmd.extend(["-i", os.path.expanduser(key_file)])

    ssh_cmd.extend(
        [
            "-p",
            str(local_port),
            f"{user}@{local_bind_address}",
        ]
    )

    console.print(f"[dim]Connecting via proxy: {' '.join(ssh_cmd)}[/dim]")

    ssh_process = None
    returncode = 1

    try:
        ssh_process = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        returncode = await ssh_process.wait()

    except FileNotFoundError:
        print_error(
            "SSH command not found. Make sure 'ssh' is installed and in your PATH."
        )
        returncode = 127

    except Exception as e:
        print_error(f"Error running SSH subprocess: {e}")
        returncode = 1

    finally:
        proxy.close()
        # Cancel the proxy server task since serve_forever doesn't exit on close
        proxy_server_task.cancel()
        await asyncio.gather(proxy_server_task, return_exceptions=True)

    return returncode


@app.command("connect")
def ssh_connect(
    task_id: Annotated[str, typer.Argument(help="VPS Task ID")],
    key_file: Annotated[
        str | None,
        typer.Option("--key", "-i", help="SSH private key file"),
    ] = None,
    proxy_port: Annotated[
        int | None,
        typer.Option("--proxy-port", help="Host SSH proxy port"),
    ] = None,
    local_port: Annotated[
        int,
        typer.Option("--local-port", help="Local port for client proxy (0=auto)"),
    ] = 0,
    user: Annotated[
        str,
        typer.Option("--user", "-u", help="SSH user"),
    ] = "root",
):
    """SSH connect to a VPS instance via the host proxy."""
    try:
        vps = client.get_task_status(task_id)

        if not vps:
            print_error(f"VPS {task_id} not found.")
            raise typer.Exit(1)

        if vps.get("task_type") != "vps":
            print_error(
                f"Task {task_id} is not a VPS task (type: {vps.get('task_type')})"
            )
            raise typer.Exit(1)

        if vps.get("status") != "running":
            print_error(f"VPS is not running (status: {vps.get('status')})")
            raise typer.Exit(1)

        # Try to find key file if not provided
        if not key_file:
            default_key = get_default_key_output_path(task_id)
            if os.path.exists(os.path.expanduser(default_key)):
                key_file = default_key

        # Get host address and proxy port
        host = cli_config.HOST_ADDRESS
        ssh_proxy_port = proxy_port or cli_config.HOST_SSH_PROXY_PORT

        console.print(f"[dim]Using SSH proxy at {host}:{ssh_proxy_port}[/dim]")

        # Run the SSH with proxy
        returncode = asyncio.run(
            _run_ssh_with_proxy(
                task_id=task_id,
                host=host,
                proxy_port=ssh_proxy_port,
                local_port=local_port,
                user=user,
                key_file=key_file,
            )
        )

        raise typer.Exit(returncode)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("config")
def ssh_config(
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output file (default: stdout)"),
    ] = None,
):
    """Generate SSH config entries for all VPS instances.

    Note: These configs connect through the host SSH proxy,
    which is the recommended way to connect to VPS instances.
    """
    try:
        vps_list = client.get_vps_list(active_only=True)

        if not vps_list:
            console.print("[yellow]No active VPS instances found.[/yellow]")
            return

        # Get host address and proxy port for ProxyCommand
        host = cli_config.HOST_ADDRESS
        proxy_port = cli_config.HOST_SSH_PROXY_PORT

        config_lines = [
            "# HakuRiver VPS SSH Config",
            "# Generated automatically",
            f"# Uses SSH proxy at {host}:{proxy_port}",
            "",
        ]

        for vps in vps_list:
            if vps.get("status") != "running":
                continue

            task_id = vps.get("task_id")

            if not task_id:
                continue

            default_key = get_default_key_output_path(task_id)

            # Generate config that uses hakuriver ssh connect
            config_lines.extend(
                [
                    f"Host kohakuriver-vps-{task_id}",
                    f"    # Use: hakuriver ssh connect {task_id}",
                    f"    HostName 127.0.0.1",
                    f"    User root",
                    f"    IdentityFile {default_key}",
                    f"    StrictHostKeyChecking no",
                    f"    UserKnownHostsFile /dev/null",
                    "",
                ]
            )

        config_content = "\n".join(config_lines)

        if output:
            output_path = os.path.expanduser(output)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w") as f:
                f.write(config_content)
            print_success(f"SSH config written to: {output_path}")
        else:
            console.print(config_content)

        console.print(
            "\n[yellow]Note: Use 'hakuriver ssh connect <task_id>' to connect via proxy.[/yellow]"
        )

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
