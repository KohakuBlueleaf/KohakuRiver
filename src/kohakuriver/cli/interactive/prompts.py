"""Interactive prompts for complex commands."""

import os

from rich.prompt import Confirm, IntPrompt, Prompt

from kohakuriver.cli import client
from kohakuriver.cli.formatters.node import format_node_table
from kohakuriver.cli.formatters.vps import format_vps_created
from kohakuriver.cli.output import console, print_error, print_success
from kohakuriver.utils.cli import parse_memory_string
from kohakuriver.utils.ssh_key import read_public_key_file, save_generated_ssh_keys


def interactive_task_submit() -> dict | None:
    """Interactive task submission wizard."""
    console.print("[bold]Task Submission Wizard[/bold]\n")

    # Command
    command = Prompt.ask("Command to execute")
    if not command:
        print_error("Command is required.")
        return None

    # Arguments
    args_str = Prompt.ask("Arguments (space-separated)", default="")
    args = args_str.split() if args_str else []

    # Resources
    cores = IntPrompt.ask("CPU cores", default=1)
    memory = Prompt.ask("Memory limit (e.g., 4G, leave empty for no limit)", default="")

    # Target node
    try:
        nodes = client.get_nodes()
        if nodes:
            console.print("\n[bold]Available nodes:[/bold]")
            table = format_node_table(nodes)
            console.print(table)

        target = Prompt.ask(
            "\nTarget node (or leave empty for auto)",
            default="",
        )
    except client.APIError:
        target = ""

    # Container
    container = Prompt.ask(
        "Container environment (leave empty for default)",
        default="",
    )

    # Confirm
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Command: {command}")
    console.print(f"  Arguments: {args}")
    console.print(f"  Cores: {cores}")
    console.print(f"  Memory: {memory or 'No limit'}")
    console.print(f"  Target: {target or 'Auto'}")
    console.print(f"  Container: {container or 'Default'}")

    if not Confirm.ask("\nSubmit task?"):
        console.print("[dim]Cancelled.[/dim]")
        return None

    # Parse memory
    memory_bytes = None
    if memory:
        try:
            memory_bytes = parse_memory_string(memory)
        except ValueError as e:
            print_error(f"Invalid memory format: {e}")
            return None

    # Submit
    try:
        result = client.submit_task(
            command=command,
            args=args,
            cores=cores,
            memory_bytes=memory_bytes,
            targets=[target] if target else None,
            container_name=container or None,
        )

        task_ids = result.get("task_ids", [])
        if task_ids:
            print_success(f"Task(s) submitted: {', '.join(map(str, task_ids))}")
            return result
        else:
            print_error("No task IDs returned.")
            return None

    except client.APIError as e:
        print_error(str(e))
        return None


def _prompt_ssh_config() -> tuple[str, str | None] | None:
    """Interactively prompt for SSH key mode and optional public key.

    Returns:
        A ``(ssh_key_mode, public_key)`` tuple, or *None* if the user
        provides an invalid key file and the wizard should be aborted.
    """
    console.print("[bold]SSH Key Options:[/bold]")
    console.print("  1. Use existing key (from ~/.ssh/)")
    console.print("  2. Generate new keypair")
    console.print("  3. No SSH key (passwordless root)")

    key_choice = Prompt.ask("Choose option", choices=["1", "2", "3"], default="1")

    ssh_key_mode = "upload"
    public_key = None

    if key_choice == "1":
        key_path = Prompt.ask(
            "Public key path",
            default="~/.ssh/id_ed25519.pub",
        )
        key_path = os.path.expanduser(key_path)

        if not os.path.exists(key_path):
            print_error(f"Key file not found: {key_path}")
            return None

        try:
            public_key = read_public_key_file(key_path)
        except Exception as e:
            print_error(f"Failed to read key: {e}")
            return None

    elif key_choice == "2":
        ssh_key_mode = "generate"
    else:
        ssh_key_mode = "none"

    return ssh_key_mode, public_key


def _prompt_vps_resources() -> tuple[int, str, str, str]:
    """Interactively prompt for VPS resource configuration.

    Returns:
        A ``(cores, memory, target, container)`` tuple where *memory*,
        *target*, and *container* are raw strings (possibly empty).
    """
    cores = IntPrompt.ask("CPU cores", default=1)
    memory = Prompt.ask("Memory limit (e.g., 4G, leave empty for no limit)", default="")

    # Target node
    try:
        nodes = client.get_nodes()
        if nodes:
            console.print("\n[bold]Available nodes:[/bold]")
            table = format_node_table(nodes)
            console.print(table)

        target = Prompt.ask(
            "\nTarget node (or leave empty for auto)",
            default="",
        )
    except client.APIError:
        target = ""

    # Container
    container = Prompt.ask(
        "Container environment (leave empty for default)",
        default="",
    )

    return cores, memory, target, container


def interactive_vps_create() -> dict | None:
    """Interactive VPS creation wizard."""
    console.print("[bold]VPS Creation Wizard[/bold]\n")

    # SSH key mode
    ssh_config = _prompt_ssh_config()
    if ssh_config is None:
        return None
    ssh_key_mode, public_key = ssh_config

    # Resources
    cores, memory, target, container = _prompt_vps_resources()

    # Confirm
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  SSH Key Mode: {ssh_key_mode}")
    console.print(f"  Cores: {cores}")
    console.print(f"  Memory: {memory or 'No limit'}")
    console.print(f"  Target: {target or 'Auto'}")
    console.print(f"  Container: {container or 'Default'}")

    if not Confirm.ask("\nCreate VPS?"):
        console.print("[dim]Cancelled.[/dim]")
        return None

    # Parse memory
    memory_bytes = None
    if memory:
        try:
            memory_bytes = parse_memory_string(memory)
        except ValueError as e:
            print_error(f"Invalid memory format: {e}")
            return None

    # Create VPS
    try:
        result = client.create_vps(
            ssh_key_mode=ssh_key_mode,
            public_key=public_key,
            cores=cores,
            memory_bytes=memory_bytes,
            target=target or None,
            container_name=container or None,
        )

        if result.get("task_id"):
            panel = format_vps_created(result)
            console.print(panel)

            # Handle generated key
            if ssh_key_mode == "generate":
                save_generated_ssh_keys(result, console=console)

            return result
        else:
            print_error("VPS creation failed.")
            return None

    except client.APIError as e:
        print_error(str(e))
        return None
