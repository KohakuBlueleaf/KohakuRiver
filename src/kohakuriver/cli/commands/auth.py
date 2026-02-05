"""
Authentication CLI commands for KohakuRiver.

Commands for:
- Login (username/password or token)
- Logout
- Status check
- API token management
"""

import json
import os
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.table import Table

from kohakuriver.cli import config as cli_config
from kohakuriver.cli.output import console, print_error, print_success

app = typer.Typer(name="auth", help="Authentication commands")


# =============================================================================
# Token Storage
# =============================================================================


def _get_auth_file() -> Path:
    """Get path to auth credentials file."""
    return Path.home() / ".kohakuriver" / "auth.json"


def _load_auth() -> dict:
    """Load auth credentials from file."""
    auth_file = _get_auth_file()
    if not auth_file.exists():
        return {}
    try:
        with open(auth_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_auth(data: dict) -> None:
    """Save auth credentials to file with secure permissions."""
    auth_file = _get_auth_file()
    auth_file.parent.mkdir(parents=True, exist_ok=True)

    with open(auth_file, "w") as f:
        json.dump(data, f, indent=2)

    # Set file permissions to 0600 (owner read/write only)
    os.chmod(auth_file, 0o600)


def _clear_auth() -> None:
    """Clear stored auth credentials."""
    auth_file = _get_auth_file()
    if auth_file.exists():
        auth_file.unlink()


def get_stored_token() -> str | None:
    """Get stored API token for use in requests."""
    auth = _load_auth()
    return auth.get("token")


def _get_host_url() -> str:
    """Get the host API URL."""
    return f"http://{cli_config.HOST_ADDRESS}:{cli_config.HOST_PORT}/api"


# =============================================================================
# Login Command
# =============================================================================


@app.command("login")
def login(
    username: Annotated[
        str | None,
        typer.Option("--username", "-u", help="Username for login"),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option("--password", "-p", help="Password for login", hide_input=True),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option("--token", "-t", help="API token for direct authentication"),
    ] = None,
    token_name: Annotated[
        str,
        typer.Option("--token-name", help="Name for auto-created API token"),
    ] = "cli-auto",
):
    """
    Login to KohakuRiver host.

    Use username/password to login and auto-create an API token,
    or provide an existing API token directly with --token.
    """
    url = _get_host_url()

    if token:
        # Direct token authentication - verify it works
        try:
            response = httpx.get(
                f"{url}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            response.raise_for_status()
            user_info = response.json()

            # Save token
            _save_auth(
                {
                    "token": token,
                    "username": user_info["username"],
                    "role": user_info["role"],
                }
            )

            print_success(
                f"Logged in as {user_info['username']} (role: {user_info['role']})"
            )
            return

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                print_error("Invalid token")
            else:
                print_error(f"Login failed: {e.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as e:
            print_error(f"Network error: {e}")
            raise typer.Exit(1)

    # Username/password login
    if not username:
        username = typer.prompt("Username")
    if not password:
        password = typer.prompt("Password", hide_input=True)

    try:
        # Login to get session
        response = httpx.post(
            f"{url}/auth/login",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        response.raise_for_status()
        login_data = response.json()

        # Extract session cookie
        session_cookie = response.cookies.get("kohakuriver_session")
        if not session_cookie:
            print_error("Login succeeded but no session cookie received")
            raise typer.Exit(1)

        # Create an API token for CLI use
        token_response = httpx.post(
            f"{url}/auth/tokens/create",
            json={"name": token_name},
            cookies={"kohakuriver_session": session_cookie},
            timeout=10.0,
        )
        token_response.raise_for_status()
        token_data = token_response.json()

        # Save the API token
        _save_auth(
            {
                "token": token_data["token"],
                "token_id": token_data["id"],
                "token_name": token_data["name"],
                "username": login_data["user"]["username"],
                "role": login_data["user"]["role"],
            }
        )

        print_success(
            f"Logged in as {login_data['user']['username']} "
            f"(role: {login_data['user']['role']})"
        )
        console.print(f"[dim]API token '{token_name}' created and stored[/dim]")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            print_error("Invalid username or password")
        elif e.response.status_code == 503:
            print_error("Authentication is not enabled on this server")
        else:
            detail = e.response.json().get("detail", e.response.text)
            print_error(f"Login failed: {detail}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        print_error(f"Network error: {e}")
        raise typer.Exit(1)


# =============================================================================
# Logout Command
# =============================================================================


@app.command("logout")
def logout(
    revoke: Annotated[
        bool,
        typer.Option("--revoke", "-r", help="Also revoke the stored API token"),
    ] = False,
):
    """
    Logout and clear stored credentials.

    Use --revoke to also revoke the stored API token on the server.
    """
    auth = _load_auth()

    if not auth:
        console.print("[dim]Not logged in[/dim]")
        return

    if revoke and auth.get("token") and auth.get("token_id"):
        # Revoke the token on the server
        try:
            url = _get_host_url()
            response = httpx.delete(
                f"{url}/auth/tokens/{auth['token_id']}",
                headers={"Authorization": f"Bearer {auth['token']}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                console.print("[dim]API token revoked on server[/dim]")
        except Exception:
            pass  # Ignore errors - still clear local credentials

    _clear_auth()
    print_success("Logged out")


# =============================================================================
# Status Command
# =============================================================================


@app.command("status")
def status():
    """Show current authentication status."""
    auth = _load_auth()

    if not auth or not auth.get("token"):
        console.print("[yellow]Not logged in[/yellow]")
        console.print(f"[dim]Use 'kohakuriver auth login' to authenticate[/dim]")
        return

    # Verify token is still valid
    try:
        url = _get_host_url()
        response = httpx.get(
            f"{url}/auth/me",
            headers={"Authorization": f"Bearer {auth['token']}"},
            timeout=10.0,
        )
        response.raise_for_status()
        user_info = response.json()

        console.print(f"[green]Logged in[/green]")
        console.print(f"  Username: {user_info['username']}")
        console.print(f"  Role: {user_info['role']}")
        if auth.get("token_name"):
            console.print(f"  Token: {auth['token_name']}")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            console.print("[red]Token expired or invalid[/red]")
            console.print(
                f"[dim]Stored credentials for: {auth.get('username', 'unknown')}[/dim]"
            )
            console.print(f"[dim]Use 'kohakuriver auth login' to re-authenticate[/dim]")
        elif e.response.status_code == 503:
            console.print("[yellow]Authentication not enabled on server[/yellow]")
        else:
            print_error(f"Error checking status: {e.response.text}")
    except httpx.RequestError as e:
        print_error(f"Network error: {e}")
        console.print(
            f"[dim]Stored credentials for: {auth.get('username', 'unknown')}[/dim]"
        )


# =============================================================================
# Token Management Commands
# =============================================================================


@app.command("token")
def token_cmd():
    """API token management (use subcommands: list, create, revoke)."""
    console.print("Use: kohakuriver auth token [list|create|revoke]")


token_app = typer.Typer(name="token", help="API token management")
app.add_typer(token_app)


@token_app.command("list")
def token_list():
    """List your API tokens."""
    auth = _load_auth()
    if not auth.get("token"):
        print_error("Not logged in. Use 'kohakuriver auth login' first.")
        raise typer.Exit(1)

    try:
        url = _get_host_url()
        response = httpx.get(
            f"{url}/auth/tokens",
            headers={"Authorization": f"Bearer {auth['token']}"},
            timeout=10.0,
        )
        response.raise_for_status()
        tokens = response.json()

        if not tokens:
            console.print("[dim]No API tokens[/dim]")
            return

        table = Table(title="API Tokens")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Last Used")
        table.add_column("Created")

        for t in tokens:
            table.add_row(
                str(t["id"]),
                t["name"],
                t["last_used"] or "-",
                t["created_at"],
            )

        console.print(table)

    except httpx.HTTPStatusError as e:
        print_error(f"Error: {e.response.text}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        print_error(f"Network error: {e}")
        raise typer.Exit(1)


@token_app.command("create")
def token_create(
    name: Annotated[str, typer.Argument(help="Name for the new token")],
):
    """Create a new API token."""
    auth = _load_auth()
    if not auth.get("token"):
        print_error("Not logged in. Use 'kohakuriver auth login' first.")
        raise typer.Exit(1)

    try:
        url = _get_host_url()
        response = httpx.post(
            f"{url}/auth/tokens/create",
            json={"name": name},
            headers={"Authorization": f"Bearer {auth['token']}"},
            timeout=10.0,
        )
        response.raise_for_status()
        token_data = response.json()

        print_success(f"Token '{name}' created")
        console.print()
        console.print(
            "[bold yellow]Save this token - it will not be shown again:[/bold yellow]"
        )
        console.print(f"[bold]{token_data['token']}[/bold]")

    except httpx.HTTPStatusError as e:
        print_error(f"Error: {e.response.text}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        print_error(f"Network error: {e}")
        raise typer.Exit(1)


@token_app.command("revoke")
def token_revoke(
    token_id: Annotated[int, typer.Argument(help="Token ID to revoke")],
):
    """Revoke an API token."""
    auth = _load_auth()
    if not auth.get("token"):
        print_error("Not logged in. Use 'kohakuriver auth login' first.")
        raise typer.Exit(1)

    try:
        url = _get_host_url()
        response = httpx.delete(
            f"{url}/auth/tokens/{token_id}",
            headers={"Authorization": f"Bearer {auth['token']}"},
            timeout=10.0,
        )
        response.raise_for_status()

        print_success(f"Token {token_id} revoked")

        # If we revoked our own token, clear local auth
        if auth.get("token_id") == token_id:
            _clear_auth()
            console.print(
                "[dim]Local credentials cleared (revoked current token)[/dim]"
            )

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print_error("Token not found")
        else:
            print_error(f"Error: {e.response.text}")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        print_error(f"Network error: {e}")
        raise typer.Exit(1)
