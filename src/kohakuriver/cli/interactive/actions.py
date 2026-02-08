"""TUI action methods — interactive dialogs, kill/stop, shell, output viewing.

Mixed into TUIApp via inheritance.
"""

import os
import shlex
import subprocess

from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from kohakuriver.cli import client
from kohakuriver.cli.interactive.renderers import View
from kohakuriver.cli.output import format_bytes


class TUIActions:
    """Mixin providing action methods for TUIApp.

    Expects the host class to have: console, live, old_settings, detail_item,
    current_view, previous_view, status_message, error_message, nodes, tarballs,
    fetch_data(), _restore_terminal(), _setup_terminal().
    """

    def _interactive_prompt(
        self, title: str, prompts: list[tuple[str, str, str]]
    ) -> dict | None:
        """
        Show interactive prompts outside of Live mode.

        Args:
            title: Dialog title
            prompts: List of (field_name, prompt_text, default_value)

        Returns:
            Dict of field_name -> value, or None if cancelled
        """
        # Exit Live mode temporarily
        if self.live:
            self.live.stop()
        self._restore_terminal()

        try:
            self.console.clear()
            self.console.print(Panel(f"[bold]{title}[/bold]", border_style="cyan"))
            self.console.print("[dim]Press Ctrl+C to cancel[/dim]\n")

            result = {}
            for field_name, prompt_text, default in prompts:
                try:
                    value = Prompt.ask(
                        prompt_text, default=default if default else None
                    )
                    result[field_name] = value
                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Cancelled.[/yellow]")
                    return None

            return result

        finally:
            # Re-enter Live mode
            self._setup_terminal()
            if self.live:
                self.live.start()

    def _create_task_interactive(self):
        """Interactive task creation dialog."""
        result = self._interactive_prompt(
            "Create New Task",
            [
                ("command", "Command (e.g., python, echo)", ""),
                ("arguments", "Arguments (space-separated)", ""),
                ("cores", "CPU cores (0=no limit)", "0"),
                ("target", "Target node (optional)", ""),
                ("container", "Container environment (optional)", ""),
            ],
        )

        if not result:
            return

        command = (result.get("command") or "").strip()
        if not command:
            self.error_message = "Command is required"
            return

        # Parse arguments - split by spaces, respecting quotes
        args_str = (result.get("arguments") or "").strip()
        if args_str:
            try:
                arguments = shlex.split(args_str)
            except ValueError:
                # Fallback to simple split if shlex fails
                arguments = args_str.split()
        else:
            arguments = []

        try:
            cores_str = result.get("cores") or "0"
            cores = int(cores_str)
        except ValueError:
            cores = 0

        target = (result.get("target") or "").strip() or None
        container = (result.get("container") or "").strip() or None

        try:
            response = client.submit_task(
                command=command,
                arguments=arguments,
                cores=cores,
                targets=[target] if target else None,
                container_name=container,
            )
            task_ids = response.get("task_ids", [])
            if task_ids:
                self.status_message = f"Task created: {task_ids[0]}"
            else:
                self.error_message = "Failed to create task"
        except client.APIError as e:
            self.error_message = str(e)

        self.fetch_data()

    def _create_vps_interactive(self):
        """Interactive VPS creation dialog with GPU selection support."""
        # Exit Live mode temporarily
        if self.live:
            self.live.stop()
        self._restore_terminal()

        try:
            self.console.clear()
            self.console.print(
                Panel("[bold]Create New VPS[/bold]", border_style="cyan")
            )
            self.console.print("[dim]Press Ctrl+C to cancel[/dim]\n")

            # Get nodes with GPU info
            nodes_with_gpus = [
                n
                for n in self.nodes
                if n.get("status") == "online"
                and n.get("gpu_info")
                and len(n.get("gpu_info", [])) > 0
            ]
            online_nodes = [n for n in self.nodes if n.get("status") == "online"]

            # Step 1: Selection mode (Node or GPU)
            self.console.print("[bold cyan]Step 1: Target Selection Mode[/bold cyan]")
            if nodes_with_gpus:
                self.console.print("  [1] Select by Node (CPU/NUMA targeting)")
                self.console.print("  [2] Select by GPU (GPU targeting)")
                try:
                    mode = Prompt.ask("Selection mode", choices=["1", "2"], default="1")
                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Cancelled.[/yellow]")
                    return
            else:
                mode = "1"
                self.console.print(
                    "  [dim]No nodes with GPUs available. Using node selection.[/dim]"
                )

            target = None
            gpu_ids = None

            if mode == "2":
                target, gpu_ids = self._vps_select_gpus(nodes_with_gpus)
                if target is None and gpu_ids is None:
                    return  # cancelled
            else:
                target = self._vps_select_node(online_nodes)
                if target is False:
                    return  # cancelled (None means auto-select)

            # Step 3: Basic configuration
            self.console.print("\n[bold cyan]Step 3: Configuration[/bold cyan]")
            try:
                cores_str = Prompt.ask("CPU cores (0=no limit)", default="0")
                cores = int(cores_str) if cores_str.isdigit() else 0

                container = Prompt.ask("Container environment (optional)", default="")
                container = container.strip() or None

                ssh_key_mode = Prompt.ask(
                    "SSH key mode",
                    choices=["none", "upload", "generate"],
                    default="generate",
                )
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Cancelled.[/yellow]")
                return

            # Handle SSH key upload
            public_key = self._vps_resolve_ssh_key(ssh_key_mode)
            if public_key is False:
                # Fallback to generate
                ssh_key_mode = "generate"
                public_key = None

            # Confirmation
            self.console.print("\n[bold cyan]Summary:[/bold cyan]")
            self.console.print(f"  Target: {target or 'Auto'}")
            if gpu_ids:
                self.console.print(f"  GPUs: {gpu_ids}")
            self.console.print(f"  CPU cores: {cores}")
            self.console.print(f"  Container: {container or 'Default'}")
            self.console.print(f"  SSH key mode: {ssh_key_mode}")

            try:
                if not Confirm.ask("\nCreate VPS?", default=True):
                    self.console.print("[yellow]Cancelled.[/yellow]")
                    return
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Cancelled.[/yellow]")
                return

            # Create VPS
            self._vps_submit_and_report(
                ssh_key_mode=ssh_key_mode,
                public_key=public_key,
                cores=cores,
                target=target,
                container=container,
                gpu_ids=gpu_ids,
            )

        finally:
            # Re-enter Live mode
            self._setup_terminal()
            if self.live:
                self.live.start()

        self.fetch_data()

    def _vps_select_gpus(self, nodes_with_gpus: list[dict]) -> tuple:
        """GPU selection sub-step. Returns (target, gpu_ids) or (None, None) if cancelled."""
        self.console.print("\n[bold cyan]Step 2: Select GPUs[/bold cyan]")
        self.console.print(
            "[dim]GPUs must be on the same node. Select node first, then GPUs.[/dim]\n"
        )

        # Show nodes with GPUs
        for i, node in enumerate(nodes_with_gpus, 1):
            hostname = node.get("hostname", "unknown")
            gpu_info = node.get("gpu_info", [])
            self.console.print(f"  [{i}] {hostname} ({len(gpu_info)} GPUs)")

        try:
            node_choice = Prompt.ask(
                "Select node",
                choices=[str(i) for i in range(1, len(nodes_with_gpus) + 1)],
                default="1",
            )
            selected_node = nodes_with_gpus[int(node_choice) - 1]
        except (KeyboardInterrupt, ValueError, IndexError):
            self.console.print("\n[yellow]Cancelled.[/yellow]")
            return None, None

        target = selected_node.get("hostname")
        gpu_info = selected_node.get("gpu_info", [])

        # Show GPUs on selected node
        self.console.print(f"\n[bold]GPUs on {target}:[/bold]")
        gpu_table = Table(show_header=True, header_style="bold")
        gpu_table.add_column("ID", width=4)
        gpu_table.add_column("Name")
        gpu_table.add_column("Memory")
        gpu_table.add_column("Util")
        gpu_table.add_column("Temp")

        for gpu in gpu_info:
            gpu_id = gpu.get("gpu_id", 0)
            name = gpu.get("name", "Unknown")
            mem_total = gpu.get("memory_total_mib", 0)
            gpu_util = gpu.get("gpu_utilization", "?")
            temp = gpu.get("temperature", "?")
            gpu_table.add_row(
                str(gpu_id),
                name,
                f"{mem_total} MiB",
                f"{gpu_util}%",
                f"{temp}°C",
            )
        self.console.print(gpu_table)

        # Select GPUs
        gpu_id_list = [str(gpu.get("gpu_id", i)) for i, gpu in enumerate(gpu_info)]
        try:
            gpu_selection = Prompt.ask(
                "Select GPU IDs (comma-separated, e.g., 0,1)",
                default=gpu_id_list[0] if gpu_id_list else "0",
            )
            gpu_ids = [
                int(g.strip()) for g in gpu_selection.split(",") if g.strip().isdigit()
            ]
            if not gpu_ids:
                self.console.print(
                    "[yellow]No valid GPU IDs. Using first GPU.[/yellow]"
                )
                gpu_ids = [int(gpu_id_list[0])] if gpu_id_list else [0]
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Cancelled.[/yellow]")
            return None, None

        return target, gpu_ids

    def _vps_select_node(self, online_nodes: list[dict]):
        """Node selection sub-step. Returns hostname, None for auto, or False if cancelled."""
        self.console.print(
            "\n[bold cyan]Step 2: Select Target Node (optional)[/bold cyan]"
        )
        if online_nodes:
            self.console.print("  [0] Auto-select (let scheduler decide)")
            for i, node in enumerate(online_nodes, 1):
                hostname = node.get("hostname", "unknown")
                cores = node.get("total_cores", 0)
                mem = format_bytes(node.get("total_memory", 0))
                self.console.print(f"  [{i}] {hostname} ({cores} cores, {mem})")

            try:
                node_choice = Prompt.ask("Select node", default="0")
                if node_choice != "0":
                    try:
                        idx = int(node_choice) - 1
                        if 0 <= idx < len(online_nodes):
                            return online_nodes[idx].get("hostname")
                    except ValueError:
                        # Treat as hostname
                        return node_choice if node_choice else None
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Cancelled.[/yellow]")
                return False
        else:
            self.console.print("  [dim]No online nodes available.[/dim]")

        return None

    def _vps_resolve_ssh_key(self, ssh_key_mode: str) -> str | None | bool:
        """Resolve SSH public key. Returns key string, None, or False if fallback needed."""
        if ssh_key_mode != "upload":
            return None

        default_keys = [
            os.path.expanduser("~/.ssh/id_ed25519.pub"),
            os.path.expanduser("~/.ssh/id_rsa.pub"),
        ]
        for key_path in default_keys:
            if os.path.exists(key_path):
                try:
                    with open(key_path) as f:
                        public_key = f.read().strip()
                    self.console.print(f"[green]Using key: {key_path}[/green]")
                    return public_key
                except Exception:
                    continue

        self.console.print("[red]No SSH key found. Switching to generate mode.[/red]")
        return False

    def _vps_submit_and_report(self, **kwargs):
        """Submit VPS creation and report results."""
        ssh_key_mode = kwargs["ssh_key_mode"]
        gpu_ids = kwargs.get("gpu_ids")

        self.console.print("\n[dim]Creating VPS...[/dim]")
        try:
            response = client.create_vps(
                ssh_key_mode=ssh_key_mode,
                public_key=kwargs.get("public_key"),
                cores=kwargs.get("cores", 0),
                target=kwargs.get("target"),
                container_name=kwargs.get("container"),
                gpu_ids=gpu_ids,
            )

            task_id = response.get("task_id")
            if task_id:
                ssh_port = response.get("ssh_port", "?")
                self.status_message = f"VPS created: {task_id} (SSH port: {ssh_port})"

                # Save generated key if applicable
                if ssh_key_mode == "generate" and response.get("ssh_private_key"):
                    key_dir = os.path.expanduser("~/.ssh/hakuriver")
                    os.makedirs(key_dir, exist_ok=True)
                    key_path = os.path.join(key_dir, f"vps_{task_id}")

                    with open(key_path, "w") as f:
                        f.write(response["ssh_private_key"])
                    os.chmod(key_path, 0o600)

                    if response.get("ssh_public_key"):
                        with open(f"{key_path}.pub", "w") as f:
                            f.write(response["ssh_public_key"])

                    self.status_message += f" Key saved: {key_path}"

                self.console.print("[green]VPS created successfully![/green]")
                self.console.print(f"  Task ID: {task_id}")
                self.console.print(f"  SSH Port: {ssh_port}")
                if gpu_ids:
                    self.console.print(f"  GPUs: {gpu_ids}")
            else:
                self.error_message = "Failed to create VPS"
                self.console.print("[red]Failed to create VPS[/red]")

        except client.APIError as e:
            self.error_message = str(e)
            self.console.print(f"[red]Error: {e}[/red]")

        # Wait for user acknowledgment
        self.console.print("\n[dim]Press Enter to continue...[/dim]")
        try:
            input()
        except Exception:
            pass

    def _handle_kill(self) -> None:
        """Handle kill/stop action."""
        if not self.detail_item:
            return

        task_id = str(self.detail_item.get("task_id", ""))
        if not task_id:
            return

        try:
            if self.current_view == View.TASK_DETAIL:
                client.kill_task(task_id)
                self.status_message = f"Task {task_id[-12:]} killed"
            elif self.current_view == View.VPS_DETAIL:
                client.stop_vps(task_id)
                self.status_message = f"VPS {task_id[-12:]} stopped"

            # Go back and refresh
            self.current_view = self.previous_view
            self.detail_item = None
            self.fetch_data()
        except client.APIError as e:
            self.error_message = str(e)

    def _handle_new(self) -> None:
        """Handle new task/VPS/container creation."""
        if self.current_view == View.TASKS:
            self._create_task_interactive()
        elif self.current_view == View.VPS:
            self._create_vps_interactive()
        elif self.current_view == View.DOCKER:
            self._create_container_interactive()

    def _show_full_output(self, output_type: str) -> None:
        """Show full stdout or stderr in a pager-like view."""
        if not self.detail_item:
            return

        task_id = str(self.detail_item.get("task_id", ""))
        if not task_id:
            return

        # Exit Live mode temporarily
        if self.live:
            self.live.stop()
        self._restore_terminal()

        try:
            self.console.clear()

            # Fetch the content
            try:
                if output_type == "stdout":
                    content = client.get_task_stdout(task_id)
                    title = f"Task {task_id[-12:]} - stdout"
                else:
                    content = client.get_task_stderr(task_id)
                    title = f"Task {task_id[-12:]} - stderr"
            except client.APIError as e:
                content = f"Error fetching {output_type}: {e}"
                title = "Error"

            if not content:
                content = f"No {output_type} output"

            # Display with paging
            self.console.print(Panel(title, style="bold cyan"))
            self.console.print()

            # Print content
            self.console.print(content)

            self.console.print()
            self.console.print("[dim]Press Enter to return...[/dim]")
            input()

        finally:
            # Re-enter Live mode
            self._setup_terminal()
            if self.live:
                self.live.start()

    def _create_container_interactive(self):
        """Interactive container creation dialog."""
        result = self._interactive_prompt(
            "Create New Environment Container",
            [
                ("image", "Docker image (e.g., python:3.11, ubuntu:22.04)", ""),
                ("name", "Environment name", ""),
            ],
        )

        if not result:
            return

        image = (result.get("image") or "").strip()
        name = (result.get("name") or "").strip()

        if not image:
            self.error_message = "Image is required"
            return

        if not name:
            self.error_message = "Name is required"
            return

        try:
            response = client.create_host_container(image, name)
            if response.get("container_id") or response.get("message"):
                self.status_message = f"Container '{name}' created"
            else:
                self.error_message = "Failed to create container"
        except client.APIError as e:
            self.error_message = str(e)

        self.fetch_data()

    def _docker_shell(self):
        """Open shell in container - exits TUI and runs docker exec."""
        if not self.detail_item:
            return

        env_name = self.detail_item.get("env_name", self.detail_item.get("name", ""))
        container_name = self.detail_item.get("name", "")

        if not container_name:
            self.error_message = "No container name"
            return

        # Exit TUI and run shell
        if self.live:
            self.live.stop()
        self._restore_terminal()

        try:
            self.console.clear()
            self.console.print(
                f"[bold cyan]Opening shell in container: {env_name}[/bold cyan]"
            )
            self.console.print(f"[dim]Container: {container_name}[/dim]")
            self.console.print("[dim]Type 'exit' to return to TUI...[/dim]\n")

            # Run docker exec interactively
            subprocess.run(
                ["docker", "exec", "-it", container_name, "/bin/bash"],
                check=False,
            )

            self.console.print("\n[dim]Press Enter to return to TUI...[/dim]")
            input()

        finally:
            self._setup_terminal()
            if self.live:
                self.live.start()

    def _docker_create_tar(self):
        """Create tarball from container."""
        if not self.detail_item:
            return

        env_name = self.detail_item.get("env_name", self.detail_item.get("name", ""))

        if not env_name:
            self.error_message = "No environment name"
            return

        try:
            self.status_message = f"Creating tarball for '{env_name}'..."
            response = client.create_tarball(env_name)

            if response.get("tarball_path") or response.get("message"):
                self.status_message = f"Tarball created for '{env_name}'"
            else:
                self.error_message = "Failed to create tarball"

            self.fetch_data()
        except client.APIError as e:
            self.error_message = str(e)
