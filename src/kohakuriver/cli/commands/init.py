"""
KohakuRiver Init CLI: Initialize configuration and services.

Usage:
    kohakuriver init config              # Show instructions
    kohakuriver init config --generate   # Generate example config files
    kohakuriver init service --all       # Generate systemd service files
"""

import os
import shutil
import subprocess
import sys
import tempfile
from typing import Annotated

import typer

from kohakuriver.cli.output import console, print_error, print_success, print_warning

app = typer.Typer(help="Initialize configuration and services")


def get_default_config_dir() -> str:
    """Get the default config directory path."""
    return os.path.expanduser("~/.kohakuriver")


# Template for host configuration - uses module globals + from_globals()
HOST_CONFIG_TEMPLATE = '''"""
KohakuRiver Host Configuration

This file is loaded by KohakuEngine when running:
    kohakuriver.host --config /path/to/this/file.py

Or automatically if located at:
    ~/.kohakuriver/host_config.py

Modify the module-level variables below to customize your host setup.
"""
from kohakuengine import Config

from kohakuriver.models.enums import LogLevel

# =============================================================================
# Network Configuration
# =============================================================================

# IP address the Host server binds to
HOST_BIND_IP: str = "0.0.0.0"

# Port the Host API server listens on
HOST_PORT: int = 8000

# Port for SSH proxy (VPS access)
HOST_SSH_PROXY_PORT: int = 8002

# Address that runners/clients use to reach the host
# IMPORTANT: Change this in production to the actual reachable IP/hostname!
HOST_REACHABLE_ADDRESS: str = "127.0.0.1"

# =============================================================================
# Path Configuration
# =============================================================================

# Shared storage accessible by all nodes at the same path (NFS mount)
SHARED_DIR: str = "/mnt/cluster-share"

# SQLite database file path
DB_FILE: str = "/var/lib/kohakuriver/kohakuriver.db"

# Container tarball directory (empty = SHARED_DIR/kohakuriver-containers)
CONTAINER_DIR: str = ""

# Log file path (empty = console only)
HOST_LOG_FILE: str = ""

# =============================================================================
# Timing Configuration
# =============================================================================

# How often runners send heartbeats (seconds)
HEARTBEAT_INTERVAL_SECONDS: int = 5

# Runner is marked offline if no heartbeat for interval * this factor
HEARTBEAT_TIMEOUT_FACTOR: int = 6

# How often to check for dead runners (seconds)
CLEANUP_CHECK_INTERVAL_SECONDS: int = 10

# =============================================================================
# Docker Configuration
# =============================================================================

# Default container name for KohakuRiver tasks
DEFAULT_CONTAINER_NAME: str = "kohakuriver-base"

# Initial Docker image if default container tarball doesn't exist
INITIAL_BASE_IMAGE: str = "python:3.12-alpine"

# Whether tasks run with --privileged flag (use with caution!)
TASKS_PRIVILEGED: bool = False

# Additional host directories to mount into containers
# Format: ["host_path:container_path", ...]
ADDITIONAL_MOUNTS: list[str] = []

# Default working directory inside containers
DEFAULT_WORKING_DIR: str = "/shared"

# =============================================================================
# Logging Configuration
# =============================================================================

# Logging verbosity level: full, debug, info, warning
LOG_LEVEL: LogLevel = LogLevel.INFO


# =============================================================================
# KohakuEngine config_gen - DO NOT MODIFY
# =============================================================================

def config_gen():
    """Generate configuration from module globals."""
    return Config.from_globals()
'''

# Template for runner configuration - uses module globals + from_globals()
RUNNER_CONFIG_TEMPLATE = '''"""
KohakuRiver Runner Configuration

This file is loaded by KohakuEngine when running:
    kohakuriver.runner --config /path/to/this/file.py

Or automatically if located at:
    ~/.kohakuriver/runner_config.py

Modify the module-level variables below to customize your runner setup.
"""
from kohakuengine import Config

from kohakuriver.models.enums import LogLevel

# =============================================================================
# Network Configuration
# =============================================================================

# IP address the Runner server binds to
RUNNER_BIND_IP: str = "0.0.0.0"

# Port the Runner API server listens on
RUNNER_PORT: int = 8001

# Host server address (how runner reaches the host)
HOST_ADDRESS: str = "127.0.0.1"

# Host server port
HOST_PORT: int = 8000

# =============================================================================
# Path Configuration
# =============================================================================

# Shared storage accessible by all nodes (NFS mount)
SHARED_DIR: str = "/mnt/cluster-share"

# Local fast temporary storage on this node
LOCAL_TEMP_DIR: str = "/tmp/kohakuriver"

# Container tarball directory (empty = SHARED_DIR/kohakuriver-containers)
CONTAINER_TAR_DIR: str = ""

# Path to numactl executable (empty = use system PATH)
NUMACTL_PATH: str = ""

# Log file path (empty = console only)
RUNNER_LOG_FILE: str = ""

# =============================================================================
# Timing Configuration
# =============================================================================

# How often to send heartbeat to host (seconds)
HEARTBEAT_INTERVAL_SECONDS: int = 5

# How often to check resource/task status (seconds)
RESOURCE_CHECK_INTERVAL_SECONDS: int = 1

# =============================================================================
# Execution Configuration
# =============================================================================

# User to run tasks as (empty = current user)
RUNNER_USER: str = ""

# Default working directory inside containers
DEFAULT_WORKING_DIR: str = "/shared"

# =============================================================================
# Docker Configuration
# =============================================================================

# Whether tasks run with --privileged flag (use with caution!)
TASKS_PRIVILEGED: bool = False

# Additional host directories to mount into containers
# Format: ["host_path:container_path", ...]
ADDITIONAL_MOUNTS: list[str] = []

# Timeout for Docker image sync in seconds (default 10 minutes for large images)
DOCKER_IMAGE_SYNC_TIMEOUT: int = 600

# =============================================================================
# Docker Network Configuration
# =============================================================================

# Docker bridge network name for container communication
# Containers on same node can communicate via container name
DOCKER_NETWORK_NAME: str = "kohakuriver-net"

# Subnet for the kohakuriver-net network
DOCKER_NETWORK_SUBNET: str = "172.30.0.0/16"

# Gateway IP for the kohakuriver-net network
# Tunnel client uses this to reach the runner
DOCKER_NETWORK_GATEWAY: str = "172.30.0.1"

# =============================================================================
# Tunnel Configuration
# =============================================================================

# Enable tunnel client in containers for port forwarding
TUNNEL_ENABLED: bool = True

# Path to tunnel-client binary (empty = auto-detect)
TUNNEL_CLIENT_PATH: str = ""

# =============================================================================
# Logging Configuration
# =============================================================================

# Logging verbosity level: full, debug, info, warning
LOG_LEVEL: LogLevel = LogLevel.INFO


# =============================================================================
# KohakuEngine config_gen - DO NOT MODIFY
# =============================================================================

def config_gen():
    """Generate configuration from module globals."""
    return Config.from_globals()
'''


def generate_config(config_type: str, output_dir: str) -> str:
    """Generate a configuration file and return its path."""
    os.makedirs(output_dir, exist_ok=True)

    if config_type == "host":
        filename = "host_config.py"
        content = HOST_CONFIG_TEMPLATE
    elif config_type == "runner":
        filename = "runner_config.py"
        content = RUNNER_CONFIG_TEMPLATE
    else:
        raise ValueError(f"Unknown config type: {config_type}")

    filepath = os.path.join(output_dir, filename)

    if os.path.exists(filepath):
        print_warning(f"{filepath} already exists, skipping.")
        return filepath

    with open(filepath, "w") as f:
        f.write(content)

    return filepath


@app.command("config")
def init_config(
    generate: Annotated[
        bool,
        typer.Option("--generate", "-g", help="Generate example configuration files"),
    ] = False,
    host: Annotated[
        bool,
        typer.Option("--host", help="Generate host configuration only"),
    ] = False,
    runner: Annotated[
        bool,
        typer.Option("--runner", help="Generate runner configuration only"),
    ] = False,
    output_dir: Annotated[
        str | None,
        typer.Option("--output-dir", "-o", help="Output directory for config files"),
    ] = None,
):
    """Initialize configuration files."""
    config_dir = output_dir or get_default_config_dir()

    if generate or host or runner:
        # Generate config files
        os.makedirs(config_dir, exist_ok=True)
        generated = []

        if host or (generate and not runner):
            path = generate_config("host", config_dir)
            generated.append(("host", path))

        if runner or (generate and not host):
            path = generate_config("runner", config_dir)
            generated.append(("runner", path))

        if generated:
            console.print()
            console.print("[bold]Generated configuration files:[/bold]")
            for config_type, path in generated:
                console.print(f"  {path}")

            console.print()
            console.print("[bold]Usage:[/bold]")
            for config_type, path in generated:
                if config_type == "host":
                    console.print(f"  kohakuriver.host --config {path}")
                    console.print(
                        f"  [dim]Or auto-loaded if at ~/.kohakuriver/host_config.py[/dim]"
                    )
                elif config_type == "runner":
                    console.print(f"  kohakuriver.runner --config {path}")
                    console.print(
                        f"  [dim]Or auto-loaded if at ~/.kohakuriver/runner_config.py[/dim]"
                    )
    else:
        # Show instructions
        console.print("[bold]KohakuRiver Configuration[/bold]")
        console.print("=" * 60)
        console.print()
        console.print("KohakuRiver uses KohakuEngine for Python-based configuration.")
        console.print("Config files define module-level variables and a config_gen()")
        console.print("function that returns Config.from_globals().")
        console.print()
        console.print("[bold]Generate config files:[/bold]")
        console.print("  kohakuriver init config --generate    # Both host and runner")
        console.print("  kohakuriver init config --host        # Host only")
        console.print("  kohakuriver init config --runner      # Runner only")
        console.print("  kohakuriver init config -g -o ./      # Custom output dir")
        console.print()
        console.print("[bold]Run with config:[/bold]")
        console.print(f"  kohakuriver.host --config {config_dir}/host_config.py")
        console.print(f"  kohakuriver.runner --config {config_dir}/runner_config.py")
        console.print()
        console.print("[bold]Auto-loading:[/bold]")
        console.print("  If no --config is specified, servers will automatically load:")
        console.print(f"    Host:   {config_dir}/host_config.py")
        console.print(f"    Runner: {config_dir}/runner_config.py")
        console.print()
        console.print(f"[dim]Default config directory: {config_dir}[/dim]")


def _resolve_service_paths(
    working_dir: str | None, python_path: str | None, capture_env: bool
) -> tuple[str, str, str]:
    """Resolve working directory, Python executable, and PATH for service files.

    Args:
        working_dir: Working directory override, or None for default (~/.kohakuriver).
        python_path: Python executable override, or None for current interpreter.
        capture_env: Whether to capture the current PATH environment variable.

    Returns:
        Tuple of (resolved_working_dir, resolved_python_path, env_path).
    """
    # Default working directory - use user's kohakuriver directory
    if working_dir is None:
        working_dir = get_default_config_dir()

    # Resolve to absolute path
    resolved_working_dir = os.path.abspath(os.path.expanduser(working_dir))

    # Get Python executable path
    if python_path is None:
        python_path = sys.executable
    resolved_python_path = os.path.abspath(os.path.expanduser(python_path))

    # Get PATH environment variable
    env_path = os.environ.get("PATH", "") if capture_env else ""

    return resolved_working_dir, resolved_python_path, env_path


def _generate_service_file(
    service_name: str,
    description: str,
    exec_command: str,
    working_dir: str,
    python_path: str,
    env_path: str,
    after_units: list[str] | None = None,
    wants_units: list[str] | None = None,
) -> str:
    """Generate a systemd unit file content string.

    Args:
        service_name: Name of the service (for logging only).
        description: Description field for the [Unit] section.
        exec_command: The full ExecStart command string.
        working_dir: Absolute path for WorkingDirectory.
        python_path: Absolute path to the Python interpreter.
        env_path: PATH value for the Environment directive (empty to omit).
        after_units: List of units for After= directive. Defaults to ["network.target"].
        wants_units: List of units for Wants= directive. Defaults to none.

    Returns:
        The complete systemd service file content.
    """
    if after_units is None:
        after_units = ["network.target"]

    after_line = "After=" + " ".join(after_units)

    wants_line = ""
    if wants_units:
        wants_line = "Wants=" + " ".join(wants_units)

    env_line = f'Environment="PATH={env_path}"' if env_path else ""

    service_content = f"""[Unit]
Description={description}
{after_line}
{wants_line}

[Service]
Type=simple
WorkingDirectory={working_dir}
ExecStart={exec_command}
Restart=on-failure
RestartSec=5
{env_line}

[Install]
WantedBy=multi-user.target
"""
    return service_content


def _install_to_systemd(created_files: list[tuple[str, str]], console) -> bool:
    """Copy service files to /etc/systemd/system/ and reload the daemon.

    Args:
        created_files: List of (service_name, filepath) tuples.
        console: Rich console for output.

    Returns:
        True if all operations succeeded, False otherwise.
    """
    console.print()
    console.print("Installing service files to systemd...")
    success = True

    for service_name, filepath in created_files:
        cmd = ["sudo", "cp", filepath, "/etc/systemd/system/"]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print_error(f"Failed to copy {filepath} to /etc/systemd/system/")
            success = False

    if success:
        result = subprocess.run(["sudo", "systemctl", "daemon-reload"])
        if result.returncode != 0:
            print_error("Failed to reload systemd daemon")
            success = False

    return success


def _print_service_instructions(created_files: list[tuple[str, str]], console):
    """Print post-install instructions for starting, enabling, and viewing logs.

    Args:
        created_files: List of (service_name, filepath) tuples.
        console: Rich console for output.
    """
    print_success("Service files registered successfully.")
    console.print()
    console.print("[bold]To start the services:[/bold]")
    for service_name, _ in created_files:
        console.print(f"  sudo systemctl start {service_name}")
    console.print()
    console.print("[bold]To enable on boot:[/bold]")
    for service_name, _ in created_files:
        console.print(f"  sudo systemctl enable {service_name}")
    console.print()
    console.print("[bold]To view logs:[/bold]")
    for service_name, _ in created_files:
        console.print(f"  journalctl -u {service_name} -f")


@app.command("service")
def init_service(
    host: Annotated[
        bool,
        typer.Option("--host", help="Create and register host service"),
    ] = False,
    runner: Annotated[
        bool,
        typer.Option("--runner", help="Create and register runner service"),
    ] = False,
    all_services: Annotated[
        bool,
        typer.Option("--all", help="Create and register both services"),
    ] = False,
    host_config: Annotated[
        str | None,
        typer.Option("--host-config", help="Path to host config file for service"),
    ] = None,
    runner_config: Annotated[
        str | None,
        typer.Option("--runner-config", help="Path to runner config file for service"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option(
            "--working-dir",
            help="Working directory for services (default: ~/.kohakuriver)",
        ),
    ] = None,
    python_path: Annotated[
        str | None,
        typer.Option(
            "--python-path",
            help="Python executable path (default: current interpreter)",
        ),
    ] = None,
    capture_env: Annotated[
        bool,
        typer.Option(
            "--capture-env",
            help="Capture current PATH environment variable for service",
        ),
    ] = True,
    no_install: Annotated[
        bool,
        typer.Option(
            "--no-install", help="Only generate files, don't register with systemd"
        ),
    ] = False,
):
    """Create and register systemd service files.

    By default, this command creates the service files, copies them to
    /etc/systemd/system/, and reloads the systemd daemon.

    Services run as root for network interface management (VXLAN, bridges).

    Use --no-install to only generate the files without registering.
    """
    # Validate flags
    if not any([host, runner, all_services]):
        print_error("You must specify --host, --runner, or --all")
        raise typer.Exit(1)

    # Resolve paths
    resolved_working_dir, resolved_python_path, env_path = _resolve_service_paths(
        working_dir, python_path, capture_env
    )

    # Use temp directory for service files
    output_dir = tempfile.mkdtemp() if not no_install else "."

    if no_install:
        os.makedirs(output_dir, exist_ok=True)

    # Generate service file(s)
    created_files = []

    if host or all_services:
        console.print("Creating host service file...")
        # Use provided config or default to working_dir/host_config.py
        if host_config:
            config_path = os.path.abspath(os.path.expanduser(host_config))
        else:
            config_path = os.path.join(resolved_working_dir, "host_config.py")

        exec_command = (
            f"{resolved_python_path} -m kohakuriver.cli.host --config {config_path}"
        )
        service_content = _generate_service_file(
            service_name="kohakuriver-host",
            description="KohakuRiver Host Server",
            exec_command=exec_command,
            working_dir=resolved_working_dir,
            python_path=resolved_python_path,
            env_path=env_path,
        )

        output_path = os.path.join(output_dir, "kohakuriver-host.service")
        with open(output_path, "w") as f:
            f.write(service_content)
        console.print(f"  Created: {output_path}")
        created_files.append(("kohakuriver-host", output_path))

    if runner or all_services:
        console.print("Creating runner service file...")
        # Use provided config or default to working_dir/runner_config.py
        if runner_config:
            config_path = os.path.abspath(os.path.expanduser(runner_config))
        else:
            config_path = os.path.join(resolved_working_dir, "runner_config.py")

        exec_command = (
            f"{resolved_python_path} -m kohakuriver.cli.runner --config {config_path}"
        )
        service_content = _generate_service_file(
            service_name="kohakuriver-runner",
            description="KohakuRiver Runner Agent",
            exec_command=exec_command,
            working_dir=resolved_working_dir,
            python_path=resolved_python_path,
            env_path=env_path,
            after_units=["network.target", "docker.service"],
            wants_units=["docker.service"],
        )

        output_path = os.path.join(output_dir, "kohakuriver-runner.service")
        with open(output_path, "w") as f:
            f.write(service_content)
        console.print(f"  Created: {output_path}")
        created_files.append(("kohakuriver-runner", output_path))

    if not created_files:
        console.print("No service files created.")
        raise typer.Exit(1)

    # Write to temp and optionally install
    if no_install:
        console.print()
        console.print("[bold]Service files created.[/bold]")
        console.print("To install manually, copy to /etc/systemd/system/ and run:")
        console.print("  sudo systemctl daemon-reload")
        return

    success = _install_to_systemd(created_files, console)

    # Cleanup temp files
    if output_dir != ".":
        shutil.rmtree(output_dir, ignore_errors=True)

    # Print instructions
    if success:
        _print_service_instructions(created_files, console)
    else:
        print_error("Failed to register some service files.")
        raise typer.Exit(1)
