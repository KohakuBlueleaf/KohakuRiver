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
        max_runners = stats.get("max_runners", 63)
        stats_text = (
            f"Subnet Config: [cyan]{status.get('subnet_config', 'N/A')}[/cyan]\n"
            f"Host IP: [cyan]{status.get('host_ip')}[/cyan]\n"
            f"Total Allocations: [green]{stats.get('total_allocations', 0)}[/green]\n"
            f"Active: [green]{stats.get('active_allocations', 0)}[/green] | "
            f"Inactive: [yellow]{stats.get('inactive_allocations', 0)}[/yellow]\n"
            f"Available IDs: [cyan]{stats.get('available_ids', 0)}[/cyan]/{max_runners}"
        )
        console.print(
            Panel(stats_text, title="Overlay Network Status", border_style="blue")
        )

        # Allocations table
        allocations = status.get("allocations", [])
        if allocations:
            table = Table(title="Runner Allocations")
            table.add_column("Runner", style="cyan")
            table.add_column("ID", justify="right")
            table.add_column("Subnet")
            table.add_column("Gateway")
            table.add_column("Physical IP")
            table.add_column("Status")

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
                    alloc.get("gateway", ""),
                    alloc.get("physical_ip", ""),
                    status_str,
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


# =============================================================================
# IP Reservation Commands
# =============================================================================


@app.command("ip-reserve")
def ip_reserve(
    runner: Annotated[str, typer.Argument(help="Runner hostname to reserve IP on")],
    ip: Annotated[
        str | None,
        typer.Option("--ip", "-i", help="Specific IP to reserve (optional)"),
    ] = None,
    ttl: Annotated[
        int,
        typer.Option("--ttl", "-t", help="Reservation time-to-live in seconds"),
    ] = 300,
):
    """
    Reserve an IP address on a runner for use in task submission.

    Use this for distributed training where you need to know the master IP
    before launching workers. The returned token is used with --ip-token
    when submitting tasks.
    """
    try:
        result = client.reserve_ip(runner, ip=ip, ttl=ttl)

        console.print(f"[green]IP reserved successfully![/green]")
        console.print(f"  IP: [cyan]{result.get('ip')}[/cyan]")
        console.print(f"  Runner: [cyan]{result.get('runner')}[/cyan]")
        console.print(f"  Token: [yellow]{result.get('token')}[/yellow]")
        console.print(f"  Expires: {result.get('expires_at')}")
        console.print()
        console.print(
            "[dim]Use the token with: kohakuriver task submit --ip-token TOKEN ...[/dim]"
        )

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("ip-release")
def ip_release(
    token: Annotated[str, typer.Argument(help="Reservation token to release")],
):
    """Release an IP reservation by token."""
    try:
        result = client.release_ip_reservation(token)

        if result.get("released"):
            console.print("[green]IP reservation released.[/green]")
        else:
            console.print("[yellow]Failed to release reservation.[/yellow]")

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("ip-list")
def ip_list(
    runner: Annotated[
        str | None,
        typer.Option("--runner", "-r", help="Filter by runner"),
    ] = None,
):
    """List active IP reservations."""
    try:
        from rich.table import Table

        result = client.list_ip_reservations(runner)
        reservations = result.get("reservations", [])

        if not reservations:
            console.print("[dim]No active IP reservations.[/dim]")
            return

        table = Table(title="IP Reservations")
        table.add_column("IP", style="cyan")
        table.add_column("Runner")
        table.add_column("Token (truncated)")
        table.add_column("Expires")
        table.add_column("Status")

        for r in reservations:
            status = (
                f"[green]In use ({r.get('container_id', '')[:12]})[/green]"
                if r.get("is_used")
                else "[yellow]Pending[/yellow]"
            )
            table.add_row(
                r.get("ip", ""),
                r.get("runner", ""),
                r.get("token", "")[:20] + "...",
                r.get("expires_at", "")[:19],
                status,
            )

        console.print(table)

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("ip-info")
def ip_info(
    runner: Annotated[str, typer.Argument(help="Runner hostname")],
):
    """Show IP allocation info for a runner."""
    try:
        from rich.panel import Panel

        info = client.get_runner_ip_info(runner)

        info_text = (
            f"Runner: [cyan]{info.get('runner_name')}[/cyan] (ID: {info.get('runner_id')})\n"
            f"Subnet: [cyan]{info.get('subnet')}[/cyan]\n"
            f"Gateway: [cyan]{info.get('gateway')}[/cyan]\n"
            f"IP Range: {info.get('ip_range', {}).get('first')} - {info.get('ip_range', {}).get('last')}\n"
            f"\nTotal IPs: [green]{info.get('total_ips')}[/green]\n"
            f"Available: [green]{info.get('available')}[/green]\n"
            f"Reserved: [yellow]{info.get('reserved')}[/yellow]\n"
            f"Used: [red]{info.get('used')}[/red]"
        )

        console.print(Panel(info_text, title=f"IP Info: {runner}", border_style="blue"))

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("ip-available")
def ip_available(
    runner: Annotated[
        str | None,
        typer.Option("--runner", "-r", help="Filter by runner"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max IPs to show per runner"),
    ] = 20,
):
    """Show available IPs for reservation."""
    try:
        result = client.get_available_ips(runner, limit=limit)
        available = result.get("available_ips", {})

        if not available:
            console.print("[dim]No available IPs (check overlay status).[/dim]")
            return

        for runner_name, ips in available.items():
            console.print(f"\n[cyan]{runner_name}[/cyan] ({len(ips)} IPs):")
            if ips:
                # Show first few and last few
                if len(ips) <= 10:
                    console.print(f"  {', '.join(ips)}")
                else:
                    first_5 = ", ".join(ips[:5])
                    last_3 = ", ".join(ips[-3:])
                    console.print(f"  {first_5}, ..., {last_3}")

    except client.APIError as e:
        print_error(str(e))
        raise typer.Exit(1)
