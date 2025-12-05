"""Node management commands."""

from typing import Annotated

import typer

from kohakuriver.cli import client
from kohakuriver.cli.formatters.node import (
    format_cluster_summary,
    format_node_detail,
    format_node_table,
)
from kohakuriver.cli.output import console, print_error

app = typer.Typer(help="Node management commands")


@app.command("list")
def list_nodes(
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (online/offline)"),
    ] = None,
):
    """List all registered nodes."""
    try:
        nodes = client.get_nodes()

        if status:
            nodes = [n for n in nodes if n.get("status") == status]

        if not nodes:
            console.print("[yellow]No nodes found.[/yellow]")
            return

        table = format_node_table(nodes)
        console.print(table)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("status")
def node_status(
    hostname: Annotated[str, typer.Argument(help="Node hostname")],
):
    """Get detailed status for a node."""
    try:
        nodes = client.get_nodes()
        node = next((n for n in nodes if n.get("hostname") == hostname), None)

        if not node:
            print_error(f"Node {hostname} not found.")
            raise typer.Exit(1)

        panel = format_node_detail(node)
        console.print(panel)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("health")
def node_health(
    hostname: Annotated[
        str | None, typer.Argument(help="Node hostname (optional)")
    ] = None,
):
    """Show node health metrics."""
    try:
        if hostname:
            health = client.get_node_health(hostname)
            if isinstance(health, dict):
                panel = format_node_detail(health)
                console.print(panel)
            else:
                console.print("[yellow]No health data available.[/yellow]")
        else:
            nodes = client.get_nodes()
            if not nodes:
                console.print("[yellow]No nodes found.[/yellow]")
                return

            # Show cluster summary
            summary = format_cluster_summary(nodes)
            console.print(summary)
            console.print()

            # Show node table
            table = format_node_table(nodes)
            console.print(table)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("watch")
def watch_nodes():
    """Live monitor cluster status (TUI dashboard)."""
    try:
        from kohakuriver.cli.interactive.dashboard import run_dashboard

        run_dashboard()

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard closed.[/dim]")


@app.command("summary")
def cluster_summary():
    """Show cluster summary."""
    try:
        nodes = client.get_nodes()

        if not nodes:
            console.print("[yellow]No nodes found.[/yellow]")
            return

        panel = format_cluster_summary(nodes)
        console.print(panel)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


# =============================================================================
# Overlay Network Commands
# =============================================================================


@app.command("overlay")
def overlay_status():
    """Show overlay network status and allocations."""
    try:
        status = client.get_overlay_status()

        if not status.get("enabled"):
            console.print("[yellow]Overlay network is not enabled.[/yellow]")
            return

        if status.get("error"):
            print_error(f"Overlay error: {status['error']}")
            raise typer.Exit(1)

        # Show overlay status
        from rich.table import Table
        from rich.panel import Panel

        # Stats panel
        stats = status.get("stats", {})
        stats_text = (
            f"Host IP: [cyan]{status.get('host_ip')}[/cyan]\n"
            f"Bridge: [cyan]{status.get('bridge')}[/cyan]\n"
            f"Total Allocations: [green]{stats.get('total_allocations', 0)}[/green]\n"
            f"Active: [green]{stats.get('active_allocations', 0)}[/green] | "
            f"Inactive: [yellow]{stats.get('inactive_allocations', 0)}[/yellow]\n"
            f"Available IDs: [cyan]{stats.get('available_ids', 0)}[/cyan]/255"
        )
        console.print(Panel(stats_text, title="Overlay Network Status", border_style="blue"))

        # Allocations table
        allocations = status.get("allocations", [])
        if allocations:
            table = Table(title="Runner Allocations")
            table.add_column("Runner", style="cyan")
            table.add_column("ID", justify="right")
            table.add_column("Subnet")
            table.add_column("Physical IP")
            table.add_column("Status")
            table.add_column("Last Used")

            for alloc in allocations:
                status_str = (
                    "[green]Active[/green]"
                    if alloc.get("is_active")
                    else "[yellow]Inactive[/yellow]"
                )
                table.add_row(
                    alloc.get("runner_name", ""),
                    str(alloc.get("runner_id", "")),
                    alloc.get("subnet", ""),
                    alloc.get("physical_ip", ""),
                    status_str,
                    alloc.get("last_used", "")[:19],  # Truncate timestamp
                )

            console.print(table)
        else:
            console.print("[dim]No overlay allocations.[/dim]")

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("overlay-release")
def overlay_release(
    runner: Annotated[str, typer.Argument(help="Runner hostname to release")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
):
    """Release overlay allocation for a runner."""
    try:
        if not force:
            console.print(
                f"[yellow]Warning:[/yellow] This will disconnect runner "
                f"'{runner}' from the overlay network."
            )
            console.print("Running containers may lose cross-node connectivity.")
            confirm = typer.confirm("Are you sure?")
            if not confirm:
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)

        result = client.release_overlay(runner)

        if result.get("released"):
            console.print(f"[green]Released overlay allocation for {runner}.[/green]")
        else:
            console.print(
                f"[yellow]Could not release:[/yellow] {result.get('reason', 'Unknown')}"
            )

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("overlay-cleanup")
def overlay_cleanup(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
):
    """Cleanup inactive overlay allocations."""
    try:
        if not force:
            console.print(
                "[yellow]Warning:[/yellow] This will remove VXLAN tunnels for "
                "all inactive runners."
            )
            console.print(
                "Only do this when you're sure no containers need cross-node connectivity."
            )
            confirm = typer.confirm("Are you sure?")
            if not confirm:
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)

        result = client.cleanup_overlay()
        count = result.get("cleaned_count", 0)

        if count > 0:
            console.print(f"[green]Cleaned up {count} inactive allocation(s).[/green]")
        else:
            console.print("[dim]No inactive allocations to clean up.[/dim]")

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
