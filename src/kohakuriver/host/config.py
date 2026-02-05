"""
Host server configuration for HakuRiver.

This module defines the configuration dataclass for the host server,
providing a centralized place for all configurable parameters.

Configuration can be modified at runtime by importing the global config
instance and updating its attributes before starting the server.

Usage:
    from kohakuriver.host.config import config

    # Modify configuration before starting
    config.HOST_PORT = 9000
    config.LOG_LEVEL = LogLevel.DEBUG
"""

import os
from dataclasses import dataclass, field

from kohakuriver.models.enums import LogLevel


# =============================================================================
# Configuration Dataclass
# =============================================================================


@dataclass
class HostConfig:
    """
    Host server configuration.

    All configuration options for the HakuRiver host server, organized by category.

    Attributes:
        HOST_BIND_IP: IP address to bind the server to.
        HOST_PORT: HTTP API port.
        HOST_SSH_PROXY_PORT: SSH proxy port for VPS tunneling.
        SHARED_DIR: Root directory for shared cluster storage.
        DB_FILE: Path to the SQLite database file.
        LOG_LEVEL: Logging verbosity level.
    """

    # -------------------------------------------------------------------------
    # Network Configuration
    # -------------------------------------------------------------------------

    HOST_BIND_IP: str = "0.0.0.0"
    HOST_PORT: int = 8000
    HOST_SSH_PROXY_PORT: int = 8002
    HOST_REACHABLE_ADDRESS: str = "127.0.0.1"

    # -------------------------------------------------------------------------
    # Path Configuration
    # -------------------------------------------------------------------------

    SHARED_DIR: str = "/mnt/cluster-share"
    DB_FILE: str = "/var/lib/kohakuriver/kohakuriver.db"
    CONTAINER_DIR: str = ""  # Defaults to SHARED_DIR/kohakuriver-containers
    HOST_LOG_FILE: str = ""

    # -------------------------------------------------------------------------
    # Timing Configuration
    # -------------------------------------------------------------------------

    HEARTBEAT_INTERVAL_SECONDS: int = 5
    HEARTBEAT_TIMEOUT_FACTOR: int = 6
    CLEANUP_CHECK_INTERVAL_SECONDS: int = 10

    # -------------------------------------------------------------------------
    # Docker Configuration
    # -------------------------------------------------------------------------

    DEFAULT_CONTAINER_NAME: str = "kohakuriver-base"
    INITIAL_BASE_IMAGE: str = "python:3.12-alpine"
    TASKS_PRIVILEGED: bool = False
    ADDITIONAL_MOUNTS: list[str] = field(default_factory=list)
    DEFAULT_WORKING_DIR: str = "/shared"

    # -------------------------------------------------------------------------
    # Environment Container Limits
    # -------------------------------------------------------------------------

    # Percentage of system resources (0.0-1.0) for env setup containers
    ENV_CONTAINER_CPU_LIMIT: float = 0.25
    ENV_CONTAINER_MEM_LIMIT: float = 0.25

    # -------------------------------------------------------------------------
    # Logging Configuration
    # -------------------------------------------------------------------------

    LOG_LEVEL: LogLevel = LogLevel.INFO

    # -------------------------------------------------------------------------
    # Overlay Network Configuration (VXLAN Hub)
    # -------------------------------------------------------------------------

    # Enable VXLAN overlay network for cross-node container communication
    # When disabled, containers use isolated per-node bridge networks
    OVERLAY_ENABLED: bool = False

    # Overlay subnet configuration
    # Format: BASE_IP/NETWORK_PREFIX/NODE_BITS/SUBNET_BITS (must sum to 32)
    # Default: 10.128.0.0/12/6/14 = 10.128-143.x.x range, avoids common 10.x.x.x
    # Example: 10.0.0.0/8/8/16 = full 10.x.x.x range, 255 runners, 64K IPs each
    OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"

    # Base VXLAN ID (each runner gets base_id + runner_id)
    OVERLAY_VXLAN_ID: int = 100

    # VXLAN UDP port (must be open in firewall between Host and Runners)
    OVERLAY_VXLAN_PORT: int = 4789

    # MTU for overlay network (1500 - 50 bytes VXLAN overhead)
    OVERLAY_MTU: int = 1450

    # -------------------------------------------------------------------------
    # Authentication Configuration
    # -------------------------------------------------------------------------

    # Enable authentication (when False, all endpoints are public)
    AUTH_ENABLED: bool = False

    # Admin secret for bootstrap operations (creating first invitation)
    # Set this via environment or config file, then use X-Admin-Token header
    ADMIN_SECRET: str = ""

    # Admin registration secret - use this as invitation token to register as admin
    # Set this to allow first admin registration via web UI: /register?token=<secret>
    # Leave empty to disable direct admin registration
    ADMIN_REGISTER_SECRET: str = ""

    # Session cookie expiration in hours (default: 30 days)
    SESSION_EXPIRE_HOURS: int = 24 * 30

    # Default invitation expiration in hours (default: 1 days)
    INVITATION_EXPIRE_HOURS: int = 24

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def get_container_dir(self) -> str:
        """
        Get the container tarball directory path.

        Returns:
            Path to the directory containing container tarballs.
            Defaults to SHARED_DIR/kohakuriver-containers if not explicitly set.
        """
        if self.CONTAINER_DIR:
            return self.CONTAINER_DIR
        return os.path.join(self.SHARED_DIR, "kohakuriver-containers")

    def get_host_url(self) -> str:
        """
        Get the full host URL for external access.

        Returns:
            URL string like "http://192.168.1.1:8000"
        """
        return f"http://{self.HOST_REACHABLE_ADDRESS}:{self.HOST_PORT}"

    def get_heartbeat_timeout(self) -> int:
        """
        Get the heartbeat timeout in seconds.

        Returns:
            Number of seconds after which a node is considered dead.
        """
        return self.HEARTBEAT_INTERVAL_SECONDS * self.HEARTBEAT_TIMEOUT_FACTOR


# =============================================================================
# Global Instance
# =============================================================================

# Global config instance - modify before server startup
config = HostConfig()
