"""
Full-screen TUI application for HakuRiver cluster management.

Features:
- Live cluster status dashboard
- Node list with real-time updates
- Task list with filtering
- VPS management
- Keyboard navigation with arrow keys
- Detail views with Enter key
- Interactive task/VPS creation
"""

import json
import os
import select
import shlex
import subprocess
import sys
import termios
import time
import tty
from datetime import datetime
from enum import Enum

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from kohakuriver.cli import client
from kohakuriver.cli.output import format_bytes


class View(Enum):
    """Available TUI views."""

    DASHBOARD = "dashboard"
    NODES = "nodes"
    TASKS = "tasks"
    VPS = "vps"
    DOCKER = "docker"
    TASK_DETAIL = "task_detail"
    VPS_DETAIL = "vps_detail"
    NODE_DETAIL = "node_detail"
    DOCKER_DETAIL = "docker_detail"


# Status colors
STATUS_COLORS = {
    "online": "green",
    "offline": "red",
    "running": "green",
    "pending": "yellow",
    "assigning": "yellow",
    "completed": "cyan",
    "failed": "red",
    "killed": "red",
    "unknown": "dim",
}


def get_status_style(status: str) -> str:
    """Get color for status."""
    return STATUS_COLORS.get(status.lower(), "white")


def format_status(status: str) -> Text:
    """Format status with color."""
    color = get_status_style(status)
    return Text(status, style=color)


class InputReader:
    """Non-blocking input reader with proper escape sequence handling."""

    def __init__(self):
        self.buffer = []

    def read_key(self, timeout: float = 0.1) -> str | None:
        """Read a key with proper escape sequence handling."""
        # Check if input available
        if not select.select([sys.stdin], [], [], timeout)[0]:
            return None

        # Read first character
        ch = sys.stdin.read(1)

        # Handle escape sequences
        if ch == "\x1b":
            # Wait a bit longer for the rest of escape sequence
            # SSH may have latency, so use longer timeout
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    # CSI sequence - read until we get a letter
                    seq = ""
                    while True:
                        if select.select([sys.stdin], [], [], 0.05)[0]:
                            ch3 = sys.stdin.read(1)
                            seq += ch3
                            # CSI sequences end with a letter
                            if ch3.isalpha() or ch3 == "~":
                                break
                        else:
                            break

                    # Parse common sequences
                    if seq == "A":
                        return "up"
                    elif seq == "B":
                        return "down"
                    elif seq == "C":
                        return "right"
                    elif seq == "D":
                        return "left"
                    elif seq == "H":
                        return "home"
                    elif seq == "F":
                        return "end"
                    elif seq.endswith("~"):
                        # Handle sequences like 1~, 4~, 5~, 6~
                        num = seq[:-1]
                        if num == "1":
                            return "home"
                        elif num == "4":
                            return "end"
                        elif num == "5":
                            return "pageup"
                        elif num == "6":
                            return "pagedown"
                        elif num == "3":
                            return "delete"
                    return f"esc[{seq}"  # Unknown sequence
                elif ch2 == "O":
                    # SS3 sequence (some terminals use this for arrow keys)
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        ch3 = sys.stdin.read(1)
                        if ch3 == "A":
                            return "up"
                        elif ch3 == "B":
                            return "down"
                        elif ch3 == "C":
                            return "right"
                        elif ch3 == "D":
                            return "left"
                    return "escape"
                else:
                    # Alt+key combination
                    return f"alt+{ch2}"
            else:
                # Just escape key pressed
                return "escape"

        return ch


class TUIApp:
    """Terminal UI Application for HakuRiver."""

    def __init__(self, refresh_rate: float = 2.0):
        self.console = Console()
        self.refresh_rate = refresh_rate
        self.current_view = View.DASHBOARD
        self.previous_view = View.DASHBOARD
        self.running = True
        self.selected_index = 0
        self.task_filter = "all"  # all, running, pending, completed, failed
        self.error_message: str | None = None
        self.status_message: str | None = None
        self.input_reader = InputReader()

        # Cached data
        self.nodes: list[dict] = []
        self.tasks: list[dict] = []
        self.vps_list: list[dict] = []
        self.containers: list[dict] = []
        self.tarballs: dict = {}

        # Detail view data
        self.detail_item: dict | None = None

        # For temporarily exiting Live mode
        self.live: Live | None = None
        self.old_settings = None

    def fetch_data(self) -> None:
        """Fetch all data from the API."""
        try:
            self.nodes = client.get_nodes()
            self.tasks = client.get_tasks(limit=50)
            self.vps_list = client.get_vps_list(active_only=False)
            self.containers = client.get_host_containers()
            self.tarballs = client.get_tarballs()
            self.error_message = None
        except client.APIError as e:
            self.error_message = str(e)
        except Exception as e:
            self.error_message = f"Connection error: {e}"

    def get_current_list(self) -> list[dict]:
        """Get the list for current view."""
        if self.current_view == View.NODES:
            return self.nodes
        elif self.current_view == View.TASKS:
            if self.task_filter == "all":
                return self.tasks
            return [t for t in self.tasks if t.get("status") == self.task_filter]
        elif self.current_view == View.VPS:
            return self.vps_list
        elif self.current_view == View.DOCKER:
            return self.containers
        return []

    def create_layout(self) -> Layout:
        """Create the main layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        return layout

    def render_header(self) -> Panel:
        """Render the header bar."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # View tabs
        tabs = []
        for view in [View.DASHBOARD, View.NODES, View.TASKS, View.VPS, View.DOCKER]:
            if view == self.current_view or (
                self.current_view
                in (
                    View.TASK_DETAIL,
                    View.VPS_DETAIL,
                    View.NODE_DETAIL,
                    View.DOCKER_DETAIL,
                )
                and view == self.previous_view
            ):
                tabs.append(Text(f" {view.value.upper()} ", style="bold white on blue"))
            else:
                tabs.append(Text(f" {view.value.upper()} ", style="dim"))

        tab_line = Text()
        for i, tab in enumerate(tabs):
            if i > 0:
                tab_line.append(" | ", style="dim")
            tab_line.append_text(tab)

        header_text = Text()
        header_text.append("HakuRiver Cluster Manager", style="bold cyan")
        header_text.append(f"  |  {now}", style="dim")

        return Panel(
            Group(header_text, tab_line),
            style="white on dark_blue",
            border_style="blue",
        )

    def render_footer(self) -> Panel:
        """Render the footer with keybindings."""
        if self.error_message:
            return Panel(
                Text(f"Error: {self.error_message}", style="red"),
                style="red",
            )

        if self.status_message:
            return Panel(
                Text(self.status_message, style="green"),
                style="green",
            )

        # Build key hints based on current view
        keys = Text()

        if self.current_view in (
            View.TASK_DETAIL,
            View.VPS_DETAIL,
            View.NODE_DETAIL,
            View.DOCKER_DETAIL,
        ):
            keys.append("Esc", style="bold")
            keys.append("-Back  ", style="dim")
            if self.current_view == View.TASK_DETAIL:
                keys.append("k", style="bold")
                keys.append("-Kill  ", style="dim")
            elif self.current_view == View.VPS_DETAIL:
                keys.append("k", style="bold")
                keys.append("-Stop  ", style="dim")
            elif self.current_view == View.DOCKER_DETAIL:
                keys.append("s", style="bold")
                keys.append("-Shell  ", style="dim")
                keys.append("t", style="bold")
                keys.append("-Tar  ", style="dim")
        else:
            keys.append("1", style="bold")
            keys.append("-Dashboard  ", style="dim")
            keys.append("2", style="bold")
            keys.append("-Nodes  ", style="dim")
            keys.append("3", style="bold")
            keys.append("-Tasks  ", style="dim")
            keys.append("4", style="bold")
            keys.append("-VPS  ", style="dim")
            keys.append("5", style="bold")
            keys.append("-Docker  ", style="dim")

            if self.current_view in (View.NODES, View.TASKS, View.VPS, View.DOCKER):
                keys.append("↑↓/WS", style="bold")
                keys.append("-Nav  ", style="dim")
                keys.append("AD", style="bold")
                keys.append("-Views  ", style="dim")
                keys.append("Enter", style="bold")
                keys.append("-Details  ", style="dim")

            if self.current_view == View.TASKS:
                keys.append("f", style="bold")
                keys.append("-Filter  ", style="dim")
                keys.append("n", style="bold")
                keys.append("-New  ", style="dim")
            elif self.current_view == View.VPS:
                keys.append("n", style="bold")
                keys.append("-New  ", style="dim")
            elif self.current_view == View.DOCKER:
                keys.append("n", style="bold")
                keys.append("-New  ", style="dim")

            keys.append("r", style="bold")
            keys.append("-Refresh  ", style="dim")

        keys.append("q", style="bold")
        keys.append("-Quit", style="dim")

        return Panel(keys, style="dim")

    def render_dashboard(self) -> Panel:
        """Render the dashboard view."""
        # Cluster summary
        online = sum(1 for n in self.nodes if n.get("status") == "online")
        offline = len(self.nodes) - online

        total_cores = sum(n.get("total_cores", 0) for n in self.nodes)

        running_tasks = sum(1 for t in self.tasks if t.get("status") == "running")
        pending_tasks = sum(
            1 for t in self.tasks if t.get("status") in ("pending", "assigning")
        )

        active_vps = sum(1 for v in self.vps_list if v.get("status") == "running")

        # Summary table
        summary = Table(show_header=False, box=None, padding=(0, 2))
        summary.add_column("Label", style="bold")
        summary.add_column("Value", style="green")

        summary.add_row("Nodes", f"{online} online / {offline} offline")
        summary.add_row("Total Cores", str(total_cores))
        summary.add_row("Running Tasks", str(running_tasks))
        summary.add_row("Pending Tasks", str(pending_tasks))
        summary.add_row("Active VPS", str(active_vps))

        # Recent tasks
        recent_table = Table(title="Recent Tasks", show_header=True, expand=True)
        recent_table.add_column("ID", style="cyan", width=18)
        recent_table.add_column("Status", justify="center", width=10)
        recent_table.add_column("Node", width=15)
        recent_table.add_column("Command", overflow="ellipsis")

        for task in self.tasks[:10]:
            status = task.get("status", "unknown")
            node = task.get("assigned_node")
            if isinstance(node, dict):
                node = node.get("hostname", "-")

            recent_table.add_row(
                str(task.get("task_id", ""))[-18:],
                Text(status, style=get_status_style(status)),
                node or "-",
                task.get("command", "")[:40],
            )

        # Node status
        node_table = Table(title="Node Status", show_header=True, expand=True)
        node_table.add_column("Hostname", style="cyan")
        node_table.add_column("Status", justify="center")
        node_table.add_column("CPU%", justify="right")
        node_table.add_column("Memory", justify="right")

        for node in self.nodes[:8]:
            cpu = node.get("cpu_percent", 0)
            mem_total = node.get("memory_total_bytes", 0)
            mem_used = node.get("memory_used_bytes", 0)
            mem_pct = (mem_used / mem_total * 100) if mem_total else 0
            status = node.get("status", "unknown")

            node_table.add_row(
                node.get("hostname", ""),
                Text(status, style=get_status_style(status)),
                f"{cpu:.0f}%",
                f"{mem_pct:.0f}%",
            )

        # Layout
        content = Layout()
        content.split_column(
            Layout(Panel(summary, title="Cluster Summary"), size=9),
            Layout(name="tables"),
        )
        content["tables"].split_row(
            Layout(Panel(node_table)),
            Layout(Panel(recent_table)),
        )

        return Panel(content, title="Dashboard", border_style="green")

    def render_nodes(self) -> Panel:
        """Render the nodes view."""
        table = Table(show_header=True, expand=True)
        table.add_column("Hostname", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Cores", justify="right")
        table.add_column("CPU%", justify="right")
        table.add_column("Memory", justify="right")
        table.add_column("GPUs", justify="right")
        table.add_column("URL")

        for i, node in enumerate(self.nodes):
            is_selected = i == self.selected_index
            row_style = "reverse" if is_selected else None

            cpu = node.get("cpu_percent", 0)
            mem_total = node.get("memory_total_bytes", 0)
            mem_used = node.get("memory_used_bytes", 0)

            if mem_total:
                mem_str = f"{format_bytes(mem_used)}/{format_bytes(mem_total)}"
            else:
                mem_str = "-"

            gpu_info = node.get("gpu_info", [])
            gpu_str = str(len(gpu_info)) if gpu_info else "-"

            status = node.get("status", "unknown")

            table.add_row(
                node.get("hostname", ""),
                Text(status, style=get_status_style(status)),
                str(node.get("total_cores", 0)),
                f"{cpu:.0f}%",
                mem_str,
                gpu_str,
                node.get("url", ""),
                style=row_style,
            )

        info = Text()
        info.append(f"Total: {len(self.nodes)} nodes", style="dim")

        return Panel(Group(info, table), title="Nodes", border_style="cyan")

    def render_tasks(self) -> Panel:
        """Render the tasks view."""
        # Filter tasks
        if self.task_filter == "all":
            filtered = self.tasks
        else:
            filtered = [t for t in self.tasks if t.get("status") == self.task_filter]

        # Filter indicator
        filter_text = Text()
        filter_text.append("Filter: ", style="dim")
        filter_text.append(self.task_filter, style="bold yellow")
        filter_text.append(f"  |  Total: {len(filtered)} tasks", style="dim")

        table = Table(show_header=True, expand=True)
        table.add_column("Task ID", style="cyan", width=20)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Node", width=15)
        table.add_column("Cores", justify="right", width=6)
        table.add_column("GPUs", justify="right", width=8)
        table.add_column("Command", overflow="ellipsis")

        for i, task in enumerate(filtered[:30]):
            is_selected = i == self.selected_index
            row_style = "reverse" if is_selected else None

            node = task.get("assigned_node")
            if isinstance(node, dict):
                node = node.get("hostname", "-")

            gpus = task.get("required_gpus", [])
            if isinstance(gpus, str):
                try:
                    gpus = json.loads(gpus)
                except:
                    gpus = []
            gpu_str = ",".join(map(str, gpus)) if gpus else "-"

            status = task.get("status", "unknown")

            table.add_row(
                str(task.get("task_id", ""))[-20:],
                Text(status, style=get_status_style(status)),
                node or "-",
                str(task.get("required_cores", 1)),
                gpu_str,
                task.get("command", ""),
                style=row_style,
            )

        content = Group(filter_text, table)
        return Panel(content, title="Tasks", border_style="yellow")

    def render_vps(self) -> Panel:
        """Render the VPS view."""
        table = Table(show_header=True, expand=True)
        table.add_column("Task ID", style="cyan", width=20)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Node", width=15)
        table.add_column("SSH Port", justify="right", width=10)
        table.add_column("Cores", justify="right", width=6)
        table.add_column("Started", width=20)

        for i, vps in enumerate(self.vps_list[:20]):
            is_selected = i == self.selected_index
            row_style = "reverse" if is_selected else None

            node = vps.get("assigned_node")
            if isinstance(node, dict):
                node = node.get("hostname", "-")

            ssh_port = vps.get("ssh_port")
            ssh_str = str(ssh_port) if ssh_port else "-"

            started = vps.get("started_at", "-")
            if started and isinstance(started, str) and len(started) > 19:
                started = started[:19]

            status = vps.get("status", "unknown")

            table.add_row(
                str(vps.get("task_id", ""))[-20:],
                Text(status, style=get_status_style(status)),
                node or "-",
                ssh_str,
                str(vps.get("required_cores", 0)),
                str(started),
                style=row_style,
            )

        info = Text()
        info.append(f"Total: {len(self.vps_list)} VPS instances", style="dim")

        return Panel(Group(info, table), title="VPS Instances", border_style="magenta")

    def render_docker(self) -> Panel:
        """Render the Docker containers view."""
        table = Table(show_header=True, expand=True)
        table.add_column("Environment", style="cyan", width=20)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Image", width=30)
        table.add_column("Tarball", justify="center", width=10)

        for i, container in enumerate(self.containers[:20]):
            is_selected = i == self.selected_index
            row_style = "reverse" if is_selected else None

            env_name = container.get("env_name", container.get("name", ""))
            status = container.get("status", "unknown")
            image = container.get("image", "-")

            # Check if tarball exists
            has_tarball = env_name in self.tarballs
            tarball_str = "✓" if has_tarball else "-"

            # Status style
            status_style = (
                "green"
                if status == "running"
                else "yellow" if status == "exited" else "dim"
            )

            table.add_row(
                env_name,
                Text(status, style=status_style),
                image,
                tarball_str,
                style=row_style,
            )

        info = Text()
        info.append(
            f"Total: {len(self.containers)} environment containers", style="dim"
        )
        info.append(f"  |  Tarballs: {len(self.tarballs)}", style="dim")

        return Panel(
            Group(info, table), title="Docker Environments (Host)", border_style="blue"
        )

    def render_docker_detail(self) -> Panel:
        """Render Docker container detail view."""
        if not self.detail_item:
            return Panel(
                "No container selected", title="Container Detail", border_style="blue"
            )

        container = self.detail_item

        # Info table
        info = Table(show_header=False, box=None, padding=(0, 2))
        info.add_column("Field", style="bold", width=12)
        info.add_column("Value")

        env_name = container.get("env_name", container.get("name", ""))
        status = container.get("status", "unknown")

        info.add_row("Environment", env_name)
        info.add_row("Container", container.get("name", "-"))
        info.add_row("ID", container.get("id", "-"))

        status_style = (
            "green"
            if status == "running"
            else "yellow" if status == "exited" else "dim"
        )
        info.add_row("Status", Text(status, style=status_style))

        info.add_row("Image", container.get("image", "-"))
        info.add_row("Created", str(container.get("created", "-"))[:19])

        # Tarball info
        if env_name in self.tarballs:
            tarball_info = self.tarballs[env_name]
            info.add_row("Tarball", tarball_info.get("latest_tarball", "-"))
            versions = tarball_info.get("all_versions", [])
            info.add_row("Versions", str(len(versions)))
        else:
            info.add_row("Tarball", Text("Not created", style="yellow"))

        # Actions help
        help_text = Text()
        help_text.append("\n[Actions]\n", style="bold")
        help_text.append("  s - Open shell in container\n", style="dim")
        help_text.append("  t - Create/update tarball\n", style="dim")
        help_text.append("  Esc - Go back\n", style="dim")

        return Panel(
            Group(info, help_text),
            title=f"Container: {env_name}",
            border_style="blue",
        )

    def render_task_detail(self) -> Panel:
        """Render task detail view."""
        if not self.detail_item:
            return Panel("No task selected", title="Task Detail", border_style="yellow")

        task = self.detail_item

        # Info table
        info = Table(show_header=False, box=None, padding=(0, 2))
        info.add_column("Field", style="bold", width=12)
        info.add_column("Value")

        task_id = str(task.get("task_id", ""))
        status = task.get("status", "unknown")

        info.add_row("Task ID", task_id)
        info.add_row("Status", Text(status, style=get_status_style(status)))

        node = task.get("assigned_node")
        if isinstance(node, dict):
            node = node.get("hostname", "-")
        info.add_row("Node", node or "-")

        info.add_row("Command", task.get("command", "-"))
        info.add_row("Cores", str(task.get("required_cores", 1)))

        gpus = task.get("required_gpus", [])
        if isinstance(gpus, str):
            try:
                gpus = json.loads(gpus)
            except:
                gpus = []
        info.add_row("GPUs", ",".join(map(str, gpus)) if gpus else "-")

        info.add_row("Created", str(task.get("created_at", "-"))[:19])
        info.add_row(
            "Started",
            str(task.get("started_at", "-"))[:19] if task.get("started_at") else "-",
        )
        info.add_row(
            "Completed",
            (
                str(task.get("completed_at", "-"))[:19]
                if task.get("completed_at")
                else "-"
            ),
        )

        if task.get("exit_code") is not None:
            exit_code = task.get("exit_code")
            exit_style = "green" if exit_code == 0 else "red"
            info.add_row("Exit Code", Text(str(exit_code), style=exit_style))

        # Fetch stdout/stderr
        stdout_content = ""
        stderr_content = ""
        try:
            stdout_content = client.get_task_stdout(task_id)
            stderr_content = client.get_task_stderr(task_id)
        except:
            pass  # Ignore errors fetching logs

        # Build layout
        content = Layout()
        content.split_column(
            Layout(Panel(info, title="Task Info"), size=14),
            Layout(name="logs"),
        )

        # Logs section
        logs_layout = Layout()
        logs_layout.split_row(
            Layout(name="stdout"),
            Layout(name="stderr"),
        )

        # Stdout panel
        if stdout_content:
            # Show last ~20 lines to fit in view
            stdout_lines = stdout_content.strip().split("\n")
            if len(stdout_lines) > 20:
                stdout_display = "\n".join(stdout_lines[-20:])
                stdout_display = (
                    f"... ({len(stdout_lines) - 20} lines hidden)\n{stdout_display}"
                )
            else:
                stdout_display = stdout_content.strip()
        else:
            stdout_display = "[dim]No output[/dim]"
        logs_layout["stdout"].update(
            Panel(stdout_display, title="stdout", border_style="green")
        )

        # Stderr panel
        if stderr_content:
            stderr_lines = stderr_content.strip().split("\n")
            if len(stderr_lines) > 20:
                stderr_display = "\n".join(stderr_lines[-20:])
                stderr_display = (
                    f"... ({len(stderr_lines) - 20} lines hidden)\n{stderr_display}"
                )
            else:
                stderr_display = stderr_content.strip()
        else:
            stderr_display = "[dim]No errors[/dim]"
        logs_layout["stderr"].update(
            Panel(stderr_display, title="stderr", border_style="red")
        )

        content["logs"].update(logs_layout)

        # Actions hint
        actions = Text()
        actions.append("Actions: ", style="bold")
        if status == "running":
            actions.append("k", style="bold red")
            actions.append("-Kill  ", style="dim")
        actions.append("o", style="bold")
        actions.append("-Full stdout  ", style="dim")
        actions.append("e", style="bold")
        actions.append("-Full stderr  ", style="dim")
        actions.append("Esc", style="bold")
        actions.append("-Back", style="dim")

        return Panel(
            Group(content, actions),
            title=f"Task Detail: {task_id[-20:]}",
            border_style="yellow",
        )

    def render_vps_detail(self) -> Panel:
        """Render VPS detail view."""
        if not self.detail_item:
            return Panel("No VPS selected", title="VPS Detail", border_style="magenta")

        vps = self.detail_item

        # Info table
        info = Table(show_header=False, box=None, padding=(0, 2))
        info.add_column("Field", style="bold")
        info.add_column("Value")

        task_id = str(vps.get("task_id", ""))
        status = vps.get("status", "unknown")

        info.add_row("Task ID", task_id)
        info.add_row("Status", Text(status, style=get_status_style(status)))

        node = vps.get("assigned_node")
        if isinstance(node, dict):
            node_hostname = node.get("hostname", "-")
            node_url = node.get("url", "")
        else:
            node_hostname = node or "-"
            node_url = ""
        info.add_row("Node", node_hostname)

        ssh_port = vps.get("ssh_port")
        if ssh_port and node_url:
            # Extract host from URL
            host = node_url.replace("http://", "").replace("https://", "").split(":")[0]
            info.add_row("SSH Port", str(ssh_port))
            info.add_row("SSH Command", f"ssh -p {ssh_port} root@{host}")
        else:
            info.add_row("SSH Port", str(ssh_port) if ssh_port else "-")

        info.add_row("Cores", str(vps.get("required_cores", 0)))
        info.add_row("Container", vps.get("container_name", "-") or "-")
        info.add_row(
            "Started",
            str(vps.get("started_at", "-"))[:19] if vps.get("started_at") else "-",
        )

        # Actions hint
        actions = Text()
        actions.append("\nActions: ", style="bold")
        if status == "running":
            actions.append("k", style="bold red")
            actions.append("-Stop VPS  ", style="dim")
        actions.append("Esc", style="bold")
        actions.append("-Back", style="dim")

        return Panel(
            Group(info, actions),
            title=f"VPS Detail: {task_id[-20:]}",
            border_style="magenta",
        )

    def render_node_detail(self) -> Panel:
        """Render node detail view."""
        if not self.detail_item:
            return Panel("No node selected", title="Node Detail", border_style="cyan")

        node = self.detail_item

        # Info table
        info = Table(show_header=False, box=None, padding=(0, 2))
        info.add_column("Field", style="bold")
        info.add_column("Value")

        hostname = node.get("hostname", "")
        status = node.get("status", "unknown")

        info.add_row("Hostname", hostname)
        info.add_row("Status", Text(status, style=get_status_style(status)))
        info.add_row("URL", node.get("url", "-"))
        info.add_row("Cores", str(node.get("total_cores", 0)))

        cpu = node.get("cpu_percent", 0)
        info.add_row("CPU Usage", f"{cpu:.1f}%")

        mem_total = node.get("memory_total_bytes", 0)
        mem_used = node.get("memory_used_bytes", 0)
        mem_pct = (mem_used / mem_total * 100) if mem_total else 0
        info.add_row(
            "Memory",
            f"{format_bytes(mem_used)} / {format_bytes(mem_total)} ({mem_pct:.1f}%)",
        )

        # GPU info
        gpu_info = node.get("gpu_info", [])
        if gpu_info:
            info.add_row("GPUs", str(len(gpu_info)))
            for i, gpu in enumerate(gpu_info):
                gpu_name = gpu.get("name", "Unknown")
                gpu_mem = gpu.get("memory_total", 0)
                info.add_row(f"  GPU {i}", f"{gpu_name} ({format_bytes(gpu_mem)})")
        else:
            info.add_row("GPUs", "-")

        # Actions hint
        actions = Text()
        actions.append("\nPress ", style="dim")
        actions.append("Esc", style="bold")
        actions.append(" to go back", style="dim")

        return Panel(
            Group(info, actions), title=f"Node Detail: {hostname}", border_style="cyan"
        )

    def render(self) -> Layout:
        """Render the full TUI."""
        layout = self.create_layout()

        layout["header"].update(self.render_header())
        layout["footer"].update(self.render_footer())

        match self.current_view:
            case View.DASHBOARD:
                layout["body"].update(self.render_dashboard())
            case View.NODES:
                layout["body"].update(self.render_nodes())
            case View.TASKS:
                layout["body"].update(self.render_tasks())
            case View.VPS:
                layout["body"].update(self.render_vps())
            case View.DOCKER:
                layout["body"].update(self.render_docker())
            case View.TASK_DETAIL:
                layout["body"].update(self.render_task_detail())
            case View.VPS_DETAIL:
                layout["body"].update(self.render_vps_detail())
            case View.NODE_DETAIL:
                layout["body"].update(self.render_node_detail())
            case View.DOCKER_DETAIL:
                layout["body"].update(self.render_docker_detail())

        return layout

    def _restore_terminal(self):
        """Restore terminal to normal mode for input."""
        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def _setup_terminal(self):
        """Setup terminal for raw input mode."""
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

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
                # GPU selection mode
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
                    return

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
                gpu_id_list = [
                    str(gpu.get("gpu_id", i)) for i, gpu in enumerate(gpu_info)
                ]
                try:
                    gpu_selection = Prompt.ask(
                        "Select GPU IDs (comma-separated, e.g., 0,1)",
                        default=gpu_id_list[0] if gpu_id_list else "0",
                    )
                    gpu_ids = [
                        int(g.strip())
                        for g in gpu_selection.split(",")
                        if g.strip().isdigit()
                    ]
                    if not gpu_ids:
                        self.console.print(
                            "[yellow]No valid GPU IDs. Using first GPU.[/yellow]"
                        )
                        gpu_ids = [int(gpu_id_list[0])] if gpu_id_list else [0]
                except KeyboardInterrupt:
                    self.console.print("\n[yellow]Cancelled.[/yellow]")
                    return
            else:
                # Node selection mode
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
                                    target = online_nodes[idx].get("hostname")
                            except ValueError:
                                # Treat as hostname
                                target = node_choice if node_choice else None
                    except KeyboardInterrupt:
                        self.console.print("\n[yellow]Cancelled.[/yellow]")
                        return
                else:
                    self.console.print("  [dim]No online nodes available.[/dim]")

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
            public_key = None
            if ssh_key_mode == "upload":
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
                            break
                        except:
                            continue

                if not public_key:
                    self.console.print(
                        "[red]No SSH key found. Switching to generate mode.[/red]"
                    )
                    ssh_key_mode = "generate"

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
            self.console.print("\n[dim]Creating VPS...[/dim]")
            try:
                response = client.create_vps(
                    ssh_key_mode=ssh_key_mode,
                    public_key=public_key,
                    cores=cores,
                    target=target,
                    container_name=container,
                    gpu_ids=gpu_ids,
                )

                task_id = response.get("task_id")
                if task_id:
                    ssh_port = response.get("ssh_port", "?")
                    self.status_message = (
                        f"VPS created: {task_id} (SSH port: {ssh_port})"
                    )

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

                    self.console.print(f"[green]VPS created successfully![/green]")
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
            except:
                pass

        finally:
            # Re-enter Live mode
            self._setup_terminal()
            if self.live:
                self.live.start()

        self.fetch_data()

    def handle_key(self, key: str) -> bool:
        """Handle keyboard input. Returns False to quit."""
        # Clear status message on any key
        self.status_message = None

        # Detail view handling
        if self.current_view in (
            View.TASK_DETAIL,
            View.VPS_DETAIL,
            View.NODE_DETAIL,
            View.DOCKER_DETAIL,
        ):
            if key == "escape":
                self.current_view = self.previous_view
                self.detail_item = None
            elif key == "k" or key == "K":
                self._handle_kill()
            elif key == "o" or key == "O":
                # Show full stdout
                if self.current_view == View.TASK_DETAIL and self.detail_item:
                    self._show_full_output("stdout")
            elif key == "e" or key == "E":
                # Show full stderr
                if self.current_view == View.TASK_DETAIL and self.detail_item:
                    self._show_full_output("stderr")
            elif key == "s" or key == "S":
                # Shell into container
                if self.current_view == View.DOCKER_DETAIL and self.detail_item:
                    self._docker_shell()
            elif key == "t" or key == "T":
                # Create tarball
                if self.current_view == View.DOCKER_DETAIL and self.detail_item:
                    self._docker_create_tar()
            elif key == "q" or key == "Q":
                return False
            return True

        match key:
            case "q" | "Q":
                return False
            case "1":
                self.current_view = View.DASHBOARD
                self.selected_index = 0
            case "2":
                self.current_view = View.NODES
                self.selected_index = 0
            case "3":
                self.current_view = View.TASKS
                self.selected_index = 0
            case "4":
                self.current_view = View.VPS
                self.selected_index = 0
            case "5":
                self.current_view = View.DOCKER
                self.selected_index = 0
            case "r" | "R":
                self.fetch_data()
                self.status_message = "Data refreshed"
            case "f" | "F":
                if self.current_view == View.TASKS:
                    filters = ["all", "running", "pending", "completed", "failed"]
                    idx = filters.index(self.task_filter)
                    self.task_filter = filters[(idx + 1) % len(filters)]
                    self.selected_index = 0
            case "n" | "N":
                self._handle_new()
            case "\r" | "\n":  # Enter
                self._handle_enter()
            case "up" | "w" | "W":  # Arrow up or W for SSH compatibility
                self._move_selection(-1)
            case "down" | "s" | "S":  # Arrow down or S for SSH compatibility
                self._move_selection(1)
            case "pageup":
                self._move_selection(-10)
            case "pagedown":
                self._move_selection(10)
            case "home":
                self.selected_index = 0
            case "end":
                current_list = self.get_current_list()
                if current_list:
                    self.selected_index = len(current_list) - 1
            # A/D for left/right view switching (SSH-friendly alternative)
            case "a" | "A":
                views = [View.DASHBOARD, View.NODES, View.TASKS, View.VPS, View.DOCKER]
                if self.current_view in views:
                    idx = views.index(self.current_view)
                    self.current_view = views[(idx - 1) % len(views)]
                    self.selected_index = 0
            case "d" | "D":
                views = [View.DASHBOARD, View.NODES, View.TASKS, View.VPS, View.DOCKER]
                if self.current_view in views:
                    idx = views.index(self.current_view)
                    self.current_view = views[(idx + 1) % len(views)]
                    self.selected_index = 0

        return True

    def _move_selection(self, delta: int) -> None:
        """Move selection up or down."""
        current_list = self.get_current_list()
        if not current_list:
            return

        self.selected_index = max(
            0, min(len(current_list) - 1, self.selected_index + delta)
        )

    def _handle_enter(self) -> None:
        """Handle enter key - show detail view."""
        current_list = self.get_current_list()
        if not current_list or self.selected_index >= len(current_list):
            return

        self.detail_item = current_list[self.selected_index]
        self.previous_view = self.current_view

        if self.current_view == View.NODES:
            self.current_view = View.NODE_DETAIL
        elif self.current_view == View.TASKS:
            self.current_view = View.TASK_DETAIL
        elif self.current_view == View.VPS:
            self.current_view = View.VPS_DETAIL
        elif self.current_view == View.DOCKER:
            self.current_view = View.DOCKER_DETAIL

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
                title = f"Error"

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

    def run(self) -> None:
        """Run the TUI application."""
        # Initial data fetch
        self.fetch_data()

        # Setup terminal for non-blocking input
        self.old_settings = termios.tcgetattr(sys.stdin)

        try:
            tty.setcbreak(sys.stdin.fileno())

            with Live(
                self.render(),
                console=self.console,
                refresh_per_second=4,
                screen=True,
            ) as live:
                self.live = live
                last_fetch = time.time()

                while self.running:
                    # Read key with proper escape sequence handling
                    key = self.input_reader.read_key(timeout=0.1)

                    if key:
                        if not self.handle_key(key):
                            break

                    # Auto-refresh data
                    if time.time() - last_fetch > self.refresh_rate:
                        self.fetch_data()
                        last_fetch = time.time()

                    # Update display
                    live.update(self.render())

        finally:
            self.live = None
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)


def run_tui(refresh_rate: float = 2.0) -> None:
    """Run the TUI application."""
    app = TUIApp(refresh_rate=refresh_rate)
    app.run()
