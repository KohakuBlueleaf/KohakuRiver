"""Rendering functions for the Rich-based TUI dashboard."""

import json
from datetime import datetime
from enum import Enum

from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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


def render_header(current_view: View, previous_view: View) -> Panel:
    """Render the header bar."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    detail_views = (
        View.TASK_DETAIL,
        View.VPS_DETAIL,
        View.NODE_DETAIL,
        View.DOCKER_DETAIL,
    )

    # View tabs
    tabs = []
    for view in [View.DASHBOARD, View.NODES, View.TASKS, View.VPS, View.DOCKER]:
        if view == current_view or (
            current_view in detail_views and view == previous_view
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


def render_footer(
    current_view: View,
    error_message: str | None,
    status_message: str | None,
) -> Panel:
    """Render the footer with keybindings."""
    if error_message:
        return Panel(
            Text(f"Error: {error_message}", style="red"),
            style="red",
        )

    if status_message:
        return Panel(
            Text(status_message, style="green"),
            style="green",
        )

    detail_views = (
        View.TASK_DETAIL,
        View.VPS_DETAIL,
        View.NODE_DETAIL,
        View.DOCKER_DETAIL,
    )

    # Build key hints based on current view
    keys = Text()

    if current_view in detail_views:
        keys.append("Esc", style="bold")
        keys.append("-Back  ", style="dim")
        if current_view == View.TASK_DETAIL:
            keys.append("k", style="bold")
            keys.append("-Kill  ", style="dim")
        elif current_view == View.VPS_DETAIL:
            keys.append("k", style="bold")
            keys.append("-Stop  ", style="dim")
        elif current_view == View.DOCKER_DETAIL:
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

        if current_view in (View.NODES, View.TASKS, View.VPS, View.DOCKER):
            keys.append("↑↓/WS", style="bold")
            keys.append("-Nav  ", style="dim")
            keys.append("AD", style="bold")
            keys.append("-Views  ", style="dim")
            keys.append("Enter", style="bold")
            keys.append("-Details  ", style="dim")

        if current_view == View.TASKS:
            keys.append("f", style="bold")
            keys.append("-Filter  ", style="dim")
            keys.append("n", style="bold")
            keys.append("-New  ", style="dim")
        elif current_view == View.VPS:
            keys.append("n", style="bold")
            keys.append("-New  ", style="dim")
        elif current_view == View.DOCKER:
            keys.append("n", style="bold")
            keys.append("-New  ", style="dim")

        keys.append("r", style="bold")
        keys.append("-Refresh  ", style="dim")

    keys.append("q", style="bold")
    keys.append("-Quit", style="dim")

    return Panel(keys, style="dim")


def render_dashboard(
    nodes: list[dict],
    tasks: list[dict],
    vps_list: list[dict],
) -> Panel:
    """Render the dashboard view."""
    # Cluster summary
    online = sum(1 for n in nodes if n.get("status") == "online")
    offline = len(nodes) - online

    total_cores = sum(n.get("total_cores", 0) for n in nodes)

    running_tasks = sum(1 for t in tasks if t.get("status") == "running")
    pending_tasks = sum(1 for t in tasks if t.get("status") in ("pending", "assigning"))

    active_vps = sum(1 for v in vps_list if v.get("status") == "running")

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

    for task in tasks[:10]:
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

    for node in nodes[:8]:
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


def render_nodes(nodes: list[dict], selected_index: int) -> Panel:
    """Render the nodes view."""
    table = Table(show_header=True, expand=True)
    table.add_column("Hostname", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Cores", justify="right")
    table.add_column("CPU%", justify="right")
    table.add_column("Memory", justify="right")
    table.add_column("GPUs", justify="right")
    table.add_column("URL")

    for i, node in enumerate(nodes):
        is_selected = i == selected_index
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
    info.append(f"Total: {len(nodes)} nodes", style="dim")

    return Panel(Group(info, table), title="Nodes", border_style="cyan")


def render_tasks(
    tasks: list[dict],
    task_filter: str,
    selected_index: int,
) -> Panel:
    """Render the tasks view."""
    # Filter tasks
    if task_filter == "all":
        filtered = tasks
    else:
        filtered = [t for t in tasks if t.get("status") == task_filter]

    # Filter indicator
    filter_text = Text()
    filter_text.append("Filter: ", style="dim")
    filter_text.append(task_filter, style="bold yellow")
    filter_text.append(f"  |  Total: {len(filtered)} tasks", style="dim")

    table = Table(show_header=True, expand=True)
    table.add_column("Task ID", style="cyan", width=20)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Node", width=15)
    table.add_column("Cores", justify="right", width=6)
    table.add_column("GPUs", justify="right", width=8)
    table.add_column("Command", overflow="ellipsis")

    for i, task in enumerate(filtered[:30]):
        is_selected = i == selected_index
        row_style = "reverse" if is_selected else None

        node = task.get("assigned_node")
        if isinstance(node, dict):
            node = node.get("hostname", "-")

        gpus = task.get("required_gpus", [])
        if isinstance(gpus, str):
            try:
                gpus = json.loads(gpus)
            except (ValueError, KeyError, TypeError):
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


def render_vps(vps_list: list[dict], selected_index: int) -> Panel:
    """Render the VPS view."""
    table = Table(show_header=True, expand=True)
    table.add_column("Task ID", style="cyan", width=20)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Node", width=15)
    table.add_column("SSH Port", justify="right", width=10)
    table.add_column("Cores", justify="right", width=6)
    table.add_column("Started", width=20)

    for i, vps in enumerate(vps_list[:20]):
        is_selected = i == selected_index
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
    info.append(f"Total: {len(vps_list)} VPS instances", style="dim")

    return Panel(Group(info, table), title="VPS Instances", border_style="magenta")


def render_docker(
    containers: list[dict],
    tarballs: dict,
    selected_index: int,
) -> Panel:
    """Render the Docker containers view."""
    table = Table(show_header=True, expand=True)
    table.add_column("Environment", style="cyan", width=20)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Image", width=30)
    table.add_column("Tarball", justify="center", width=10)

    for i, container in enumerate(containers[:20]):
        is_selected = i == selected_index
        row_style = "reverse" if is_selected else None

        env_name = container.get("env_name", container.get("name", ""))
        status = container.get("status", "unknown")
        image = container.get("image", "-")

        # Check if tarball exists
        has_tarball = env_name in tarballs
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
    info.append(f"Total: {len(containers)} environment containers", style="dim")
    info.append(f"  |  Tarballs: {len(tarballs)}", style="dim")

    return Panel(
        Group(info, table), title="Docker Environments (Host)", border_style="blue"
    )


def render_docker_detail(detail_item: dict | None, tarballs: dict) -> Panel:
    """Render Docker container detail view."""
    if not detail_item:
        return Panel(
            "No container selected", title="Container Detail", border_style="blue"
        )

    container = detail_item

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
        "green" if status == "running" else "yellow" if status == "exited" else "dim"
    )
    info.add_row("Status", Text(status, style=status_style))

    info.add_row("Image", container.get("image", "-"))
    info.add_row("Created", str(container.get("created", "-"))[:19])

    # Tarball info
    if env_name in tarballs:
        tarball_info = tarballs[env_name]
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


def render_task_detail(
    detail_item: dict | None, stdout_content: str, stderr_content: str
) -> Panel:
    """Render task detail view."""
    if not detail_item:
        return Panel("No task selected", title="Task Detail", border_style="yellow")

    task = detail_item

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
        except (ValueError, KeyError, TypeError):
            gpus = []
    info.add_row("GPUs", ",".join(map(str, gpus)) if gpus else "-")

    info.add_row("Created", str(task.get("created_at", "-"))[:19])
    info.add_row(
        "Started",
        str(task.get("started_at", "-"))[:19] if task.get("started_at") else "-",
    )
    info.add_row(
        "Completed",
        (str(task.get("completed_at", "-"))[:19] if task.get("completed_at") else "-"),
    )

    if task.get("exit_code") is not None:
        exit_code = task.get("exit_code")
        exit_style = "green" if exit_code == 0 else "red"
        info.add_row("Exit Code", Text(str(exit_code), style=exit_style))

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


def render_vps_detail(detail_item: dict | None) -> Panel:
    """Render VPS detail view."""
    if not detail_item:
        return Panel("No VPS selected", title="VPS Detail", border_style="magenta")

    vps = detail_item

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


def render_node_detail(detail_item: dict | None) -> Panel:
    """Render node detail view."""
    if not detail_item:
        return Panel("No node selected", title="Node Detail", border_style="cyan")

    node = detail_item

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
