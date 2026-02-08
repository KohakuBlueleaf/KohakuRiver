"""
Docker/container API wrappers.
"""

import httpx

from kohakuriver.cli.api._base import (
    APIError,
    _get_host_url,
    _handle_http_error,
    _make_request,
    logger,
)


# =============================================================================
# Docker Operations
# =============================================================================


def get_docker_images() -> list[dict]:
    """Get Docker images."""
    url = f"{_get_host_url()}/docker/images"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, list):
            return result
        return result.get("items", [])
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get docker images")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return []


def create_docker_container(image_name: str, container_name: str) -> dict:
    """Create a Docker container for environment setup."""
    url = f"{_get_host_url()}/docker/host/create"

    payload = {
        "image_name": image_name,
        "container_name": container_name,
    }

    try:
        response = _make_request("post", url, json=payload, timeout=180.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "create container")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def commit_docker_container(source_container: str, kohakuriver_name: str) -> dict:
    """Commit a container to a KohakuRiver image."""
    url = f"{_get_host_url()}/docker/commit"

    payload = {
        "source_container": source_container,
        "kohakuriver_name": kohakuriver_name,
    }

    try:
        response = _make_request("post", url, json=payload, timeout=120.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "commit container")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def delete_docker_image(image_name: str) -> dict:
    """Delete a Docker image."""
    url = f"{_get_host_url()}/docker/images/{image_name}"

    try:
        response = _make_request("delete", url, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"delete image {image_name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


# =============================================================================
# Docker Host Container Operations
# =============================================================================


def get_host_containers() -> list[dict]:
    """Get all Docker containers on the host."""
    url = f"{_get_host_url()}/docker/host/containers"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get host containers")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return []


def delete_host_container(container_name: str) -> dict:
    """Delete a Docker container on the host."""
    url = f"{_get_host_url()}/docker/host/delete/{container_name}"

    try:
        response = _make_request("post", url, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"delete container {container_name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def stop_host_container(container_name: str) -> dict:
    """Stop a Docker container on the host."""
    url = f"{_get_host_url()}/docker/host/stop/{container_name}"

    try:
        response = _make_request("post", url, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"stop container {container_name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def start_host_container(container_name: str) -> dict:
    """Start a Docker container on the host."""
    url = f"{_get_host_url()}/docker/host/start/{container_name}"

    try:
        response = _make_request("post", url, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"start container {container_name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


# =============================================================================
# Docker Tarball Operations
# =============================================================================


def get_tarballs() -> dict:
    """Get available container tarballs."""
    url = f"{_get_host_url()}/docker/list"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get tarballs")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def create_tarball(container_name: str) -> dict:
    """Create a tarball from a container.

    Note: This can take a long time for large containers (10-50GB). No timeout.
    """
    url = f"{_get_host_url()}/docker/create_tar/{container_name}"

    try:
        # No timeout - large containers can take very long
        response = _make_request("post", url, timeout=None)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"create tarball from {container_name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def delete_tarball(name: str) -> dict:
    """Delete a container tarball."""
    url = f"{_get_host_url()}/docker/container/{name}"

    try:
        response = _make_request("delete", url, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"delete tarball {name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def migrate_container(old_name: str) -> dict:
    """Migrate a legacy container to new naming convention.

    Note: This can take a long time for large containers (10-50GB). No timeout.
    """
    url = f"{_get_host_url()}/docker/host/migrate/{old_name}"

    try:
        # No timeout - large containers can take very long
        response = _make_request("post", url, timeout=None)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"migrate container {old_name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}
