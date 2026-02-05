"""
API client for CLI commands.

Provides functions to interact with the HakuRiver host API.
Returns structured data instead of printing.
"""

import httpx

from kohakuriver.cli import config as cli_config
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Authentication Header
# =============================================================================


def _get_auth_headers() -> dict[str, str]:
    """Get authorization headers if logged in."""
    try:
        from kohakuriver.cli.commands.auth import get_stored_token

        token = get_stored_token()
        if token:
            return {"Authorization": f"Bearer {token}"}
    except ImportError:
        pass
    return {}


class APIError(Exception):
    """API request error with status code and detail."""

    def __init__(
        self, message: str, status_code: int | None = None, detail: str | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _get_host_url() -> str:
    """Get the host API URL from config."""
    return f"http://{cli_config.HOST_ADDRESS}:{cli_config.HOST_PORT}/api"


def _make_request(
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    """Make an HTTP request with auth headers."""
    headers = kwargs.pop("headers", {})
    headers.update(_get_auth_headers())
    return getattr(httpx, method)(url, headers=headers, **kwargs)


def _handle_http_error(e: httpx.HTTPStatusError, context: str = "request") -> None:
    """Handle HTTP errors with consistent logging."""
    status = e.response.status_code
    try:
        detail = e.response.json()
        detail_str = detail.get("detail", str(detail))
    except Exception:
        detail_str = e.response.text

    logger.error(f"HTTP {status} on {context}: {detail_str}")
    raise APIError(
        f"HTTP {status}: {detail_str}", status_code=status, detail=detail_str
    )


# =============================================================================
# Node Operations
# =============================================================================


def get_nodes() -> list[dict]:
    """Get all registered nodes."""
    url = f"{_get_host_url()}/nodes"
    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get nodes")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return []


def get_node_health(hostname: str | None = None) -> dict | list[dict]:
    """Get health status for nodes."""
    url = f"{_get_host_url()}/health"
    if hostname:
        url += f"?hostname={hostname}"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get health")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


# =============================================================================
# Task Operations
# =============================================================================


def get_tasks(
    status: str | None = None,
    node: str | None = None,
    task_type: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Get tasks with optional filtering.

    Args:
        status: Filter by status
        node: Filter by node
        task_type: Filter by task type
        limit: Max results (None for no limit/fetch all, positive for specific limit)
    """
    url = f"{_get_host_url()}/tasks"
    params = {}
    if status:
        params["status"] = status
    if node:
        params["node"] = node
    if task_type:
        params["task_type"] = task_type
    if limit is not None and limit > 0:
        params["limit"] = limit
    else:
        # No limit - fetch all tasks (use large number)
        params["limit"] = 10000

    try:
        response = _make_request("get", url, params=params, timeout=10.0)
        response.raise_for_status()
        result = response.json()
        # Handle both list and paginated response
        if isinstance(result, list):
            return result
        return result.get("items", result)
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get tasks")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return []


def get_task_status(task_id: str) -> dict | None:
    """Get task status."""
    url = f"{_get_host_url()}/status/{task_id}"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        _handle_http_error(e, f"get task {task_id}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return None


def submit_task(
    command: str,
    arguments: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
    cores: int = 0,
    memory_bytes: int | None = None,
    targets: list[str] | None = None,
    container_name: str | None = None,
    registry_image: str | None = None,
    privileged: bool | None = None,
    additional_mounts: list[str] | None = None,
    gpu_ids: list[list[int]] | None = None,
) -> dict:
    """
    Submit a task and return result dict.

    Args:
        command: Command to execute (just the command, not args)
        arguments: Command arguments as separate list
        env_vars: Environment variables
        cores: CPU cores (0 = no limit/use available)
        memory_bytes: Memory limit
        targets: Target nodes
        container_name: Container environment
        privileged: Run with --privileged
        additional_mounts: Additional mount directories
        gpu_ids: GPU IDs for each target

    Returns:
        Dict with task_ids and message.
    """
    url = f"{_get_host_url()}/submit"

    # Build payload matching TaskSubmission model
    payload = {
        "task_type": "command",
        "command": command,
        "arguments": arguments or [],
        "env_vars": env_vars or {},
        "required_cores": cores,
        "required_memory_bytes": memory_bytes,
        "targets": targets,
        "container_name": container_name,
        "registry_image": registry_image,
        "privileged": privileged,
        "additional_mounts": additional_mounts,
        "required_gpus": gpu_ids,
    }

    # Remove None values
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        response = _make_request("post", url, json=payload, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "submit task")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def kill_task(task_id: str) -> dict:
    """Kill a task."""
    url = f"{_get_host_url()}/kill/{task_id}"

    try:
        response = _make_request("post", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"kill task {task_id}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def send_task_command(task_id: str, action: str) -> dict:
    """Send a control command (pause/resume) to a task."""
    url = f"{_get_host_url()}/command/{task_id}/{action}"

    try:
        response = _make_request("post", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"{action} task {task_id}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def get_task_stdout(task_id: str, lines: int = 1000) -> str:
    """Get stdout for a task.

    Note: Backend returns plain text, not JSON.
    """
    url = f"{_get_host_url()}/tasks/{task_id}/stdout"

    try:
        response = _make_request("get", url, params={"lines": lines}, timeout=10.0)
        response.raise_for_status()
        # Backend returns plain text (PlainTextResponse)
        return response.text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise APIError(f"Task {task_id} not found", status_code=404)
        if e.response.status_code == 400:
            # VPS tasks don't have stdout
            return ""
        _handle_http_error(e, f"get stdout for {task_id}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return ""


def get_task_stderr(task_id: str, lines: int = 1000) -> str:
    """Get stderr for a task.

    Note: Backend returns plain text, not JSON.
    """
    url = f"{_get_host_url()}/tasks/{task_id}/stderr"

    try:
        response = _make_request("get", url, params={"lines": lines}, timeout=10.0)
        response.raise_for_status()
        # Backend returns plain text (PlainTextResponse)
        return response.text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise APIError(f"Task {task_id} not found", status_code=404)
        if e.response.status_code == 400:
            # VPS tasks don't have stderr
            return ""
        _handle_http_error(e, f"get stderr for {task_id}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return ""


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
    }

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


# =============================================================================
# Synchronous wrappers for auto-completion
# =============================================================================


def get_nodes_sync() -> list[dict]:
    """Synchronous wrapper for get_nodes (for shell completion)."""
    try:
        return get_nodes()
    except Exception:
        return []


def get_tasks_sync(status: str | None = None) -> list[dict]:
    """Synchronous wrapper for get_tasks (for shell completion)."""
    try:
        return get_tasks(status=status)
    except Exception:
        return []


def get_vps_list_sync(active_only: bool = True) -> list[dict]:
    """Synchronous wrapper for get_vps_list (for shell completion)."""
    try:
        return get_vps_list(active_only=active_only)
    except Exception:
        return []


# =============================================================================
# Overlay Network Operations
# =============================================================================


def get_overlay_status() -> dict:
    """Get overlay network status and allocations."""
    url = f"{_get_host_url()}/overlay/status"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get overlay status")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def release_overlay(runner_name: str) -> dict:
    """Release overlay allocation for a runner."""
    url = f"{_get_host_url()}/overlay/release/{runner_name}"

    try:
        response = _make_request("post", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"release overlay for {runner_name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def cleanup_overlay() -> dict:
    """Cleanup inactive overlay allocations."""
    url = f"{_get_host_url()}/overlay/cleanup"

    try:
        response = _make_request("post", url, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "cleanup overlay")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


# =============================================================================
# IP Reservation Operations
# =============================================================================


def get_available_ips(runner: str | None = None, limit: int = 100) -> dict:
    """Get available IPs for reservation."""
    url = f"{_get_host_url()}/overlay/ip/available"
    params = {"limit": limit}
    if runner:
        params["runner"] = runner

    try:
        response = _make_request("get", url, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get available IPs")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def get_runner_ip_info(runner_name: str) -> dict:
    """Get IP allocation info for a runner."""
    url = f"{_get_host_url()}/overlay/ip/info/{runner_name}"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"get IP info for {runner_name}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def reserve_ip(runner: str, ip: str | None = None, ttl: int = 300) -> dict:
    """Reserve an IP address on a runner."""
    url = f"{_get_host_url()}/overlay/ip/reserve"
    params = {"runner": runner, "ttl": ttl}
    if ip:
        params["ip"] = ip

    try:
        response = _make_request("post", url, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, f"reserve IP on {runner}")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def release_ip_reservation(token: str) -> dict:
    """Release an IP reservation by token."""
    url = f"{_get_host_url()}/overlay/ip/release"
    params = {"token": token}

    try:
        response = _make_request("post", url, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "release IP reservation")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def list_ip_reservations(runner: str | None = None) -> dict:
    """List active IP reservations."""
    url = f"{_get_host_url()}/overlay/ip/reservations"
    params = {}
    if runner:
        params["runner"] = runner

    try:
        response = _make_request("get", url, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "list IP reservations")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def validate_ip_token(token: str, runner: str | None = None) -> dict:
    """Validate an IP reservation token."""
    url = f"{_get_host_url()}/overlay/ip/validate"
    params = {"token": token}
    if runner:
        params["runner"] = runner

    try:
        response = _make_request("post", url, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "validate IP token")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}


def get_ip_reservation_stats() -> dict:
    """Get IP reservation statistics."""
    url = f"{_get_host_url()}/overlay/ip/stats"

    try:
        response = _make_request("get", url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e, "get IP reservation stats")
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise APIError(f"Network error: {e}")
    return {}
