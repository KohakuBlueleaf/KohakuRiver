"""Live monitoring utilities."""

import time

from rich.live import Live
from rich.panel import Panel

from kohakuriver.cli import client
from kohakuriver.cli.formatters.task import format_task_detail
from kohakuriver.cli.output import console, get_status_style


def watch_task_status(task_id: str, refresh_rate: float = 1.0) -> None:
    """Live monitor a task's status until completion."""
    terminal_states = {"completed", "failed", "killed", "killed_oom", "stopped"}

    with Live(console=console, refresh_per_second=2) as live:
        while True:
            task = client.get_task_status(task_id)

            if not task:
                live.update(
                    Panel(
                        f"[red]Task {task_id} not found.[/red]",
                        title="Error",
                        border_style="red",
                    )
                )
                break

            panel = format_task_detail(task)
            live.update(panel)

            status = task.get("status", "unknown")
            if status in terminal_states:
                break

            time.sleep(refresh_rate)


def wait_for_task(task_id: str, timeout: float | None = None) -> dict | None:
    """Wait for a task to complete, showing progress."""
    terminal_states = {"completed", "failed", "killed", "killed_oom", "stopped"}
    start_time = time.time()

    with console.status(f"[bold]Waiting for task {task_id}...[/bold]") as status:
        while True:
            task = client.get_task_status(task_id)

            if not task:
                console.print(f"[red]Task {task_id} not found.[/red]")
                return None

            task_status = task.get("status", "unknown")
            color = get_status_style(task_status)
            status.update(
                f"[bold]Task {task_id}:[/bold] [{color}]{task_status}[/{color}]"
            )

            if task_status in terminal_states:
                console.print(
                    f"\n[bold]Task {task_id}:[/bold] [{color}]{task_status}[/{color}]"
                )
                if task.get("exit_code") is not None:
                    exit_code = task["exit_code"]
                    exit_color = "green" if exit_code == 0 else "red"
                    console.print(
                        f"[bold]Exit code:[/bold] [{exit_color}]{exit_code}[/{exit_color}]"
                    )
                return task

            if timeout and (time.time() - start_time) > timeout:
                console.print(f"\n[yellow]Timeout waiting for task {task_id}.[/yellow]")
                return task

            time.sleep(1)


def follow_task_logs(
    task_id: str, stderr: bool = False, refresh_rate: float = 1.0
) -> None:
    """Follow task logs in real-time."""
    last_length = 0

    with Live(console=console, auto_refresh=False):
        while True:
            task = client.get_task_status(task_id)

            if not task:
                console.print(f"[red]Task {task_id} not found.[/red]")
                break

            try:
                if stderr:
                    content = client.get_task_stderr(task_id)
                else:
                    content = client.get_task_stdout(task_id)

                if len(content) > last_length:
                    new_content = content[last_length:]
                    console.print(new_content, end="")
                    last_length = len(content)

            except client.APIError:
                pass

            status = task.get("status", "unknown")
            if status in {"completed", "failed", "killed", "killed_oom", "stopped"}:
                break

            time.sleep(refresh_rate)
