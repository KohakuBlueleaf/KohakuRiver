"""
Runner configuration.

A global Config instance that can be modified at runtime.
"""

import getpass
import os
import socket
from dataclasses import dataclass, field

from kohakuriver.models.enums import LogLevel


@dataclass
class RunnerConfig:
    """Runner agent configuration."""

    # Network Configuration
    RUNNER_BIND_IP: str = "0.0.0.0"
    RUNNER_PORT: int = 8001
    HOST_ADDRESS: str = "127.0.0.1"
    HOST_PORT: int = 8000

    # Path Configuration
    SHARED_DIR: str = "/mnt/cluster-share"
    LOCAL_TEMP_DIR: str = "/tmp/kohakuriver"
    CONTAINER_TAR_DIR: str = ""
    NUMACTL_PATH: str = ""
    RUNNER_LOG_FILE: str = ""

    # Timing Configuration
    HEARTBEAT_INTERVAL_SECONDS: int = 5
    RESOURCE_CHECK_INTERVAL_SECONDS: int = 1

    # Execution Configuration
    RUNNER_USER: str = ""
    DEFAULT_WORKING_DIR: str = "/shared"

    # Docker Configuration
    TASKS_PRIVILEGED: bool = False
    ADDITIONAL_MOUNTS: list[str] = field(default_factory=list)
    DOCKER_IMAGE_SYNC_TIMEOUT: int = 600  # 10 minutes for large image syncs (10-30GB)

    # Tunnel Configuration
    TUNNEL_ENABLED: bool = True  # Enable tunnel client in containers
    TUNNEL_CLIENT_PATH: str = (
        ""  # Path to tunnel-client binary (auto-detected if empty)
    )

    # Docker Network Configuration
    DOCKER_NETWORK_NAME: str = "kohakuriver-net"  # Custom bridge network for containers
    DOCKER_NETWORK_SUBNET: str = "172.30.0.0/16"  # Subnet for kohakuriver-net
    DOCKER_NETWORK_GATEWAY: str = "172.30.0.1"  # Gateway IP (runner reachable at this IP)

    # Snapshot Configuration
    AUTO_SNAPSHOT_ON_STOP: bool = True
    MAX_SNAPSHOTS_PER_VPS: int = 3
    AUTO_RESTORE_ON_CREATE: bool = True

    # Logging Configuration
    LOG_LEVEL: LogLevel = LogLevel.INFO

    def get_hostname(self) -> str:
        """Get this runner's hostname."""
        return socket.gethostname()

    def get_host_url(self) -> str:
        """Get the full host URL."""
        return f"http://{self.HOST_ADDRESS}:{self.HOST_PORT}"

    def get_container_tar_dir(self) -> str:
        """Get the container tarball directory path."""
        if self.CONTAINER_TAR_DIR:
            return self.CONTAINER_TAR_DIR
        return os.path.join(self.SHARED_DIR, "kohakuriver-containers")

    def get_runner_user(self) -> str:
        """Get the user to run tasks as."""
        if self.RUNNER_USER:
            return self.RUNNER_USER
        return getpass.getuser()

    def get_numactl_path(self) -> str:
        """Get the numactl executable path."""
        if self.NUMACTL_PATH:
            return self.NUMACTL_PATH
        return "numactl"

    def get_state_db_path(self) -> str:
        """
        Get the path for runner state database (KohakuVault).

        The database is stored in a hidden .kohakuriver subdirectory within
        LOCAL_TEMP_DIR to keep user workspace clean.
        """
        config_dir = os.path.join(self.LOCAL_TEMP_DIR, ".kohakuriver")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "runner-state.db")

    def get_tunnel_client_path(self) -> str | None:
        """
        Get the path to the tunnel-client binary.

        Returns None if tunnel is disabled or binary not found.
        """
        if not self.TUNNEL_ENABLED:
            return None

        if self.TUNNEL_CLIENT_PATH:
            if os.path.isfile(self.TUNNEL_CLIENT_PATH):
                return self.TUNNEL_CLIENT_PATH
            return None

        # Auto-detect in common locations
        search_paths = [
            # Current working directory (service mode uses ~/.kohakuriver as WorkingDirectory)
            "./tunnel-client",
            # Installed via package
            "/usr/local/bin/tunnel-client",
            "/usr/bin/tunnel-client",
            # Relative to shared directory
            os.path.join(self.SHARED_DIR, "bin", "tunnel-client"),
            # Development build
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "kohakuriver-tunnel",
                "target",
                "release",
                "tunnel-client",
            ),
        ]

        # Add user's home directory path (only if HOME is set and valid)
        home_dir = os.environ.get("HOME")
        if home_dir and os.path.isdir(home_dir):
            search_paths.insert(
                1, os.path.join(home_dir, ".kohakuriver", "tunnel-client")
            )

        for path in search_paths:
            if os.path.isfile(path):
                return os.path.abspath(path)

        return None

    def get_runner_ws_url(self) -> str:
        """Get the WebSocket URL for tunnel client to connect to."""
        # Containers on kohakuriver-net reach the host via the network gateway
        return f"ws://{self.DOCKER_NETWORK_GATEWAY}:{self.RUNNER_PORT}"


# Global config instance
config = RunnerConfig()
