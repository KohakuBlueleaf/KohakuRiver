"""
Tunnel client integration helpers.

Provides functions to inject tunnel-client into container startup.
The tunnel client runs as a background daemon alongside the main process,
enabling port forwarding without Docker port mapping.
"""

from kohakuriver.runner.config import config
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# Path where tunnel-client binary is mounted inside containers
TUNNEL_CLIENT_CONTAINER_PATH = "/usr/local/bin/tunnel-client"

# Path for tunnel client logs inside container
TUNNEL_LOG_PATH = "/tmp/tunnel-client.log"


def get_tunnel_mount() -> str | None:
    """
    Get the mount specification for tunnel-client binary.

    Returns:
        Mount spec string like "host_path:/usr/local/bin/tunnel-client:ro"
        or None if tunnel is disabled or binary not found.
    """
    tunnel_path = config.get_tunnel_client_path()
    if not tunnel_path:
        if config.TUNNEL_ENABLED:
            logger.warning(
                "Tunnel enabled but tunnel-client binary not found. "
                "Port forwarding will not be available."
            )
        return None

    logger.debug(f"Using tunnel-client from: {tunnel_path}")
    return f"{tunnel_path}:{TUNNEL_CLIENT_CONTAINER_PATH}:ro"


def get_tunnel_env_vars(container_id: str) -> dict[str, str]:
    """
    Get environment variables for tunnel-client.

    Args:
        container_id: Container name/ID for tunnel identification.

    Returns:
        Dict of environment variables.
    """
    if not config.TUNNEL_ENABLED:
        return {}

    return {
        "KOHAKURIVER_TUNNEL_URL": config.get_runner_ws_url(),
        "KOHAKURIVER_CONTAINER_ID": container_id,
    }


def wrap_command_with_tunnel(
    shell_cmd: str,
    container_id: str,
    use_exec: bool = True,
) -> str:
    """
    Wrap a shell command to start tunnel-client as a background daemon.

    The tunnel client starts first, then the main command runs.
    For task containers (use_exec=True), we use exec to replace the shell.
    For VPS containers (use_exec=False), the main process stays as is.

    Args:
        shell_cmd: Original shell command to run.
        container_id: Container name/ID for tunnel identification.
        use_exec: Whether to use exec for the main command (tasks=True, VPS=False).

    Returns:
        Modified shell command with tunnel startup.
    """
    if not config.TUNNEL_ENABLED or not config.get_tunnel_client_path():
        return shell_cmd

    # Build tunnel startup command
    # - Uses environment variables set via Docker -e flags
    # - Runs in background with nohup
    # - Logs to file for debugging
    tunnel_start = (
        f"(nohup {TUNNEL_CLIENT_CONTAINER_PATH} "
        f'--runner-url "$KOHAKURIVER_TUNNEL_URL" '
        f'--container-id "$KOHAKURIVER_CONTAINER_ID" '
        f"--log-level info "
        f"> {TUNNEL_LOG_PATH} 2>&1 &) && sleep 0.1"
    )

    # Combine: start tunnel in background, then run main command
    if use_exec:
        # For tasks: tunnel starts, then exec replaces shell with main process
        return f"{tunnel_start} && {shell_cmd}"
    else:
        # For VPS: tunnel starts, then main process runs (no exec needed)
        return f"{tunnel_start} && {shell_cmd}"


def is_tunnel_available() -> bool:
    """Check if tunnel client is available for use."""
    return config.TUNNEL_ENABLED and config.get_tunnel_client_path() is not None
