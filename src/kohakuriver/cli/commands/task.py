"""Task management commands."""

from typing import Annotated

import typer

from kohakuriver.cli import client
from kohakuriver.cli.formatters.task import (
    format_task_detail,
    format_task_list_compact,
    format_task_table,
)
from kohakuriver.cli.output import console, print_error, print_success

app = typer.Typer(help="Task management commands")


@app.command("list")
def list_tasks(
    status: Annotated[
        str | None, typer.Option("--status", "-s", help="Filter by status")
    ] = None,
    node: Annotated[
        str | None, typer.Option("--node", "-n", help="Filter by node")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 50,
    compact: Annotated[
        bool, typer.Option("--compact", "-c", help="Compact output")
    ] = False,
):
    """List tasks with optional filtering."""
    try:
        tasks = client.get_tasks(status=status, node=node, limit=limit)

        if not tasks:
            console.print("[yellow]No tasks found.[/yellow]")
            return

        if compact:
            table = format_task_list_compact(tasks)
        else:
            table = format_task_table(tasks)
        console.print(table)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("status")
def task_status(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
):
    """Get detailed status for a task."""
    try:
        task = client.get_task_status(task_id)

        if not task:
            print_error(f"Task {task_id} not found.")
            raise typer.Exit(1)

        panel = format_task_detail(task)
        console.print(panel)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("submit", context_settings={"allow_interspersed_args": False})
def submit_task(
    command: Annotated[
        list[str],
        typer.Argument(help="Command to execute (everything after options)"),
    ],
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Target node[:numa][::gpus]"),
    ] = None,
    cores: Annotated[int, typer.Option("--cores", "-c", help="CPU cores")] = 1,
    memory: Annotated[
        str | None, typer.Option("--memory", "-m", help="Memory limit (e.g., 4G)")
    ] = None,
    container: Annotated[
        str | None, typer.Option("--container", help="Container environment")
    ] = None,
    image: Annotated[
        str | None,
        typer.Option("--image", help="Docker registry image (e.g. ubuntu:22.04)"),
    ] = None,
    privileged: Annotated[
        bool, typer.Option("--privileged", help="Run with --privileged")
    ] = False,
    mount: Annotated[
        list[str] | None,
        typer.Option("--mount", help="Additional mounts (repeatable)"),
    ] = None,
    wait: Annotated[
        bool, typer.Option("--wait", "-w", help="Wait for completion")
    ] = False,
):
    """
    Submit a new task.

    The command is everything after the options. Use -- to separate options from command.

    Examples:
        kohakuriver task submit -t node1 -- echo "hello world"
        kohakuriver task submit -t node1 -c 4 -- python -c "print('hello')"
        kohakuriver task submit --container my-env -- python /shared/script.py --arg1 val1
    """
    import shlex

    from kohakuriver.utils.cli import parse_memory_string

    if not command:
        print_error("No command provided")
        raise typer.Exit(1)

    if image and container:
        print_error("--image and --container are mutually exclusive")
        raise typer.Exit(1)

    try:
        # Parse memory
        memory_bytes = None
        if memory:
            memory_bytes = parse_memory_string(memory)

        # Parse target for GPU IDs
        targets = None
        gpu_ids = None
        if target:
            targets = [target]
            # Parse GPU IDs from target (format: host[:numa]::gpu1,gpu2)
            if "::" in target:
                target_part, gpu_str = target.rsplit("::", 1)
                targets = [target_part]
                gpu_list = [int(g.strip()) for g in gpu_str.split(",") if g.strip()]
                gpu_ids = [gpu_list]  # One GPU list per target

        # Join command parts back into a single command string
        # The shell in the container will parse it
        full_command = " ".join(shlex.quote(part) for part in command)

        result = client.submit_task(
            command=full_command,
            args=[],  # Arguments are included in command string
            cores=cores,
            memory_bytes=memory_bytes,
            targets=targets,
            container_name=container,
            registry_image=image,
            privileged=privileged if privileged else None,
            additional_mounts=mount,
            gpu_ids=gpu_ids,
        )

        task_ids = result.get("task_ids", [])
        if task_ids:
            print_success(f"Task(s) submitted: {', '.join(map(str, task_ids))}")

            if wait and len(task_ids) == 1:
                from kohakuriver.cli.interactive.monitor import wait_for_task

                wait_for_task(str(task_ids[0]))
        else:
            print_error("No task IDs returned")
            raise typer.Exit(1)

    except ValueError as e:
        print_error(f"Invalid argument: {e}")
        raise typer.Exit(1)
    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("kill")
def kill_task(
    task_id: Annotated[str, typer.Argument(help="Task ID to kill")],
):
    """Kill a running task."""
    try:
        result = client.kill_task(task_id)
        message = result.get("message", "Kill request sent.")
        print_success(message)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("pause")
def pause_task(
    task_id: Annotated[str, typer.Argument(help="Task ID to pause")],
):
    """Pause a running task."""
    try:
        result = client.send_task_command(task_id, "pause")
        message = result.get("message", "Pause command sent.")
        print_success(message)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("resume")
def resume_task(
    task_id: Annotated[str, typer.Argument(help="Task ID to resume")],
):
    """Resume a paused task."""
    try:
        result = client.send_task_command(task_id, "resume")
        message = result.get("message", "Resume command sent.")
        print_success(message)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("logs")
def task_logs(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
    stderr: Annotated[
        bool, typer.Option("--stderr", "-e", help="Show stderr instead of stdout")
    ] = False,
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Follow log output")
    ] = False,
):
    """Show task stdout/stderr."""
    try:
        if stderr:
            content = client.get_task_stderr(task_id)
        else:
            content = client.get_task_stdout(task_id)

        if content:
            console.print(content)
        else:
            console.print("[dim]No output available.[/dim]")

        if follow:
            from kohakuriver.cli.interactive.monitor import follow_task_logs

            follow_task_logs(task_id, stderr=stderr)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("watch")
def watch_task(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
):
    """Live monitor a task's status."""
    try:
        from kohakuriver.cli.interactive.monitor import watch_task_status

        watch_task_status(task_id)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Monitoring stopped.[/dim]")
