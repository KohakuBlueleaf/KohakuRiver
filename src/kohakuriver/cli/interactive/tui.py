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

import sys
import time

IS_WINDOWS = sys.platform == "win32"

if not IS_WINDOWS:
    import termios
    import tty

from rich.console import Console
from rich.layout import Layout
from rich.live import Live

from kohakuriver.cli import client
from kohakuriver.cli.interactive.actions import TUIActions
from kohakuriver.cli.interactive.input_handler import InputReader
from kohakuriver.cli.interactive.renderers import (
    View,
    render_dashboard,
    render_docker,
    render_docker_detail,
    render_footer,
    render_header,
    render_node_detail,
    render_nodes,
    render_task_detail,
    render_tasks,
    render_vps,
    render_vps_detail,
)


class TUIApp(TUIActions):
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

    def _create_layout(self) -> Layout:
        """Create the main layout."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        return layout

    def render(self) -> Layout:
        """Render the full TUI."""
        layout = self._create_layout()

        layout["header"].update(render_header(self.current_view, self.previous_view))
        layout["footer"].update(
            render_footer(self.current_view, self.error_message, self.status_message)
        )

        match self.current_view:
            case View.DASHBOARD:
                layout["body"].update(
                    render_dashboard(self.nodes, self.tasks, self.vps_list)
                )
            case View.NODES:
                layout["body"].update(render_nodes(self.nodes, self.selected_index))
            case View.TASKS:
                layout["body"].update(
                    render_tasks(self.tasks, self.task_filter, self.selected_index)
                )
            case View.VPS:
                layout["body"].update(render_vps(self.vps_list, self.selected_index))
            case View.DOCKER:
                layout["body"].update(
                    render_docker(self.containers, self.tarballs, self.selected_index)
                )
            case View.TASK_DETAIL:
                stdout_content = ""
                stderr_content = ""
                if self.detail_item:
                    task_id = str(self.detail_item.get("task_id", ""))
                    try:
                        stdout_content = client.get_task_stdout(task_id)
                        stderr_content = client.get_task_stderr(task_id)
                    except Exception:
                        pass
                layout["body"].update(
                    render_task_detail(self.detail_item, stdout_content, stderr_content)
                )
            case View.VPS_DETAIL:
                layout["body"].update(render_vps_detail(self.detail_item))
            case View.NODE_DETAIL:
                layout["body"].update(render_node_detail(self.detail_item))
            case View.DOCKER_DETAIL:
                layout["body"].update(
                    render_docker_detail(self.detail_item, self.tarballs)
                )

        return layout

    def _restore_terminal(self):
        """Restore terminal to normal mode for input."""
        if self.old_settings and not IS_WINDOWS:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def _setup_terminal(self):
        """Setup terminal for raw input mode."""
        if IS_WINDOWS:
            return
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

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

    def run(self) -> None:
        """Run the TUI application."""
        # Initial data fetch
        self.fetch_data()

        # Setup terminal for non-blocking input
        if not IS_WINDOWS:
            self.old_settings = termios.tcgetattr(sys.stdin)

        try:
            if not IS_WINDOWS:
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
            if not IS_WINDOWS and self.old_settings:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)


def run_tui(refresh_rate: float = 2.0) -> None:
    """Run the TUI application."""
    app = TUIApp(refresh_rate=refresh_rate)
    app.run()
