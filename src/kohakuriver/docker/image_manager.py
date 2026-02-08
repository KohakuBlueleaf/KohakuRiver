"""
Image management mixin for DockerManager.

This module provides the ImageManagerMixin class with methods for:
    - Image existence checks and retrieval
    - Image pull, commit, save, load
    - Image timestamp queries
    - Image removal and dangling image cleanup
"""

import datetime
import os

from docker.errors import APIError, ImageNotFound
from docker.models.images import Image

from kohakuriver.docker.exceptions import (
    ContainerNotFoundError,
    ImageBuildError,
    ImageExportError,
    ImageImportError,
    ImageNotFoundError,
)
from docker.errors import NotFound
from kohakuriver.utils.logger import get_logger

log = get_logger(__name__)


class ImageManagerMixin:
    """
    Mixin providing image management methods.

    Expects ``self.client`` to be a docker-py client instance.
    """

    def list_images(self) -> list[Image]:
        """List all local images."""
        return self.client.images.list()

    def image_exists(self, tag: str) -> bool:
        """Check if an image exists locally."""
        try:
            self.client.images.get(tag)
            return True
        except ImageNotFound:
            return False

    def get_image(self, tag: str) -> Image:
        """
        Get an image by tag.

        Raises:
            ImageNotFoundError: If image doesn't exist.
        """
        try:
            return self.client.images.get(tag)
        except ImageNotFound:
            raise ImageNotFoundError(tag)

    def pull_image(self, tag: str) -> Image:
        """Pull an image from registry."""
        log.info(f"Pulling image {tag}...")
        return self.client.images.pull(tag)

    def commit_container(
        self,
        container_name: str,
        repository: str,
        tag: str = "base",
    ) -> Image:
        """
        Commit a container to an image.

        Args:
            container_name: Container to commit.
            repository: Image repository name.
            tag: Image tag.

        Returns:
            Image object.

        Raises:
            ContainerNotFoundError: If container doesn't exist.
            ImageBuildError: If commit fails.
        """
        try:
            container = self.client.containers.get(container_name)
            image = container.commit(repository=repository, tag=tag)
            log.info(f"Committed container {container_name} to {repository}:{tag}")
            return image
        except NotFound:
            raise ContainerNotFoundError(container_name)
        except APIError as e:
            raise ImageBuildError(str(e), f"{repository}:{tag}") from e

    def save_image(self, tag: str, output_path: str) -> None:
        """
        Save an image to a tarball.

        Args:
            tag: Image tag.
            output_path: Path for the tarball.

        Raises:
            ImageNotFoundError: If image doesn't exist.
            ImageExportError: If save fails.
        """
        try:
            image = self.client.images.get(tag)
            log.info(f"Saving image {tag} to {output_path}...")

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                for chunk in image.save():
                    f.write(chunk)

            log.info(f"Image saved to {output_path}")
        except ImageNotFound:
            raise ImageNotFoundError(tag)
        except Exception as e:
            raise ImageExportError(str(e), tag) from e

    def load_image(self, tarball_path: str) -> list[Image]:
        """
        Load an image from a tarball.

        Args:
            tarball_path: Path to the tarball.

        Returns:
            List of loaded Image objects.

        Raises:
            ImageImportError: If load fails.
        """
        if not os.path.exists(tarball_path):
            raise ImageImportError(f"Tarball not found: {tarball_path}", tarball_path)

        try:
            log.info(f"Loading image from {tarball_path}...")
            with open(tarball_path, "rb") as f:
                images = self.client.images.load(f)
            log.info(f"Loaded {len(images)} image(s) from {tarball_path}")
            return images
        except Exception as e:
            raise ImageImportError(str(e), tarball_path) from e

    def get_image_created_timestamp(self, tag: str) -> int | None:
        """
        Get the creation timestamp of an image.

        Args:
            tag: Image tag.

        Returns:
            Unix timestamp, or None if not found.
        """
        try:
            image = self.client.images.get(tag)
            created_str = image.attrs.get("Created", "")
            if created_str:
                dt = datetime.datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                return int(dt.timestamp())
            return None
        except ImageNotFound:
            return None
        except Exception as e:
            log.error(f"Error getting image timestamp for {tag}: {e}")
            return None

    def remove_image(self, tag: str, force: bool = False) -> bool:
        """
        Remove an image.

        Args:
            tag: Image tag.
            force: Force removal.

        Returns:
            True if removed successfully, False otherwise.
        """
        try:
            self.client.images.remove(tag, force=force)
            log.info(f"Removed image {tag}")
            return True
        except ImageNotFound:
            return True
        except APIError as e:
            log.error(f"Failed to remove image {tag}: {e}")
            return False

    def prune_dangling_images(self) -> int:
        """
        Remove dangling images.

        Returns:
            Bytes reclaimed.
        """
        result = self.client.images.prune(filters={"dangling": True})
        space_reclaimed = result.get("SpaceReclaimed", 0)
        log.debug(f"Pruned dangling images, reclaimed {space_reclaimed} bytes")
        return space_reclaimed
