"""VPS management commands."""

import os
from typing import Annotated

import typer

from kohakuriver.cli import client
from kohakuriver.cli.formatters.vps import (
    format_vps_created,
    format_vps_detail,
    format_vps_table,
)
from kohakuriver.cli.output import console, print_error, print_success

app = typer.Typer(help="VPS management commands")


@app.command("list")
def list_vps(
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Show all VPS (including stopped)")
    ] = False,
):
    """List VPS instances."""
    try:
        vps_list = client.get_vps_list(active_only=not all_)

        if not vps_list:
            console.print("[yellow]No VPS instances found.[/yellow]")
            return

        table = format_vps_table(vps_list)
        console.print(table)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("status")
def vps_status(
    task_id: Annotated[str, typer.Argument(help="VPS Task ID")],
):
    """Get detailed status for a VPS."""
    try:
        vps = client.get_task_status(task_id)

        if not vps:
            print_error(f"VPS {task_id} not found.")
            raise typer.Exit(1)

        panel = format_vps_detail(vps)
        console.print(panel)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("create")
def create_vps(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Target node[:numa][::gpus]"),
    ] = None,
    cores: Annotated[int, typer.Option("--cores", "-c", help="CPU cores")] = 1,
    memory: Annotated[
        str | None, typer.Option("--memory", "-m", help="Memory limit (e.g., 4G)")
    ] = None,
    container: Annotated[
        str | None, typer.Option("--container", help="Container environment")
    ] = None,
    image: Annotated[
        str | None,
        typer.Option("--image", help="Docker registry image (e.g. ubuntu:22.04)"),
    ] = None,
    privileged: Annotated[
        bool, typer.Option("--privileged", help="Run with --privileged")
    ] = False,
    mount: Annotated[
        list[str] | None,
        typer.Option("--mount", help="Additional mounts (repeatable)"),
    ] = None,
    # SSH options (mutually exclusive)
    ssh: Annotated[
        bool,
        typer.Option("--ssh", help="Enable SSH server (default: disabled, TTY-only)"),
    ] = False,
    no_ssh_key: Annotated[
        bool,
        typer.Option("--no-ssh-key", help="SSH with passwordless root login"),
    ] = False,
    gen_ssh_key: Annotated[
        bool,
        typer.Option("--gen-ssh-key", help="SSH with generated keypair"),
    ] = False,
    public_key_file: Annotated[
        str | None,
        typer.Option("--public-key-file", help="SSH with public key from file"),
    ] = None,
    public_key_string: Annotated[
        str | None,
        typer.Option("--public-key-string", help="SSH with public key string"),
    ] = None,
    key_out_file: Annotated[
        str | None,
        typer.Option("--key-out-file", help="Output path for generated key"),
    ] = None,
):
    """Create a new VPS instance.

    By default, VPS is created without SSH (TTY-only mode, faster startup).
    Use --ssh or one of the SSH key options to enable SSH server.
    """
    from kohakuriver.utils.cli import parse_memory_string
    from kohakuriver.utils.ssh_key import (
        get_default_key_output_path,
        read_public_key_file,
    )

    if image and container:
        print_error("--image and --container are mutually exclusive")
        raise typer.Exit(1)

    try:
        # Validate mutually exclusive SSH options
        ssh_options = sum(
            [no_ssh_key, gen_ssh_key, bool(public_key_file), bool(public_key_string)]
        )
        if ssh_options > 1:
            print_error(
                "Only one of --no-ssh-key, --gen-ssh-key, --public-key-file, "
                "--public-key-string can be specified."
            )
            raise typer.Exit(1)

        # --ssh flag without specific key options implies try default keys or generate
        if ssh and ssh_options == 0:
            # Treat --ssh as "enable SSH with default key or generate"
            gen_ssh_key = True
            ssh_options = 1

        # Determine SSH key mode
        ssh_key_mode = "disabled"  # Default: no SSH, TTY-only
        public_key = None

        if no_ssh_key:
            ssh_key_mode = "none"
        elif gen_ssh_key:
            ssh_key_mode = "generate"
        elif public_key_string:
            ssh_key_mode = "upload"
            public_key = public_key_string.strip()
        elif public_key_file:
            ssh_key_mode = "upload"
            public_key = read_public_key_file(public_key_file)
        # If no SSH option specified, keep disabled (TTY-only mode)

        # Parse memory
        memory_bytes = None
        if memory:
            memory_bytes = parse_memory_string(memory)

        # Parse target for GPU IDs
        target_str = target
        gpu_ids = None
        if target and "::" in target:
            target_str, gpu_str = target.rsplit("::", 1)
            gpu_ids = [int(g.strip()) for g in gpu_str.split(",") if g.strip()]

        result = client.create_vps(
            ssh_key_mode=ssh_key_mode,
            public_key=public_key,
            cores=cores,
            memory_bytes=memory_bytes,
            target=target_str,
            container_name=container,
            registry_image=image,
            privileged=privileged if privileged else None,
            additional_mounts=mount,
            gpu_ids=gpu_ids,
        )

        if not result.get("task_id"):
            print_error("VPS creation failed - no task ID returned.")
            raise typer.Exit(1)

        # Display success panel
        panel = format_vps_created(result)
        console.print(panel)

        # Handle generated SSH key
        if ssh_key_mode == "generate" and result.get("ssh_private_key"):
            task_id = result["task_id"]
            out_path = key_out_file or get_default_key_output_path(task_id)
            out_path = os.path.expanduser(out_path)

            # Ensure directory exists
            ssh_dir = os.path.dirname(out_path)
            if ssh_dir:
                os.makedirs(ssh_dir, exist_ok=True)

            # Write private key
            with open(out_path, "w") as f:
                f.write(result["ssh_private_key"])
            os.chmod(out_path, 0o600)

            # Write public key
            if result.get("ssh_public_key"):
                pub_path = f"{out_path}.pub"
                with open(pub_path, "w") as f:
                    f.write(result["ssh_public_key"])
                os.chmod(pub_path, 0o644)

            console.print(f"\n[green]SSH private key saved to:[/green] {out_path}")
            console.print(f"[green]SSH public key saved to:[/green] {out_path}.pub")

    except ValueError as e:
        print_error(f"Invalid argument: {e}")
        raise typer.Exit(1)
    except FileNotFoundError as e:
        print_error(f"File not found: {e}")
        raise typer.Exit(1)
    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("stop")
def stop_vps(
    task_id: Annotated[str, typer.Argument(help="VPS Task ID to stop")],
):
    """Stop a VPS instance."""
    try:
        result = client.stop_vps(task_id)
        message = result.get("message", "VPS stop requested.")
        print_success(message)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("restart")
def restart_vps(
    task_id: Annotated[str, typer.Argument(help="VPS Task ID to restart")],
):
    """Restart a VPS instance.

    Useful when nvidia docker breaks (nvml error) or container becomes unresponsive.
    This will stop the current container and create a new one with the same configuration.
    """
    try:
        console.print(f"[dim]Restarting VPS {task_id}...[/dim]")
        result = client.restart_vps(task_id)
        message = result.get("message", "VPS restart requested.")
        print_success(message)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("pause")
def pause_vps(
    task_id: Annotated[str, typer.Argument(help="VPS Task ID to pause")],
):
    """Pause a VPS instance."""
    try:
        result = client.send_task_command(task_id, "pause")
        message = result.get("message", "Pause command sent.")
        print_success(message)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("resume")
def resume_vps(
    task_id: Annotated[str, typer.Argument(help="VPS Task ID to resume")],
):
    """Resume a paused VPS."""
    try:
        result = client.send_task_command(task_id, "resume")
        message = result.get("message", "Resume command sent.")
        print_success(message)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("connect")
def connect_vps(
    task_id: Annotated[str, typer.Argument(help="VPS Task ID")],
    key_file: Annotated[
        str | None,
        typer.Option("--key", "-i", help="SSH private key file"),
    ] = None,
):
    """SSH connect to a VPS instance.

    For VPS created without SSH (TTY-only mode), use 'kohakuriver terminal <task_id>' instead.
    """
    import subprocess

    from kohakuriver.utils.ssh_key import get_default_key_output_path

    try:
        vps = client.get_task_status(task_id)

        if not vps:
            print_error(f"VPS {task_id} not found.")
            raise typer.Exit(1)

        if vps.get("status") != "running":
            print_error(f"VPS is not running (status: {vps.get('status')})")
            raise typer.Exit(1)

        ssh_port = vps.get("ssh_port")
        if not ssh_port:
            print_error(
                "VPS has no SSH port (TTY-only mode).\n"
                f"Use 'kohakuriver terminal {task_id}' to connect via TTY instead."
            )
            raise typer.Exit(1)

        node = vps.get("assigned_node")
        if isinstance(node, dict):
            node = node.get("hostname")
        if not node:
            print_error("VPS has no assigned node.")
            raise typer.Exit(1)

        # Build SSH command
        ssh_cmd = ["ssh"]

        # Try to find key file
        if key_file:
            ssh_cmd.extend(["-i", os.path.expanduser(key_file)])
        else:
            # Try default generated key
            default_key = get_default_key_output_path(task_id)
            if os.path.exists(os.path.expanduser(default_key)):
                ssh_cmd.extend(["-i", os.path.expanduser(default_key)])

        ssh_cmd.extend(["-p", str(ssh_port), f"root@{node}"])

        console.print(f"[dim]Connecting: {' '.join(ssh_cmd)}[/dim]")

        # Execute SSH
        subprocess.run(ssh_cmd)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
