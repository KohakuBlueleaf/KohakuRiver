"""
Docker client wrapper using docker-py SDK.

This module provides the DockerManager class, a high-level wrapper around
the docker-py SDK for container and image management in HakuRiver.

Features:
    - Container lifecycle management (create, start, stop, remove, pause)
    - Task and VPS container creation with resource constraints
    - Image operations (pull, commit, save, load)
    - Container synchronization via shared storage tarballs

The class is composed from three mixins:
    - ContainerManagerMixin: Container lifecycle and queries
    - ImageManagerMixin: Image operations
    - SyncManagerMixin: Tarball/sync operations
"""

import docker

from kohakuriver.docker.container_manager import ContainerManagerMixin
from kohakuriver.docker.exceptions import DockerConnectionError
from kohakuriver.docker.image_manager import ImageManagerMixin
from kohakuriver.docker.sync_manager import SyncManagerMixin
from kohakuriver.utils.logger import get_logger

log = get_logger(__name__)


# =============================================================================
# DockerManager Class
# =============================================================================


class DockerManager(ContainerManagerMixin, ImageManagerMixin, SyncManagerMixin):
    """
    Manages Docker operations for HakuRiver using docker-py SDK.

    Provides methods for:
        - Container lifecycle (create, start, stop, remove, pause, unpause)
        - Image management (pull, commit, save, load)
        - Container synchronization from shared storage

    Attributes:
        client: The docker-py client instance.
    """

    def __init__(self, timeout: int | None = None):
        """
        Initialize Docker client.

        Args:
            timeout: Request timeout in seconds. None means no timeout.

        Raises:
            DockerConnectionError: If connection to Docker daemon fails.
        """
        try:
            self.client = docker.from_env(timeout=timeout)
            self.client.ping()
            log.debug("Docker client initialized successfully")
        except Exception as e:
            log.error(f"Failed to connect to Docker daemon: {e}")
            raise DockerConnectionError(f"Failed to connect to Docker: {e}") from e


# =============================================================================
# Global Instance
# =============================================================================

_docker_manager: DockerManager | None = None


def get_docker_manager() -> DockerManager:
    """
    Get the global DockerManager instance.

    Returns:
        Lazily initialized DockerManager singleton.
    """
    global _docker_manager
    if _docker_manager is None:
        _docker_manager = DockerManager()
    return _docker_manager
