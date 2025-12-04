"""
KohakuRiver unified CLI entry point.

Usage:
    kohakuriver [OPTIONS] COMMAND [ARGS]...

Commands:
    task      Task management
    vps       VPS management
    node      Node management
    docker    Docker/container management
    ssh       SSH commands
    terminal  Terminal access
    config    Configuration
"""

from typing import Annotated

import typer

from kohakuriver.cli import config as cli_config
from kohakuriver.cli.commands import (
    config_cmd,
    connect,
    docker,
    forward,
    init,
    node,
    ssh,
    task,
    terminal,
    vps,
)
from kohakuriver.cli.output import console

app = typer.Typer(
    name="kohakuriver",
    help="KohakuRiver Cluster Management CLI",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register command groups
app.add_typer(task.app, name="task", help="Task management")
app.add_typer(vps.app, name="vps", help="VPS management")
app.add_typer(node.app, name="node", help="Node management")
app.add_typer(docker.app, name="docker", help="Docker/container management")
app.add_typer(ssh.app, name="ssh", help="SSH commands")
app.add_typer(terminal.app, name="terminal", help="Terminal access (TUI)")
app.add_typer(connect.app, name="connect", help="Connect to container terminal")
app.add_typer(forward.app, name="forward", help="Forward local ports to containers")
app.add_typer(config_cmd.app, name="config", help="Configuration")
app.add_typer(init.app, name="init", help="Initialize config and services")


@app.callback()
def main(
    host: Annotated[
        str | None,
        typer.Option("--host", "-H", help="Host address", envvar="KOHAKURIVER_HOST"),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", "-P", help="Host port", envvar="KOHAKURIVER_PORT"),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: table|json|yaml"),
    ] = "table",
):
    """
    KohakuRiver Cluster Management CLI.

    Manage tasks, VPS instances, nodes, and Docker containers.
    """
    if host:
        cli_config.HOST_ADDRESS = host
    if port:
        cli_config.HOST_PORT = port
    cli_config.OUTPUT_FORMAT = output_format


@app.command("version")
def version():
    """Show version information."""
    try:
        from kohakuriver import __version__

        console.print(f"HakuRiver CLI v{__version__}")
    except ImportError:
        console.print("HakuRiver CLI (version unknown)")


@app.command("status")
def quick_status():
    """Show quick cluster status overview."""
    from kohakuriver.cli import client
    from kohakuriver.cli.formatters.node import format_cluster_summary
    from kohakuriver.cli.formatters.task import format_task_list_compact
    from kohakuriver.cli.output import print_error

    try:
        # Get nodes
        nodes = client.get_nodes()

        if nodes:
            summary = format_cluster_summary(nodes)
            console.print(summary)
            console.print()

        # Get running tasks
        tasks = client.get_tasks(status="running", limit=10)
        if tasks:
            console.print("[bold]Running Tasks:[/bold]")
            table = format_task_list_compact(tasks)
            console.print(table)
        else:
            console.print("[dim]No running tasks.[/dim]")

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


def run():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    run()
