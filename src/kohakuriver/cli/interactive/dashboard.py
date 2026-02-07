"""TUI dashboard for cluster monitoring."""

import time
from datetime import datetime

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from kohakuriver.cli import client
from kohakuriver.cli.output import console, format_status


def create_dashboard_layout() -> Layout:
    """Create the dashboard layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_row(
        Layout(name="nodes", ratio=1),
        Layout(name="tasks", ratio=1),
    )
    return layout


def create_header() -> Panel:
    """Create the dashboard header."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return Panel(
        f"[bold blue]HakuRiver Cluster Dashboard[/bold blue] | {now}",
        style="white on blue",
    )


def create_footer() -> Panel:
    """Create the dashboard footer."""
    return Panel(
        "[dim]Press [bold]Ctrl+C[/bold] to exit[/dim]",
        style="dim",
    )


def create_nodes_panel(nodes: list[dict]) -> Panel:
    """Create the nodes panel."""
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Hostname")
    table.add_column("Status", justify="center")
    table.add_column("CPU%", justify="right")
    table.add_column("Memory", justify="right")
    table.add_column("GPUs", justify="right")

    for node in nodes:
        status = format_status(node.get("status", "unknown"))
        cpu_pct = node.get("cpu_percent", 0)
        cpu_str = f"{cpu_pct:.0f}%"

        memory_total = node.get("memory_total_bytes", 0)
        memory_used = node.get("memory_used_bytes", 0)
        if memory_total:
            mem_pct = (memory_used / memory_total) * 100
            mem_str = f"{mem_pct:.0f}%"
        else:
            mem_str = "-"

        gpu_info = node.get("gpu_info", [])
        gpu_str = str(len(gpu_info)) if gpu_info else "-"

        table.add_row(
            node.get("hostname", ""),
            status,
            cpu_str,
            mem_str,
            gpu_str,
        )

    return Panel(table, title="Nodes", border_style="green")


def create_tasks_panel(tasks: list[dict]) -> Panel:
    """Create the tasks panel."""
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Task ID")
    table.add_column("Status", justify="center")
    table.add_column("Node")
    table.add_column("Command", overflow="ellipsis", max_width=30)

    for task in tasks[:15]:  # Limit to 15 tasks
        status = format_status(task.get("status", "unknown"))

        node = task.get("assigned_node")
        if isinstance(node, dict):
            node = node.get("hostname", "-")
        node = node or "-"

        command = task.get("command", "")
        if len(command) > 30:
            command = command[:27] + "..."

        table.add_row(
            str(task.get("task_id", ""))[-12:],  # Last 12 chars
            status,
            node,
            command,
        )

    return Panel(table, title="Active Tasks", border_style="cyan")


def run_dashboard(refresh_rate: float = 2.0) -> None:
    """Run the live dashboard."""
    layout = create_dashboard_layout()

    with Live(layout, console=console, refresh_per_second=2, screen=True) as live:
        while True:
            try:
                # Update header
                layout["header"].update(create_header())

                # Update nodes
                nodes = client.get_nodes()
                layout["nodes"].update(create_nodes_panel(nodes))

                # Update tasks
                tasks = client.get_tasks(limit=20)
                # Filter for active tasks
                active_tasks = [
                    t
                    for t in tasks
                    if t.get("status") in ("pending", "assigning", "running", "paused")
                ]
                layout["tasks"].update(create_tasks_panel(active_tasks))

                # Update footer
                layout["footer"].update(create_footer())

                time.sleep(refresh_rate)

            except client.APIError:
                layout["main"].update(
                    Panel(
                        "[red]Error connecting to host[/red]",
                        title="Error",
                        border_style="red",
                    )
                )
                time.sleep(refresh_rate)
            except KeyboardInterrupt:
                break
