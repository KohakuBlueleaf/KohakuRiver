"""
Container sync/tarball operations mixin for DockerManager.

This module provides the SyncManagerMixin class with methods for:
    - Listing shared tarballs in shared storage
    - Checking if a local image needs syncing
    - Loading (syncing) images from shared storage
    - Creating container tarballs for sharing
"""

import os
import re
import time

from kohakuriver.docker.exceptions import ImageImportError
from kohakuriver.docker.naming import image_tag
from kohakuriver.utils.logger import get_logger

log = get_logger(__name__)


class SyncManagerMixin:
    """
    Mixin providing container sync/tarball operations.

    Expects the following methods/attributes from the composing class:
        - ``self.client``: docker-py client instance
        - ``self.get_image_created_timestamp(tag)``: from ImageManagerMixin
        - ``self.load_image(path)``: from ImageManagerMixin
        - ``self.stop_container(name)``: from ContainerManagerMixin
        - ``self.commit_container(name, repo, tag)``: from ImageManagerMixin
        - ``self.save_image(tag, path)``: from ImageManagerMixin
        - ``self.remove_image(tag, force)``: from ImageManagerMixin
        - ``self.prune_dangling_images()``: from ImageManagerMixin
    """

    def list_shared_tarballs(
        self,
        container_tar_dir: str,
        container_name: str,
    ) -> list[tuple[int, str]]:
        """
        List available tarballs for a container in shared storage.

        Args:
            container_tar_dir: Directory containing tarballs.
            container_name: Container name to search for.

        Returns:
            List of (timestamp, path) tuples, sorted newest first.
        """
        pattern = re.compile(rf"^{re.escape(container_name.lower())}-(\d+)\.tar$")
        tar_files: list[tuple[int, str]] = []

        if not os.path.isdir(container_tar_dir):
            return []

        for filename in os.listdir(container_tar_dir):
            match = pattern.match(filename)
            if match:
                try:
                    timestamp = int(match.group(1))
                    tar_path = os.path.join(container_tar_dir, filename)
                    tar_files.append((timestamp, tar_path))
                except ValueError:
                    continue

        tar_files.sort(key=lambda x: x[0], reverse=True)
        return tar_files

    def needs_sync(
        self,
        container_name: str,
        container_tar_dir: str,
    ) -> tuple[bool, str | None]:
        """
        Check if local image needs sync from shared storage.

        Args:
            container_name: Container name.
            container_tar_dir: Directory containing tarballs.

        Returns:
            Tuple of (needs_sync, path_to_latest_tar).
        """
        kohakuriver_tag = image_tag(container_name, "base")
        local_timestamp = self.get_image_created_timestamp(kohakuriver_tag)
        shared_tars = self.list_shared_tarballs(container_tar_dir, container_name)

        if not shared_tars:
            return False, None

        latest_timestamp, latest_path = shared_tars[0]

        if local_timestamp is None:
            log.info(f"Local image for {container_name} not found, sync needed")
            return True, latest_path

        if latest_timestamp > local_timestamp:
            log.info(
                f"Newer tarball for {container_name} "
                f"(shared: {latest_timestamp}, local: {local_timestamp})"
            )
            return True, latest_path

        log.debug(f"Local image for {container_name} is up-to-date")
        return False, None

    def sync_from_shared(self, container_name: str, tarball_path: str) -> bool:
        """
        Sync (load) an image from shared storage.

        Args:
            container_name: Container name.
            tarball_path: Path to the tarball.

        Returns:
            True if sync succeeded, False otherwise.
        """
        try:
            self.load_image(tarball_path)
            return True
        except ImageImportError as e:
            log.error(f"Failed to sync {container_name}: {e}")
            return False

    def create_container_tarball(
        self,
        source_container: str,
        kohakuriver_name: str,
        container_tar_dir: str,
    ) -> str | None:
        """
        Create a HakuRiver container tarball from an existing container.

        Args:
            source_container: Name of existing container to commit.
            kohakuriver_name: HakuRiver environment name.
            container_tar_dir: Directory to store tarball.

        Returns:
            Path to created tarball, or None on failure.
        """
        kohakuriver_tag = image_tag(kohakuriver_name, "base")
        timestamp = int(time.time())
        tarball_filename = f"{kohakuriver_name}-{timestamp}.tar"
        tarball_path = os.path.join(container_tar_dir, tarball_filename)

        try:
            self.stop_container(source_container)
            self.commit_container(
                source_container, f"kohakuriver/{kohakuriver_name}", "base"
            )
            self.save_image(kohakuriver_tag, tarball_path)

            # Clean up old tarballs
            for old_ts, old_path in self.list_shared_tarballs(
                container_tar_dir, kohakuriver_name
            ):
                if old_ts < timestamp:
                    try:
                        os.remove(old_path)
                        log.info(f"Removed old tarball: {old_path}")
                    except OSError as e:
                        log.warning(f"Failed to remove old tarball {old_path}: {e}")

            self.prune_dangling_images()

            log.info(f"Created container tarball at {tarball_path}")
            return tarball_path

        except Exception as e:
            log.error(f"Failed to create container tarball: {e}")
            self.remove_image(kohakuriver_tag, force=True)
            return None
