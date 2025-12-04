"""
Modal dialogs for creating tasks, VPS, and containers.
"""

import os
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Grid
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    Select,
    Static,
    RadioButton,
    RadioSet,
    Checkbox,
)

from kohakuriver.cli.tui.dashboard.styles import format_bytes


class CreateTaskModal(ModalScreen[dict | None]):
    """Modal dialog for creating a new task."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    CreateTaskModal {
        align: center middle;
    }

    #task-dialog {
        width: 70;
        height: auto;
        max-height: 90%;
        border: thick #00d4ff;
        background: #1a1a2e;
        padding: 1 2;
    }

    #task-dialog .title {
        text-style: bold;
        text-align: center;
        width: 100%;
        padding-bottom: 1;
        color: #00d4ff;
    }

    #task-dialog .field-label {
        margin-top: 1;
        color: #888;
    }

    #task-dialog Input {
        width: 100%;
        margin-bottom: 0;
    }

    #task-dialog Select {
        width: 100%;
    }

    #task-dialog .buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    #task-dialog Button {
        margin: 0 1;
    }

    #task-dialog .hint {
        color: #666;
        text-style: italic;
    }
    """

    def __init__(
        self,
        nodes: list[dict] | None = None,
        containers: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.available_nodes = nodes or []
        self.available_containers = containers or []

    def compose(self) -> ComposeResult:
        with Vertical(id="task-dialog"):
            yield Static("Create New Task", classes="title")

            yield Label("Command *", classes="field-label")
            yield Input(placeholder="e.g., python, bash, echo", id="command-input")

            yield Label("Arguments", classes="field-label")
            yield Input(placeholder="e.g., script.py --arg value", id="args-input")
            yield Static("(space-separated, supports quotes)", classes="hint")

            yield Label("CPU Cores (0 = no limit)", classes="field-label")
            yield Input(placeholder="0", id="cores-input", type="integer")

            yield Label("Target Node (optional)", classes="field-label")
            node_options = [("Auto-select", "")] + [
                (n.get("hostname", ""), n.get("hostname", ""))
                for n in self.available_nodes
                if n.get("status") == "online"
            ]
            yield Select(node_options, id="node-select", allow_blank=False, value="")

            yield Label("Container Environment (optional)", classes="field-label")
            container_options = [("Default", "")] + [
                (c, c) for c in self.available_containers
            ]
            yield Select(
                container_options, id="container-select", allow_blank=False, value=""
            )

            with Horizontal(classes="buttons"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    @on(Button.Pressed, "#create-btn")
    def on_create(self) -> None:
        """Handle create button."""
        command = self.query_one("#command-input", Input).value.strip()
        if not command:
            self.notify("Command is required", severity="error")
            return

        args_str = self.query_one("#args-input", Input).value.strip()
        cores_str = self.query_one("#cores-input", Input).value.strip()
        node_select = self.query_one("#node-select", Select)
        container_select = self.query_one("#container-select", Select)

        # Parse arguments
        arguments = []
        if args_str:
            import shlex

            try:
                arguments = shlex.split(args_str)
            except ValueError:
                arguments = args_str.split()

        # Parse cores
        try:
            cores = int(cores_str) if cores_str else 0
        except ValueError:
            cores = 0

        result = {
            "command": command,
            "arguments": arguments,
            "cores": cores,
            "target": node_select.value if node_select.value else None,
            "container": container_select.value if container_select.value else None,
        }

        self.dismiss(result)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        """Handle cancel button."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(None)


class CreateVPSModal(ModalScreen[dict | None]):
    """Modal dialog for creating a new VPS."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    CreateVPSModal {
        align: center middle;
    }

    #vps-dialog {
        width: 80;
        height: auto;
        max-height: 90%;
        border: thick #ff00ff;
        background: #1a1a2e;
        padding: 1 2;
    }

    #vps-dialog .title {
        text-style: bold;
        text-align: center;
        width: 100%;
        padding-bottom: 1;
        color: #ff00ff;
    }

    #vps-dialog .section-title {
        text-style: bold;
        margin-top: 1;
        color: #00d4ff;
        border-bottom: solid #333;
    }

    #vps-dialog .field-label {
        margin-top: 1;
        color: #888;
    }

    #vps-dialog Input {
        width: 100%;
    }

    #vps-dialog Select {
        width: 100%;
    }

    #vps-dialog RadioSet {
        height: auto;
        layout: horizontal;
    }

    #vps-dialog .buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    #vps-dialog Button {
        margin: 0 1;
    }

    #vps-dialog .hint {
        color: #666;
        text-style: italic;
    }

    #vps-dialog #gpu-info {
        height: auto;
        max-height: 10;
        border: solid #333;
        padding: 0 1;
        margin-top: 1;
        overflow-y: auto;
    }
    """

    def __init__(
        self,
        nodes: list[dict] | None = None,
        containers: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.available_nodes = nodes or []
        self.available_containers = containers or []
        self.selected_node: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="vps-dialog"):
            yield Static("Create New VPS", classes="title")

            # Target selection
            yield Static("Target Selection", classes="section-title")

            yield Label("Target Node (optional)", classes="field-label")
            node_options = [("Auto-select", "")] + [
                (
                    f"{n.get('hostname', '')} ({n.get('total_cores', 0)} cores)",
                    n.get("hostname", ""),
                )
                for n in self.available_nodes
                if n.get("status") == "online"
            ]
            yield Select(node_options, id="node-select", allow_blank=False, value="")

            # GPU selection (shown if node has GPUs)
            yield Label("GPU IDs (comma-separated, e.g., 0,1)", classes="field-label")
            yield Input(placeholder="Leave empty for no GPU", id="gpu-input")
            yield Static(id="gpu-info")

            # Configuration
            yield Static("Configuration", classes="section-title")

            yield Label("CPU Cores (0 = no limit)", classes="field-label")
            yield Input(placeholder="0", id="cores-input", type="integer")

            yield Label("Container Environment", classes="field-label")
            container_options = [("Default", "")] + [
                (c, c) for c in self.available_containers
            ]
            yield Select(
                container_options, id="container-select", allow_blank=False, value=""
            )

            # SSH Key
            yield Static("SSH Access", classes="section-title")
            yield Label("SSH Key Mode", classes="field-label")
            with RadioSet(id="ssh-mode"):
                yield RadioButton(
                    "Generate new key pair", id="ssh-generate", value=True
                )
                yield RadioButton("Use existing key (~/.ssh/id_*.pub)", id="ssh-upload")
                yield RadioButton("No SSH key", id="ssh-none")

            with Horizontal(classes="buttons"):
                yield Button("Create VPS", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        """Update GPU info on mount."""
        self._update_gpu_info("")

    @on(Select.Changed, "#node-select")
    def on_node_changed(self, event: Select.Changed) -> None:
        """Handle node selection change."""
        self._update_gpu_info(event.value)

    def _update_gpu_info(self, hostname: str) -> None:
        """Update GPU info display for selected node."""
        gpu_info_widget = self.query_one("#gpu-info", Static)

        if not hostname:
            gpu_info_widget.update("[dim]Select a node to see GPU information[/dim]")
            return

        # Find node
        node = None
        for n in self.available_nodes:
            if n.get("hostname") == hostname:
                node = n
                break

        if not node:
            gpu_info_widget.update("[dim]Node not found[/dim]")
            return

        self.selected_node = node
        gpu_list = node.get("gpu_info", [])

        if not gpu_list:
            gpu_info_widget.update("[dim]No GPUs on this node[/dim]")
            return

        # Build GPU info text
        lines = []
        for gpu in gpu_list:
            gpu_id = gpu.get("gpu_id", 0)
            name = gpu.get("name", "Unknown")
            mem = gpu.get("memory_total_mib", 0)
            util = gpu.get("gpu_utilization", "?")
            temp = gpu.get("temperature", "?")
            lines.append(f"[{gpu_id}] {name} - {mem}MiB - {util}% util - {temp}°C")

        gpu_info_widget.update("\n".join(lines))

    @on(Button.Pressed, "#create-btn")
    def on_create(self) -> None:
        """Handle create button."""
        node_select = self.query_one("#node-select", Select)
        gpu_input = self.query_one("#gpu-input", Input).value.strip()
        cores_str = self.query_one("#cores-input", Input).value.strip()
        container_select = self.query_one("#container-select", Select)
        ssh_mode_set = self.query_one("#ssh-mode", RadioSet)

        # Parse cores
        try:
            cores = int(cores_str) if cores_str else 0
        except ValueError:
            cores = 0

        # Parse GPU IDs
        gpu_ids = None
        if gpu_input:
            try:
                gpu_ids = [
                    int(g.strip()) for g in gpu_input.split(",") if g.strip().isdigit()
                ]
            except ValueError:
                gpu_ids = None

        # Get SSH mode
        ssh_mode = "generate"
        if ssh_mode_set.pressed_button:
            btn_id = ssh_mode_set.pressed_button.id
            if btn_id == "ssh-generate":
                ssh_mode = "generate"
            elif btn_id == "ssh-upload":
                ssh_mode = "upload"
            elif btn_id == "ssh-none":
                ssh_mode = "none"

        # Handle SSH key upload
        public_key = None
        if ssh_mode == "upload":
            default_keys = [
                os.path.expanduser("~/.ssh/id_ed25519.pub"),
                os.path.expanduser("~/.ssh/id_rsa.pub"),
            ]
            for key_path in default_keys:
                if os.path.exists(key_path):
                    try:
                        with open(key_path) as f:
                            public_key = f.read().strip()
                        break
                    except Exception:
                        continue

            if not public_key:
                self.notify(
                    "No SSH key found, switching to generate mode", severity="warning"
                )
                ssh_mode = "generate"

        result = {
            "target": node_select.value if node_select.value else None,
            "gpu_ids": gpu_ids,
            "cores": cores,
            "container": container_select.value if container_select.value else None,
            "ssh_key_mode": ssh_mode,
            "public_key": public_key,
        }

        self.dismiss(result)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        """Handle cancel button."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(None)


class CreateContainerModal(ModalScreen[dict | None]):
    """Modal dialog for creating a new container environment."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    CreateContainerModal {
        align: center middle;
    }

    #container-dialog {
        width: 60;
        height: auto;
        border: thick #00ff00;
        background: #1a1a2e;
        padding: 1 2;
    }

    #container-dialog .title {
        text-style: bold;
        text-align: center;
        width: 100%;
        padding-bottom: 1;
        color: #00ff00;
    }

    #container-dialog .field-label {
        margin-top: 1;
        color: #888;
    }

    #container-dialog Input {
        width: 100%;
    }

    #container-dialog .buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    #container-dialog Button {
        margin: 0 1;
    }

    #container-dialog .hint {
        color: #666;
        text-style: italic;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="container-dialog"):
            yield Static("Create New Environment Container", classes="title")

            yield Label("Docker Image *", classes="field-label")
            yield Input(placeholder="e.g., python:3.11, ubuntu:22.04", id="image-input")

            yield Label("Environment Name *", classes="field-label")
            yield Input(placeholder="e.g., my-python-env", id="name-input")
            yield Static(
                "(This name will be used to reference the container)", classes="hint"
            )

            with Horizontal(classes="buttons"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    @on(Button.Pressed, "#create-btn")
    def on_create(self) -> None:
        """Handle create button."""
        image = self.query_one("#image-input", Input).value.strip()
        name = self.query_one("#name-input", Input).value.strip()

        if not image:
            self.notify("Docker image is required", severity="error")
            return

        if not name:
            self.notify("Environment name is required", severity="error")
            return

        result = {
            "image": image,
            "name": name,
        }

        self.dismiss(result)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel(self) -> None:
        """Handle cancel button."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Simple confirmation modal."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
    ]

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }

    #confirm-dialog {
        width: 50;
        height: auto;
        border: thick #ff9900;
        background: #1a1a2e;
        padding: 1 2;
    }

    #confirm-dialog .title {
        text-style: bold;
        text-align: center;
        width: 100%;
        color: #ff9900;
    }

    #confirm-dialog .message {
        text-align: center;
        padding: 1 0;
    }

    #confirm-dialog .buttons {
        height: 3;
        align: center middle;
    }

    #confirm-dialog Button {
        margin: 0 1;
    }
    """

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._title, classes="title")
            yield Static(self._message, classes="message")

            with Horizontal(classes="buttons"):
                yield Button("Yes (Y)", variant="warning", id="yes-btn")
                yield Button("No (N)", variant="default", id="no-btn")

    @on(Button.Pressed, "#yes-btn")
    def on_yes(self) -> None:
        """Handle yes button."""
        self.dismiss(True)

    @on(Button.Pressed, "#no-btn")
    def on_no(self) -> None:
        """Handle no button."""
        self.dismiss(False)

    def action_confirm(self) -> None:
        """Confirm action."""
        self.dismiss(True)

    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(False)


class PortForwardModal(ModalScreen[dict | None]):
    """Modal showing port forwarding command information."""

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
    ]

    DEFAULT_CSS = """
    PortForwardModal {
        align: center middle;
    }

    #forward-dialog {
        width: 65;
        height: auto;
        border: thick #00ff88;
        background: #1a1a2e;
        padding: 1 2;
    }

    #forward-dialog .title {
        text-style: bold;
        text-align: center;
        width: 100%;
        padding-bottom: 1;
        color: #00ff88;
    }

    #forward-dialog .info-text {
        color: #888;
        padding: 1 0;
    }

    #forward-dialog .field-label {
        margin-top: 1;
        color: #888;
    }

    #forward-dialog Input {
        width: 100%;
    }

    #forward-dialog .command-box {
        background: #0a0a1a;
        border: solid #444;
        padding: 1;
        margin: 1 0;
    }

    #forward-dialog .command-text {
        color: #4ec9b0;
    }

    #forward-dialog .buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }

    #forward-dialog Button {
        margin: 0 1;
    }

    #forward-dialog .protocol-row {
        height: 3;
        margin-top: 1;
    }

    #forward-dialog .hint {
        color: #666;
        text-style: italic;
    }
    """

    def __init__(self, task_id: str | int) -> None:
        super().__init__()
        self._task_id = task_id

    def compose(self) -> ComposeResult:
        with Vertical(id="forward-dialog"):
            yield Static("Port Forwarding", classes="title")

            yield Static(
                "Forward a container port to your local machine using the CLI.",
                classes="info-text",
            )

            yield Label("Container Port", classes="field-label")
            yield Input(placeholder="e.g., 8080", id="port-input", value="8080")

            yield Label("Local Port (optional)", classes="field-label")
            yield Input(placeholder="Same as container port", id="local-port-input")

            with Horizontal(classes="protocol-row"):
                yield Label("Protocol: ", classes="field-label")
                yield RadioSet(
                    RadioButton("TCP", value=True, id="proto-tcp"),
                    RadioButton("UDP", id="proto-udp"),
                    id="protocol-set",
                )

            yield Static("CLI Command:", classes="field-label")
            with Vertical(classes="command-box"):
                yield Static(
                    f"kohakuriver forward {self._task_id} 8080",
                    id="command-display",
                    classes="command-text",
                )

            yield Static(
                "Run this command in your terminal to start forwarding.",
                classes="hint",
            )

            with Horizontal(classes="buttons"):
                yield Button("Copy Command", variant="primary", id="copy-btn")
                yield Button("Close", variant="default", id="close-btn")

    def _update_command(self) -> None:
        """Update the displayed command based on inputs."""
        port = self.query_one("#port-input", Input).value.strip() or "8080"
        local_port = self.query_one("#local-port-input", Input).value.strip()
        proto_udp = self.query_one("#proto-udp", RadioButton).value

        cmd_parts = ["kohakuriver", "forward", str(self._task_id), port]
        if local_port and local_port != port:
            cmd_parts.extend(["-l", local_port])
        if proto_udp:
            cmd_parts.extend(["--proto", "udp"])

        cmd = " ".join(cmd_parts)
        self.query_one("#command-display", Static).update(cmd)

    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        """Update command when inputs change."""
        self._update_command()

    @on(RadioButton.Changed)
    def on_radio_changed(self, event: RadioButton.Changed) -> None:
        """Update command when protocol changes."""
        self._update_command()

    @on(Button.Pressed, "#copy-btn")
    def on_copy(self) -> None:
        """Copy command to clipboard."""
        cmd = self.query_one("#command-display", Static).renderable
        # Note: Textual doesn't have direct clipboard access,
        # so we just show a notification
        self.notify(f"Command: {cmd}", title="Copy this command")

    @on(Button.Pressed, "#close-btn")
    def on_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(None)
