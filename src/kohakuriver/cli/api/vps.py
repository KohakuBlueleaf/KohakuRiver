"""
VPS-related API wrappers.
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
# VPS Operations
# =============================================================================


def create_vps(
    ssh_key_mode: str = "upload",
    public_key: str | None = None,
    cores: int = 1,
    memory_bytes: int | None = None,
    target: str | None = None,
    container_name: str | None = None,
    registry_image: str | None = None,
    privileged: bool | None = None,
    additional_mounts: list[str] | None = None,
    gpu_ids: list[int] | None = None,
    vps_backend: str = "docker",
    vm_image: str | None = None,
    vm_disk_size: str | None = None,
    memory_mb: int | None = None,
) -> dict:
    """
    Create a VPS task.

    Args:
        ssh_key_mode: "none", "upload", or "generate"
        public_key: SSH public key (required if ssh_key_mode is "upload")
        cores: Number of CPU cores
        memory_bytes: Memory limit in bytes
        target: Target node specification (hostname[:numa_id])
        container_name: Container environment name
        privileged: Run with --privileged
        additional_mounts: Additional mount directories
        gpu_ids: List of GPU IDs to allocate
        vps_backend: "docker" or "qemu"
        vm_image: Base VM image name (qemu only)
        vm_disk_size: VM disk size e.g. "50G" (qemu only)
        memory_mb: VM memory in MB (qemu only)

    Returns:
        Dict with task_id, ssh_port, and optionally ssh_private_key/ssh_public_key.
    """
    url = f"{_get_host_url()}/vps/create"

    # Parse target to extract hostname and numa_id
    target_hostname = None
    target_numa_id = None
    if target:
        if ":" in target:
            parts = target.split(":", 1)
            target_hostname = parts[0] if parts[0] else None
            try:
                target_numa_id = int(parts[1]) if parts[1] else None
            except ValueError:
                target_numa_id = None
        else:
            target_hostname = target

    payload = {
        "ssh_key_mode": ssh_key_mode,
        "ssh_public_key": public_key,
        "required_cores": cores,
        "required_memory_bytes": memory_bytes,
        "target_hostname": target_hostname,
        "target_numa_node_id": target_numa_id,
        "container_name": container_name,
        "registry_image": registry_image,
        "required_gpus": gpu_ids if gpu_ids else None,
        "vps_backend": vps_backend,
    }

    # Add VM-specific fields
    if vps_backend == "qemu":
        payload["vm_image"] = vm_image
        payload["vm_disk_size"] = vm_disk_size
        payload["memory_mb"] = memory_mb

    try:
        # No timeout - VPS creation can take a long time
        response = _make_request("post", url, json=payload, timeout=None)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "create VPS")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def get_vm_images(hostname: str) -> list[dict]:
    """Get available VM images from a runner node (via host proxy)."""
    url = f"{_get_host_url()}/vm/images/{hostname}"
    try:
        response = _make_request("get", url, timeout=15.0)
        response.raise_for_status()
        data = response.json()
        return data.get("images", [])
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"get VM images from {hostname}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return []


def get_vm_instances() -> dict:
    """Get VM instances across all nodes (admin only)."""
    url = f"{_get_host_url()}/vps/vm-instances"
    try:
        response = _make_request("get", url, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get VM instances")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def delete_vm_instance(
    task_id: str, hostname: str | None = None, force: bool = False
) -> dict:
    """Delete a VM instance directory (admin only)."""
    url = f"{_get_host_url()}/vps/vm-instances/{task_id}"
    params = {"force": str(force).lower()}
    if hostname:
        params["hostname"] = hostname
    try:
        response = _make_request("delete", url, params=params, timeout=60.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"delete VM instance {task_id}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def get_vps_list(active_only: bool = False) -> list[dict]:
    """Get VPS list."""
    if active_only:
        url = f"{_get_host_url()}/vps/status"
    else:
        url = f"{_get_host_url()}/vps"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get VPS list")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return []


def stop_vps(task_id: str) -> dict:
    """Stop a VPS instance."""
    url = f"{_get_host_url()}/vps/stop/{task_id}"

    try:
        response = _make_request("post", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"stop VPS {task_id}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def restart_vps(task_id: str) -> dict:
    """Restart a VPS instance.

    Useful when nvidia docker breaks (nvml error) or container becomes unresponsive.
    """
    url = f"{_get_host_url()}/vps/restart/{task_id}"

    try:
        # No timeout - restart can take a while
        response = _make_request("post", url, timeout=None)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"restart VPS {task_id}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


# =============================================================================
# Synchronous wrappers for auto-completion
# =============================================================================


def get_vps_list_sync(active_only: bool = True) -> list[dict]:
    """Synchronous wrapper for get_vps_list (for shell completion)."""
    try:
        return get_vps_list(active_only=active_only)
    except Exception:
        return []
