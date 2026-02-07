"""
Screen components for the TUI Dashboard.
"""

import json

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static, DataTable, Label, TabbedContent, TabPane

from kohakuriver.cli.tui.dashboard.styles import get_status_style, format_bytes
from kohakuriver.cli.tui.dashboard.widgets import (
    HeaderBar,
    FooterBar,
    SummaryCard,
    create_status_text,
    truncate_id,
)


class DashboardScreen(Widget):
    """Dashboard view showing cluster overview."""

    DEFAULT_CSS = """
    DashboardScreen {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    DashboardScreen #summary-row {
        height: 5;
        width: 100%;
        layout: horizontal;
    }

    DashboardScreen #tables-row {
        height: 1fr;
        width: 100%;
        layout: horizontal;
    }

    DashboardScreen .table-container {
        width: 1fr;
        height: 100%;
        border: solid #333;
        margin: 0 1 0 0;
    }

    DashboardScreen .table-container:last-child {
        margin-right: 0;
    }

    DashboardScreen .table-title {
        text-style: bold;
        background: #333;
        padding: 0 1;
        height: 1;
    }

    DashboardScreen DataTable {
        height: 1fr;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.data_nodes: list[dict] = []
        self.data_tasks: list[dict] = []
        self.data_vps_list: list[dict] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="summary-row"):
            yield SummaryCard("Nodes Online", "0 / 0", id="card-nodes")
            yield SummaryCard("Total Cores", "0", id="card-cores")
            yield SummaryCard("Running Tasks", "0", id="card-running")
            yield SummaryCard("Pending Tasks", "0", id="card-pending")
            yield SummaryCard("Active VPS", "0", id="card-vps")

        with Horizontal(id="tables-row"):
            with Vertical(classes="table-container"):
                yield Static("Node Status", classes="table-title")
                yield DataTable(id="node-table", cursor_type="row")

            with Vertical(classes="table-container"):
                yield Static("Recent Tasks", classes="table-title")
                yield DataTable(id="task-table", cursor_type="row")

    def on_mount(self) -> None:
        """Setup tables on mount."""
        # Node table
        node_table = self.query_one("#node-table", DataTable)
        node_table.add_columns("Hostname", "Status", "CPU%", "Memory")

        # Task table
        task_table = self.query_one("#task-table", DataTable)
        task_table.add_columns("ID", "Status", "Node", "Command")

    def update_data(
        self,
        nodes: list[dict],
        tasks: list[dict],
        vps_list: list[dict],
    ) -> None:
        """Update dashboard with new data."""
        self.data_nodes = nodes
        self.data_tasks = tasks
        self.data_vps_list = vps_list

        # Update summary cards
        online = sum(1 for n in nodes if n.get("status") == "online")
        total_cores = sum(n.get("total_cores", 0) for n in nodes)
        running = sum(1 for t in tasks if t.get("status") == "running")
        pending = sum(1 for t in tasks if t.get("status") in ("pending", "assigning"))
        active_vps = sum(1 for v in vps_list if v.get("status") == "running")

        try:
            self.query_one("#card-nodes", SummaryCard).update_value(
                f"{online} / {len(nodes)}"
            )
            self.query_one("#card-cores", SummaryCard).update_value(str(total_cores))
            self.query_one("#card-running", SummaryCard).update_value(str(running))
            self.query_one("#card-pending", SummaryCard).update_value(str(pending))
            self.query_one("#card-vps", SummaryCard).update_value(str(active_vps))
        except Exception:
            pass

        # Update node table
        try:
            node_table = self.query_one("#node-table", DataTable)
            node_table.clear()

            for node in nodes[:8]:
                status = node.get("status", "unknown")
                cpu = node.get("cpu_percent", 0)
                mem_total = node.get("memory_total_bytes", 0)
                mem_used = node.get("memory_used_bytes", 0)
                mem_pct = (mem_used / mem_total * 100) if mem_total else 0

                node_table.add_row(
                    node.get("hostname", ""),
                    create_status_text(status),
                    f"{cpu:.0f}%",
                    f"{mem_pct:.0f}%",
                )
        except Exception:
            pass

        # Update task table
        try:
            task_table = self.query_one("#task-table", DataTable)
            task_table.clear()

            for task in tasks[:10]:
                status = task.get("status", "unknown")
                node = task.get("assigned_node")
                if isinstance(node, dict):
                    node = node.get("hostname", "-")

                task_table.add_row(
                    truncate_id(task.get("task_id", ""), 18),
                    create_status_text(status),
                    node or "-",
                    (task.get("command", "") or "")[:30],
                )
        except Exception:
            pass


class NodesScreen(Widget):
    """Nodes list view."""

    DEFAULT_CSS = """
    NodesScreen {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    NodesScreen #info-bar {
        height: 1;
        color: #888;
        padding: 0 1;
    }

    NodesScreen DataTable {
        height: 1fr;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.data_nodes: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Static("Total: 0 nodes", id="info-bar")
        yield DataTable(id="nodes-table", cursor_type="row")

    def on_mount(self) -> None:
        """Setup table on mount."""
        table = self.query_one("#nodes-table", DataTable)
        table.add_columns(
            "Hostname", "Status", "Cores", "CPU%", "Memory", "GPUs", "URL"
        )

    def update_data(self, nodes: list[dict]) -> None:
        """Update nodes table."""
        self.data_nodes = nodes

        try:
            self.query_one("#info-bar", Static).update(f"Total: {len(nodes)} nodes")
        except Exception:
            pass

        try:
            table = self.query_one("#nodes-table", DataTable)
            table.clear()

            for node in nodes:
                status = node.get("status", "unknown")
                cpu = node.get("cpu_percent", 0)
                mem_total = node.get("memory_total_bytes", 0)
                mem_used = node.get("memory_used_bytes", 0)

                if mem_total:
                    mem_str = f"{format_bytes(mem_used)}/{format_bytes(mem_total)}"
                else:
                    mem_str = "-"

                gpu_info = node.get("gpu_info", [])
                gpu_str = str(len(gpu_info)) if gpu_info else "-"

                table.add_row(
                    node.get("hostname", ""),
                    create_status_text(status),
                    str(node.get("total_cores", 0)),
                    f"{cpu:.0f}%",
                    mem_str,
                    gpu_str,
                    node.get("url", ""),
                )
        except Exception:
            pass

    def get_selected(self) -> dict | None:
        """Get currently selected node."""
        try:
            table = self.query_one("#nodes-table", DataTable)
            if table.cursor_row is not None and table.cursor_row < len(self.data_nodes):
                return self.data_nodes[table.cursor_row]
        except Exception:
            pass
        return None


class TasksScreen(Widget):
    """Tasks list view."""

    DEFAULT_CSS = """
    TasksScreen {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    TasksScreen #filter-bar {
        height: 1;
        padding: 0 1;
    }

    TasksScreen #filter-bar .filter-label {
        color: #888;
    }

    TasksScreen #filter-bar .filter-value {
        color: yellow;
        text-style: bold;
    }

    TasksScreen DataTable {
        height: 1fr;
    }
    """

    FILTERS = ["all", "running", "pending", "completed", "failed"]

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.data_tasks: list[dict] = []
        self.data_filtered_tasks: list[dict] = []
        self.current_filter = "all"

    def compose(self) -> ComposeResult:
        with Horizontal(id="filter-bar"):
            yield Static("Filter: ", classes="filter-label")
            yield Static("all", classes="filter-value", id="filter-value")
            yield Static(
                "  |  Total: 0 tasks", classes="filter-label", id="total-count"
            )
        yield DataTable(id="tasks-table", cursor_type="row")

    def on_mount(self) -> None:
        """Setup table on mount."""
        table = self.query_one("#tasks-table", DataTable)
        table.add_columns("Task ID", "Status", "Node", "Cores", "GPUs", "Command")

    def update_data(self, tasks: list[dict]) -> None:
        """Update tasks table."""
        self.data_tasks = tasks
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Apply current filter and update table."""
        if self.current_filter == "all":
            self.data_filtered_tasks = self.data_tasks
        else:
            self.data_filtered_tasks = [
                t for t in self.data_tasks if t.get("status") == self.current_filter
            ]

        try:
            self.query_one("#filter-value", Static).update(self.current_filter)
            self.query_one("#total-count", Static).update(
                f"  |  Total: {len(self.data_filtered_tasks)} tasks"
            )
        except Exception:
            pass

        try:
            table = self.query_one("#tasks-table", DataTable)
            table.clear()

            for task in self.data_filtered_tasks[:30]:
                status = task.get("status", "unknown")
                node = task.get("assigned_node")
                if isinstance(node, dict):
                    node = node.get("hostname", "-")

                gpus = task.get("required_gpus", [])
                if isinstance(gpus, str):
                    try:
                        gpus = json.loads(gpus)
                    except Exception:
                        gpus = []
                gpu_str = ",".join(map(str, gpus)) if gpus else "-"

                table.add_row(
                    truncate_id(task.get("task_id", ""), 20),
                    create_status_text(status),
                    node or "-",
                    str(task.get("required_cores", 1)),
                    gpu_str,
                    (task.get("command", "") or "")[:40],
                )
        except Exception:
            pass

    def cycle_filter(self) -> None:
        """Cycle through task filters."""
        idx = self.FILTERS.index(self.current_filter)
        self.current_filter = self.FILTERS[(idx + 1) % len(self.FILTERS)]
        self._apply_filter()

    def get_selected(self) -> dict | None:
        """Get currently selected task."""
        try:
            table = self.query_one("#tasks-table", DataTable)
            if table.cursor_row is not None and table.cursor_row < len(
                self.data_filtered_tasks
            ):
                return self.data_filtered_tasks[table.cursor_row]
        except Exception:
            pass
        return None


class VPSScreen(Widget):
    """VPS list view."""

    DEFAULT_CSS = """
    VPSScreen {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    VPSScreen #filter-bar {
        height: 1;
        padding: 0 1;
    }

    VPSScreen #filter-bar .filter-label {
        color: #888;
    }

    VPSScreen #filter-bar .filter-value {
        color: #ff00ff;
        text-style: bold;
    }

    VPSScreen DataTable {
        height: 1fr;
    }
    """

    FILTERS = ["running", "all", "pending", "completed", "failed"]

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.data_vps_list: list[dict] = []
        self.data_filtered_vps: list[dict] = []
        self.current_filter = "running"  # Default to running

    def compose(self) -> ComposeResult:
        with Horizontal(id="filter-bar"):
            yield Static("Filter: ", classes="filter-label")
            yield Static("running", classes="filter-value", id="filter-value")
            yield Static("  |  Total: 0 VPS", classes="filter-label", id="total-count")
        yield DataTable(id="vps-table", cursor_type="row")

    def on_mount(self) -> None:
        """Setup table on mount."""
        table = self.query_one("#vps-table", DataTable)
        table.add_columns("Task ID", "Status", "Node", "SSH Port", "Cores", "Started")

    def update_data(self, vps_list: list[dict]) -> None:
        """Update VPS table."""
        self.data_vps_list = vps_list
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Apply current filter and update table."""
        if self.current_filter == "all":
            self.data_filtered_vps = self.data_vps_list
        else:
            self.data_filtered_vps = [
                v for v in self.data_vps_list if v.get("status") == self.current_filter
            ]

        try:
            self.query_one("#filter-value", Static).update(self.current_filter)
            self.query_one("#total-count", Static).update(
                f"  |  Total: {len(self.data_filtered_vps)} VPS"
            )
        except Exception:
            pass

        try:
            table = self.query_one("#vps-table", DataTable)
            table.clear()

            for vps in self.data_filtered_vps[:20]:
                status = vps.get("status", "unknown")
                node = vps.get("assigned_node")
                if isinstance(node, dict):
                    node = node.get("hostname", "-")

                ssh_port = vps.get("ssh_port")
                ssh_str = str(ssh_port) if ssh_port else "-"

                started = vps.get("started_at", "-")
                if started and isinstance(started, str) and len(started) > 19:
                    started = started[:19]

                table.add_row(
                    truncate_id(vps.get("task_id", ""), 20),
                    create_status_text(status),
                    node or "-",
                    ssh_str,
                    str(vps.get("required_cores", 0)),
                    str(started) if started else "-",
                )
        except Exception:
            pass

    def cycle_filter(self) -> None:
        """Cycle through VPS filters."""
        idx = self.FILTERS.index(self.current_filter)
        self.current_filter = self.FILTERS[(idx + 1) % len(self.FILTERS)]
        self._apply_filter()

    def get_selected(self) -> dict | None:
        """Get currently selected VPS."""
        try:
            table = self.query_one("#vps-table", DataTable)
            if table.cursor_row is not None and table.cursor_row < len(
                self.data_filtered_vps
            ):
                return self.data_filtered_vps[table.cursor_row]
        except Exception:
            pass
        return None


class DockerScreen(Widget):
    """Docker containers list view."""

    DEFAULT_CSS = """
    DockerScreen {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    DockerScreen #info-bar {
        height: 1;
        color: #888;
        padding: 0 1;
    }

    DockerScreen DataTable {
        height: 1fr;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.data_containers: list[dict] = []
        self.data_tarballs: dict = {}

    def compose(self) -> ComposeResult:
        yield Static("Total: 0 containers  |  Tarballs: 0", id="info-bar")
        yield DataTable(id="docker-table", cursor_type="row")

    def on_mount(self) -> None:
        """Setup table on mount."""
        table = self.query_one("#docker-table", DataTable)
        table.add_columns("Environment", "Status", "Image", "Tarball")

    def update_data(self, containers: list[dict], tarballs: dict) -> None:
        """Update Docker table."""
        self.data_containers = containers
        self.data_tarballs = tarballs

        try:
            self.query_one("#info-bar", Static).update(
                f"Total: {len(containers)} containers  |  Tarballs: {len(tarballs)}"
            )
        except Exception:
            pass

        try:
            table = self.query_one("#docker-table", DataTable)
            table.clear()

            for container in containers[:20]:
                env_name = container.get("env_name", container.get("name", ""))
                status = container.get("status", "unknown")
                image = container.get("image", "-")
                has_tarball = env_name in tarballs

                table.add_row(
                    env_name,
                    create_status_text(status),
                    image,
                    "Yes" if has_tarball else "-",
                )
        except Exception:
            pass

    def get_selected(self) -> dict | None:
        """Get currently selected container."""
        try:
            table = self.query_one("#docker-table", DataTable)
            if table.cursor_row is not None and table.cursor_row < len(
                self.data_containers
            ):
                return self.data_containers[table.cursor_row]
        except Exception:
            pass
        return None


class TaskDetailScreen(Screen):
    """Task detail view screen."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("k", "kill_task", "Kill"),
        Binding("o", "show_stdout", "Full stdout"),
        Binding("e", "show_stderr", "Full stderr"),
    ]

    DEFAULT_CSS = """
    TaskDetailScreen {
        height: 100%;
        width: 100%;
        background: #0d0d1a;
    }

    #detail-container {
        height: 100%;
        padding: 1;
    }

    #info-panel {
        height: auto;
        border: solid #333;
        padding: 1;
        margin-bottom: 1;
    }

    #info-panel .info-row {
        height: 1;
        layout: horizontal;
    }

    #info-panel .info-label {
        width: 15;
        color: #888;
    }

    #info-panel .info-value {
        width: 1fr;
    }

    #logs-container {
        height: 1fr;
        layout: horizontal;
    }

    #stdout-panel, #stderr-panel {
        width: 1fr;
        height: 100%;
        border: solid green;
        margin: 0 1 0 0;
    }

    #stderr-panel {
        border: solid red;
        margin-right: 0;
    }

    .log-title {
        background: #333;
        padding: 0 1;
        text-style: bold;
    }

    .log-content {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }

    #actions-bar {
        height: 1;
        dock: bottom;
        background: #1a1a2e;
        padding: 0 1;
    }
    """

    def __init__(self, task_data: dict, get_stdout_fn, get_stderr_fn, kill_fn) -> None:
        super().__init__()
        self._task_data = task_data
        self._get_stdout = get_stdout_fn
        self._get_stderr = get_stderr_fn
        self._kill_fn = kill_fn

    def compose(self) -> ComposeResult:
        task_info = self._task_data
        task_id = str(task_info.get("task_id", ""))
        status = task_info.get("status", "unknown")

        node = task_info.get("assigned_node")
        if isinstance(node, dict):
            node = node.get("hostname", "-")

        with Vertical(id="detail-container"):
            yield Static(
                f"Task Detail: {truncate_id(task_id, 20)}", classes="screen-title"
            )

            with Vertical(id="info-panel"):
                with Horizontal(classes="info-row"):
                    yield Static("Task ID:", classes="info-label")
                    yield Static(task_id, classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("Status:", classes="info-label")
                    yield Static(create_status_text(status), classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("Node:", classes="info-label")
                    yield Static(node or "-", classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("Command:", classes="info-label")
                    yield Static(
                        task_info.get("command", "-") or "-", classes="info-value"
                    )

                with Horizontal(classes="info-row"):
                    yield Static("Cores:", classes="info-label")
                    yield Static(
                        str(task_info.get("required_cores", 1)), classes="info-value"
                    )

                with Horizontal(classes="info-row"):
                    yield Static("Created:", classes="info-label")
                    yield Static(
                        str(task_info.get("created_at", "-"))[:19], classes="info-value"
                    )

                with Horizontal(classes="info-row"):
                    yield Static("Started:", classes="info-label")
                    started = task_info.get("started_at")
                    yield Static(
                        str(started)[:19] if started else "-", classes="info-value"
                    )

                if task_info.get("exit_code") is not None:
                    with Horizontal(classes="info-row"):
                        yield Static("Exit Code:", classes="info-label")
                        exit_code = task_info.get("exit_code")
                        style = "green" if exit_code == 0 else "red"
                        yield Static(
                            Text(str(exit_code), style=style), classes="info-value"
                        )

            with Horizontal(id="logs-container"):
                with Vertical(id="stdout-panel"):
                    yield Static("stdout", classes="log-title")
                    yield Static(
                        "[dim]Loading...[/dim]",
                        classes="log-content",
                        id="stdout-content",
                    )

                with Vertical(id="stderr-panel"):
                    yield Static("stderr", classes="log-title")
                    yield Static(
                        "[dim]Loading...[/dim]",
                        classes="log-content",
                        id="stderr-content",
                    )

        yield Static(
            "[bold]Esc[/bold]-Back  [bold]k[/bold]-Kill  [bold]o[/bold]-Full stdout  [bold]e[/bold]-Full stderr",
            id="actions-bar",
        )

    def on_mount(self) -> None:
        """Load logs on mount and set up periodic refresh."""
        self._load_logs()
        # Refresh logs every 2 seconds if task is still running
        self.set_interval(2.0, self._periodic_refresh)

    def _periodic_refresh(self) -> None:
        """Periodically refresh logs if task is running."""
        status = self._task_data.get("status", "")
        if status in ("running", "pending", "assigning"):
            self._load_logs()

    @work(exclusive=True)
    async def _load_logs(self) -> None:
        """Load stdout and stderr."""
        task_id = str(self._task_data.get("task_id", ""))

        try:
            stdout = await self._get_stdout(task_id)
            if stdout:
                lines = stdout.strip().split("\n")
                if len(lines) > 30:
                    display = f"... ({len(lines) - 30} lines hidden)\n" + "\n".join(
                        lines[-30:]
                    )
                else:
                    display = stdout.strip()
            else:
                display = "[dim]No output[/dim]"

            try:
                self.query_one("#stdout-content", Static).update(display)
            except Exception:
                pass
        except Exception as e:
            try:
                self.query_one("#stdout-content", Static).update(
                    f"[red]Error: {e}[/red]"
                )
            except Exception:
                pass

        try:
            stderr = await self._get_stderr(task_id)
            if stderr:
                lines = stderr.strip().split("\n")
                if len(lines) > 30:
                    display = f"... ({len(lines) - 30} lines hidden)\n" + "\n".join(
                        lines[-30:]
                    )
                else:
                    display = stderr.strip()
            else:
                display = "[dim]No errors[/dim]"

            try:
                self.query_one("#stderr-content", Static).update(display)
            except Exception:
                pass
        except Exception as e:
            try:
                self.query_one("#stderr-content", Static).update(
                    f"[red]Error: {e}[/red]"
                )
            except Exception:
                pass

    def action_go_back(self) -> None:
        """Go back to task list."""
        self.app.pop_screen()

    def action_kill_task(self) -> None:
        """Kill the task."""
        if self._task_data.get("status") == "running":
            self._kill_fn(str(self._task_data.get("task_id", "")))
            self.app.pop_screen()

    def action_show_stdout(self) -> None:
        """Show full stdout."""
        # TODO: Implement full stdout view
        self.notify("Full stdout view not implemented yet")

    def action_show_stderr(self) -> None:
        """Show full stderr."""
        # TODO: Implement full stderr view
        self.notify("Full stderr view not implemented yet")


class NodeDetailScreen(Screen):
    """Node detail view screen."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]

    DEFAULT_CSS = """
    NodeDetailScreen {
        height: 100%;
        width: 100%;
        background: #0d0d1a;
    }

    #detail-container {
        height: 100%;
        padding: 1;
    }

    #info-panel {
        height: auto;
        border: solid #333;
        padding: 1;
    }

    #info-panel .info-row {
        height: 1;
        layout: horizontal;
    }

    #info-panel .info-label {
        width: 15;
        color: #888;
    }

    #info-panel .info-value {
        width: 1fr;
    }

    #gpu-panel {
        height: auto;
        border: solid #00d4ff;
        padding: 1;
        margin-top: 1;
    }

    .panel-title {
        text-style: bold;
        color: #00d4ff;
    }

    #actions-bar {
        height: 1;
        dock: bottom;
        background: #1a1a2e;
        padding: 0 1;
    }
    """

    def __init__(self, node: dict) -> None:
        super().__init__()
        self._node = node

    def compose(self) -> ComposeResult:
        node = self._node
        hostname = node.get("hostname", "")
        status = node.get("status", "unknown")

        cpu = node.get("cpu_percent", 0)
        mem_total = node.get("memory_total_bytes", 0)
        mem_used = node.get("memory_used_bytes", 0)
        mem_pct = (mem_used / mem_total * 100) if mem_total else 0

        with Vertical(id="detail-container"):
            yield Static(f"Node Detail: {hostname}", classes="screen-title")

            with Vertical(id="info-panel"):
                with Horizontal(classes="info-row"):
                    yield Static("Hostname:", classes="info-label")
                    yield Static(hostname, classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("Status:", classes="info-label")
                    yield Static(create_status_text(status), classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("URL:", classes="info-label")
                    yield Static(node.get("url", "-"), classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("Cores:", classes="info-label")
                    yield Static(str(node.get("total_cores", 0)), classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("CPU Usage:", classes="info-label")
                    yield Static(f"{cpu:.1f}%", classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("Memory:", classes="info-label")
                    yield Static(
                        f"{format_bytes(mem_used)} / {format_bytes(mem_total)} ({mem_pct:.1f}%)",
                        classes="info-value",
                    )

            # GPU info
            gpu_info = node.get("gpu_info", [])
            if gpu_info:
                with Vertical(id="gpu-panel"):
                    yield Static(f"GPUs ({len(gpu_info)})", classes="panel-title")
                    for gpu in gpu_info:
                        gpu_id = gpu.get("gpu_id", 0)
                        name = gpu.get("name", "Unknown")
                        mem = gpu.get("memory_total_mib", 0)
                        util = gpu.get("gpu_utilization", "?")
                        temp = gpu.get("temperature", "?")
                        yield Static(
                            f"  [{gpu_id}] {name} - {mem}MiB - {util}% util - {temp}°C"
                        )

        yield Static("[bold]Esc[/bold]-Back", id="actions-bar")

    def action_go_back(self) -> None:
        """Go back to node list."""
        self.app.pop_screen()


class VPSDetailScreen(Screen):
    """VPS detail view screen."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("k", "stop_vps", "Stop"),
        Binding("p", "port_forward", "Port Forward"),
    ]

    DEFAULT_CSS = """
    VPSDetailScreen {
        height: 100%;
        width: 100%;
        background: #0d0d1a;
    }

    #detail-container {
        height: 100%;
        padding: 1;
    }

    #info-panel {
        height: auto;
        border: solid #ff00ff;
        padding: 1;
    }

    #info-panel .info-row {
        height: 1;
        layout: horizontal;
    }

    #info-panel .info-label {
        width: 15;
        color: #888;
    }

    #info-panel .info-value {
        width: 1fr;
    }

    .ssh-command {
        background: #333;
        padding: 0 1;
        margin-top: 1;
        color: #00ff00;
    }

    #actions-bar {
        height: 1;
        dock: bottom;
        background: #1a1a2e;
        padding: 0 1;
    }
    """

    def __init__(self, vps: dict, stop_fn) -> None:
        super().__init__()
        self._vps = vps
        self._stop_fn = stop_fn

    def compose(self) -> ComposeResult:
        vps = self._vps
        task_id = str(vps.get("task_id", ""))
        status = vps.get("status", "unknown")

        node = vps.get("assigned_node")
        if isinstance(node, dict):
            node_hostname = node.get("hostname", "-")
            node_url = node.get("url", "")
        else:
            node_hostname = node or "-"
            node_url = ""

        ssh_port = vps.get("ssh_port")

        with Vertical(id="detail-container"):
            yield Static(
                f"VPS Detail: {truncate_id(task_id, 20)}", classes="screen-title"
            )

            with Vertical(id="info-panel"):
                with Horizontal(classes="info-row"):
                    yield Static("Task ID:", classes="info-label")
                    yield Static(task_id, classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("Status:", classes="info-label")
                    yield Static(create_status_text(status), classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("Node:", classes="info-label")
                    yield Static(node_hostname, classes="info-value")

                with Horizontal(classes="info-row"):
                    yield Static("SSH Port:", classes="info-label")
                    yield Static(
                        str(ssh_port) if ssh_port else "-", classes="info-value"
                    )

                with Horizontal(classes="info-row"):
                    yield Static("Cores:", classes="info-label")
                    yield Static(
                        str(vps.get("required_cores", 0)), classes="info-value"
                    )

                with Horizontal(classes="info-row"):
                    yield Static("Container:", classes="info-label")
                    yield Static(
                        vps.get("container_name", "-") or "-", classes="info-value"
                    )

                with Horizontal(classes="info-row"):
                    yield Static("Started:", classes="info-label")
                    started = vps.get("started_at")
                    yield Static(
                        str(started)[:19] if started else "-", classes="info-value"
                    )

            # SSH command
            if ssh_port and node_url:
                host = (
                    node_url.replace("http://", "")
                    .replace("https://", "")
                    .split(":")[0]
                )
                yield Static(
                    f"SSH Command: ssh -p {ssh_port} root@{host}", classes="ssh-command"
                )

        yield Static(
            "[bold]Esc[/bold]-Back  [bold]k[/bold]-Stop VPS  [bold]p[/bold]-Port Forward",
            id="actions-bar",
        )

    def action_go_back(self) -> None:
        """Go back to VPS list."""
        self.app.pop_screen()

    def action_stop_vps(self) -> None:
        """Stop the VPS."""
        if self._vps.get("status") == "running":
            self._stop_fn(str(self._vps.get("task_id", "")))
            self.app.pop_screen()

    def action_port_forward(self) -> None:
        """Show port forward dialog."""
        from kohakuriver.cli.tui.dashboard.modals import PortForwardModal

        if self._vps.get("status") == "running":
            task_id = self._vps.get("task_id", "")
            self.app.push_screen(PortForwardModal(task_id))
