"""
Main TUI Dashboard application using Textual.

Cross-platform cluster management TUI with:
- Dashboard overview
- Node/Task/VPS/Docker list views
- Modal dialogs for creating tasks/VPS
- Detail screens
"""

import asyncio
import os
from datetime import datetime
from enum import Enum

import httpx
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, TabbedContent, TabPane, Footer

from kohakuriver.cli.tui.dashboard.screens import (
    DashboardScreen,
    NodesScreen,
    TasksScreen,
    VPSScreen,
    DockerScreen,
    TaskDetailScreen,
    NodeDetailScreen,
    VPSDetailScreen,
)
from kohakuriver.cli.tui.dashboard.modals import (
    CreateTaskModal,
    CreateVPSModal,
    CreateContainerModal,
    ConfirmModal,
)
from kohakuriver.cli.tui.dashboard.widgets import HeaderBar, FooterBar


class View(Enum):
    """Available views."""

    DASHBOARD = "dashboard"
    NODES = "nodes"
    TASKS = "tasks"
    VPS = "vps"
    DOCKER = "docker"


class DashboardApp(App):
    """
    Textual-based TUI Dashboard for KohakuRiver cluster management.

    Cross-platform with modal dialogs for task/VPS creation.
    """

    TITLE = "KohakuRiver Cluster Manager"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("1", "view_dashboard", "Dashboard"),
        Binding("2", "view_nodes", "Nodes"),
        Binding("3", "view_tasks", "Tasks"),
        Binding("4", "view_vps", "VPS"),
        Binding("5", "view_docker", "Docker"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_item", "New"),
        Binding("f", "filter", "Filter"),
        Binding("enter", "show_detail", "Details"),
    ]

    CSS = """
    DashboardApp {
        background: #0d0d1a;
    }

    #main-tabs {
        height: 1fr;
        width: 100%;
    }

    #main-tabs > ContentSwitcher {
        width: 100%;
        height: 1fr;
    }

    #main-tabs TabPane {
        width: 100%;
        height: 100%;
        padding: 0;
    }

    /* Screen widgets inside TabPanes need explicit sizing */
    DashboardScreen,
    NodesScreen,
    TasksScreen,
    VPSScreen,
    DockerScreen {
        width: 100%;
        height: 100%;
    }

    .screen-title {
        text-style: bold;
        color: #00d4ff;
        padding: 0 0 1 0;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #1a1a2e;
        padding: 0 1;
        color: #888;
    }

    #status-bar .error {
        color: red;
    }

    #status-bar .success {
        color: green;
    }
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        refresh_rate: float = 2.0,
    ) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._refresh_rate = refresh_rate

        self._http_client: httpx.AsyncClient | None = None
        self._current_view = View.DASHBOARD

        # Cached data (using data_ prefix to avoid conflicts with Textual internals)
        self.data_nodes: list[dict] = []
        self.data_tasks: list[dict] = []
        self.data_vps_list: list[dict] = []
        self.data_containers: list[dict] = []
        self.data_tarballs: dict = {}

        # Status
        self._status_message: str = ""
        self._error_message: str = ""

    def compose(self) -> ComposeResult:
        yield HeaderBar()

        with TabbedContent(id="main-tabs"):
            with TabPane("Dashboard [1]", id="tab-dashboard"):
                yield DashboardScreen(id="dashboard-screen")

            with TabPane("Nodes [2]", id="tab-nodes"):
                yield NodesScreen(id="nodes-screen")

            with TabPane("Tasks [3]", id="tab-tasks"):
                yield TasksScreen(id="tasks-screen")

            with TabPane("VPS [4]", id="tab-vps"):
                yield VPSScreen(id="vps-screen")

            with TabPane("Docker [5]", id="tab-docker"):
                yield DockerScreen(id="docker-screen")

        yield Static("", id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize on mount."""
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Initial data fetch
        await self._fetch_data()

        # Set up auto-refresh
        self.set_interval(self._refresh_rate, self._auto_refresh)

        # Set up time update
        self.set_interval(1.0, self._update_time)

    async def on_unmount(self) -> None:
        """Cleanup on unmount."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _update_time(self) -> None:
        """Update header time."""
        try:
            header = self.query_one(HeaderBar)
            header.update_time()
        except Exception:
            pass

    async def _auto_refresh(self) -> None:
        """Auto-refresh data."""
        await self._fetch_data()

    def _get_api_url(self, endpoint: str) -> str:
        """Build API URL."""
        return f"http://{self._host}:{self._port}/api/{endpoint}"

    async def _fetch_data(self) -> None:
        """Fetch all data from API."""
        if not self._http_client:
            return

        try:
            # Fetch nodes (endpoint is /nodes, not /nodes/status)
            try:
                resp = await self._http_client.get(self._get_api_url("nodes"))
                resp.raise_for_status()
                data = resp.json()
                self.data_nodes = data if isinstance(data, list) else []
            except Exception:
                self.data_nodes = []

            # Fetch tasks
            try:
                resp = await self._http_client.get(
                    self._get_api_url("tasks"),
                    params={"limit": 50},
                )
                resp.raise_for_status()
                data = resp.json()
                self.data_tasks = data if isinstance(data, list) else []
            except Exception:
                self.data_tasks = []

            # Fetch VPS
            try:
                resp = await self._http_client.get(
                    self._get_api_url("vps"),
                    params={"active_only": "false"},
                )
                resp.raise_for_status()
                data = resp.json()
                self.data_vps_list = data if isinstance(data, list) else []
            except Exception:
                self.data_vps_list = []

            # Fetch containers (endpoint is /docker/host/containers)
            try:
                resp = await self._http_client.get(
                    self._get_api_url("docker/host/containers")
                )
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    self.data_containers = data
                elif isinstance(data, dict):
                    self.data_containers = data.get("containers", [])
                else:
                    self.data_containers = []
            except Exception:
                self.data_containers = []

            # Fetch tarballs (endpoint is /docker/list)
            try:
                resp = await self._http_client.get(self._get_api_url("docker/list"))
                resp.raise_for_status()
                data = resp.json()
                self.data_tarballs = (
                    data if isinstance(data, dict) and "detail" not in data else {}
                )
            except Exception:
                self.data_tarballs = {}

            self._error_message = ""
            self._update_screens()

        except Exception as e:
            self._error_message = f"Connection error: {e}"
            self._update_status()

    def _update_screens(self) -> None:
        """Update all screen data."""
        try:
            dashboard = self.query_one("#dashboard-screen", DashboardScreen)
            dashboard.update_data(self.data_nodes, self.data_tasks, self.data_vps_list)
        except Exception:
            pass

        try:
            nodes = self.query_one("#nodes-screen", NodesScreen)
            nodes.update_data(self.data_nodes)
        except Exception:
            pass

        try:
            tasks = self.query_one("#tasks-screen", TasksScreen)
            tasks.update_data(self.data_tasks)
        except Exception:
            pass

        try:
            vps = self.query_one("#vps-screen", VPSScreen)
            vps.update_data(self.data_vps_list)
        except Exception:
            pass

        try:
            docker = self.query_one("#docker-screen", DockerScreen)
            docker.update_data(self.data_containers, self.data_tarballs)
        except Exception:
            pass

        self._update_status()

    def _update_status(self) -> None:
        """Update status bar."""
        try:
            status_bar = self.query_one("#status-bar", Static)
            if self._error_message:
                status_bar.update(f"[red]Error: {self._error_message}[/red]")
            elif self._status_message:
                status_bar.update(f"[green]{self._status_message}[/green]")
            else:
                status_bar.update(
                    f"[dim]Last update: {datetime.now().strftime('%H:%M:%S')}[/dim]"
                )
        except Exception:
            pass

    def _set_status(self, message: str, is_error: bool = False) -> None:
        """Set status message."""
        if is_error:
            self._error_message = message
            self._status_message = ""
        else:
            self._status_message = message
            self._error_message = ""
        self._update_status()

        # Clear status after a few seconds
        if not is_error:
            self.set_timer(3.0, lambda: self._clear_status())

    def _clear_status(self) -> None:
        """Clear status message."""
        self._status_message = ""
        self._update_status()

    # =========================================================================
    # View Actions
    # =========================================================================

    def action_view_dashboard(self) -> None:
        """Switch to dashboard view."""
        self._current_view = View.DASHBOARD
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = "tab-dashboard"
        except Exception:
            pass

    def action_view_nodes(self) -> None:
        """Switch to nodes view."""
        self._current_view = View.NODES
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = "tab-nodes"
        except Exception:
            pass

    def action_view_tasks(self) -> None:
        """Switch to tasks view."""
        self._current_view = View.TASKS
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = "tab-tasks"
        except Exception:
            pass

    def action_view_vps(self) -> None:
        """Switch to VPS view."""
        self._current_view = View.VPS
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = "tab-vps"
        except Exception:
            pass

    def action_view_docker(self) -> None:
        """Switch to Docker view."""
        self._current_view = View.DOCKER
        try:
            tabs = self.query_one("#main-tabs", TabbedContent)
            tabs.active = "tab-docker"
        except Exception:
            pass

    @on(TabbedContent.TabActivated)
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Handle tab activation."""
        tab_id = event.pane.id
        if tab_id == "tab-dashboard":
            self._current_view = View.DASHBOARD
        elif tab_id == "tab-nodes":
            self._current_view = View.NODES
        elif tab_id == "tab-tasks":
            self._current_view = View.TASKS
        elif tab_id == "tab-vps":
            self._current_view = View.VPS
        elif tab_id == "tab-docker":
            self._current_view = View.DOCKER

    # =========================================================================
    # Data Actions
    # =========================================================================

    async def action_refresh(self) -> None:
        """Refresh data."""
        await self._fetch_data()
        self._set_status("Data refreshed")

    def action_filter(self) -> None:
        """Cycle filter (tasks and VPS)."""
        if self._current_view == View.TASKS:
            try:
                tasks_screen = self.query_one("#tasks-screen", TasksScreen)
                tasks_screen.cycle_filter()
            except Exception:
                pass
        elif self._current_view == View.VPS:
            try:
                vps_screen = self.query_one("#vps-screen", VPSScreen)
                vps_screen.cycle_filter()
            except Exception:
                pass

    def action_new_item(self) -> None:
        """Create new item based on current view."""
        if self._current_view == View.TASKS:
            self._create_task()
        elif self._current_view == View.VPS:
            self._create_vps()
        elif self._current_view == View.DOCKER:
            self._create_container()

    def action_show_detail(self) -> None:
        """Show detail for selected item."""
        if self._current_view == View.NODES:
            self._show_node_detail()
        elif self._current_view == View.TASKS:
            self._show_task_detail()
        elif self._current_view == View.VPS:
            self._show_vps_detail()

    # =========================================================================
    # Detail Views
    # =========================================================================

    def _show_node_detail(self) -> None:
        """Show node detail screen."""
        try:
            nodes_screen = self.query_one("#nodes-screen", NodesScreen)
            node = nodes_screen.get_selected()
            if node:
                self.push_screen(NodeDetailScreen(node))
        except Exception:
            pass

    def _show_task_detail(self) -> None:
        """Show task detail screen."""
        try:
            tasks_screen = self.query_one("#tasks-screen", TasksScreen)
            task = tasks_screen.get_selected()
            if task:
                screen = TaskDetailScreen(
                    task,
                    self._get_task_stdout,
                    self._get_task_stderr,
                    self._kill_task,
                )
                self.push_screen(screen)
        except Exception:
            pass

    def _show_vps_detail(self) -> None:
        """Show VPS detail screen."""
        try:
            vps_screen = self.query_one("#vps-screen", VPSScreen)
            vps = vps_screen.get_selected()
            if vps:
                screen = VPSDetailScreen(vps, self._stop_vps)
                self.push_screen(screen)
        except Exception:
            pass

    # =========================================================================
    # API Operations
    # =========================================================================

    async def _get_task_stdout(self, task_id: str) -> str:
        """Get task stdout."""
        if not self._http_client:
            return ""
        try:
            resp = await self._http_client.get(
                self._get_api_url(f"tasks/{task_id}/stdout")
            )
            resp.raise_for_status()
            return resp.text
        except Exception:
            return ""

    async def _get_task_stderr(self, task_id: str) -> str:
        """Get task stderr."""
        if not self._http_client:
            return ""
        try:
            resp = await self._http_client.get(
                self._get_api_url(f"tasks/{task_id}/stderr")
            )
            resp.raise_for_status()
            return resp.text
        except Exception:
            return ""

    def _kill_task(self, task_id: str) -> None:
        """Kill a task."""
        self._do_kill_task(task_id)

    @work(exclusive=True)
    async def _do_kill_task(self, task_id: str) -> None:
        """Kill a task (async worker)."""
        if not self._http_client:
            return
        try:
            resp = await self._http_client.post(
                self._get_api_url(f"tasks/{task_id}/kill")
            )
            resp.raise_for_status()
            self._set_status(f"Task {task_id[-12:]} killed")
            await self._fetch_data()
        except Exception as e:
            self._set_status(f"Failed to kill task: {e}", is_error=True)

    def _stop_vps(self, task_id: str) -> None:
        """Stop a VPS."""
        self._do_stop_vps(task_id)

    @work(exclusive=True)
    async def _do_stop_vps(self, task_id: str) -> None:
        """Stop a VPS (async worker)."""
        if not self._http_client:
            return
        try:
            resp = await self._http_client.post(
                self._get_api_url(f"vps/{task_id}/stop")
            )
            resp.raise_for_status()
            self._set_status(f"VPS {task_id[-12:]} stopped")
            await self._fetch_data()
        except Exception as e:
            self._set_status(f"Failed to stop VPS: {e}", is_error=True)

    # =========================================================================
    # Create Operations
    # =========================================================================

    def _create_task(self) -> None:
        """Show create task modal."""
        container_names = [
            c.get("env_name", c.get("name", "")) for c in self.data_containers
        ]
        modal = CreateTaskModal(nodes=self.data_nodes, containers=container_names)
        self.push_screen(modal, self._on_task_modal_dismiss)

    def _on_task_modal_dismiss(self, result: dict | None) -> None:
        """Handle task modal dismissal."""
        if result:
            self._do_create_task(result)

    @work(exclusive=True)
    async def _do_create_task(self, data: dict) -> None:
        """Create task (async worker)."""
        if not self._http_client:
            return

        try:
            payload = {
                "command": data["command"],
                "arguments": data.get("arguments", []),
                "required_cores": data.get("cores", 0),
            }

            if data.get("target"):
                payload["targets"] = [data["target"]]
            if data.get("container"):
                payload["container_name"] = data["container"]

            resp = await self._http_client.post(
                self._get_api_url("submit"),
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            task_ids = result.get("task_ids", result.get("task_id", []))

            if task_ids:
                self._set_status(f"Task created: {task_ids[0]}")
            else:
                self._set_status("Failed to create task", is_error=True)

            await self._fetch_data()

        except Exception as e:
            self._set_status(f"Failed to create task: {e}", is_error=True)

    def _create_vps(self) -> None:
        """Show create VPS modal."""
        container_names = [
            c.get("env_name", c.get("name", "")) for c in self.data_containers
        ]
        modal = CreateVPSModal(nodes=self.data_nodes, containers=container_names)
        self.push_screen(modal, self._on_vps_modal_dismiss)

    def _on_vps_modal_dismiss(self, result: dict | None) -> None:
        """Handle VPS modal dismissal."""
        if result:
            self._do_create_vps(result)

    @work(exclusive=True)
    async def _do_create_vps(self, data: dict) -> None:
        """Create VPS (async worker)."""
        if not self._http_client:
            return

        try:
            payload = {
                "ssh_key_mode": data.get("ssh_key_mode", "generate"),
                "required_cores": data.get("cores", 0),
            }

            if data.get("target"):
                payload["target_hostname"] = data["target"]
            if data.get("container"):
                payload["container_name"] = data["container"]
            if data.get("gpu_ids"):
                payload["required_gpus"] = data["gpu_ids"]
            if data.get("public_key"):
                payload["ssh_public_key"] = data["public_key"]

            resp = await self._http_client.post(
                self._get_api_url("vps/create"),
                json=payload,
            )
            resp.raise_for_status()
            result = resp.json()
            task_id = result.get("task_id")

            if task_id:
                ssh_port = result.get("ssh_port", "?")
                self._set_status(f"VPS created: {task_id} (SSH port: {ssh_port})")

                # Save generated key if applicable
                if data.get("ssh_key_mode") == "generate" and result.get(
                    "ssh_private_key"
                ):
                    self._save_ssh_key(task_id, result)
            else:
                self._set_status("Failed to create VPS", is_error=True)

            await self._fetch_data()

        except Exception as e:
            self._set_status(f"Failed to create VPS: {e}", is_error=True)

    def _save_ssh_key(self, task_id: str, result: dict) -> None:
        """Save generated SSH key."""
        try:
            key_dir = os.path.expanduser("~/.ssh/hakuriver")
            os.makedirs(key_dir, exist_ok=True)
            key_path = os.path.join(key_dir, f"vps_{task_id}")

            with open(key_path, "w") as f:
                f.write(result["ssh_private_key"])
            os.chmod(key_path, 0o600)

            if result.get("ssh_public_key"):
                with open(f"{key_path}.pub", "w") as f:
                    f.write(result["ssh_public_key"])

            self.notify(f"SSH key saved: {key_path}")
        except Exception as e:
            self.notify(f"Failed to save SSH key: {e}", severity="warning")

    def _create_container(self) -> None:
        """Show create container modal."""
        modal = CreateContainerModal()
        self.push_screen(modal, self._on_container_modal_dismiss)

    def _on_container_modal_dismiss(self, result: dict | None) -> None:
        """Handle container modal dismissal."""
        if result:
            self._do_create_container(result)

    @work(exclusive=True)
    async def _do_create_container(self, data: dict) -> None:
        """Create container (async worker)."""
        if not self._http_client:
            return

        try:
            resp = await self._http_client.post(
                self._get_api_url("docker/host/create"),
                json={
                    "image_name": data["image"],
                    "container_name": data["name"],
                },
            )
            resp.raise_for_status()
            self._set_status(f"Container '{data['name']}' created")
            await self._fetch_data()

        except Exception as e:
            self._set_status(f"Failed to create container: {e}", is_error=True)


def run_dashboard(
    host: str = "localhost", port: int = 8000, refresh_rate: float = 2.0
) -> None:
    """Run the TUI Dashboard application."""
    app = DashboardApp(host=host, port=port, refresh_rate=refresh_rate)
    app.run()
