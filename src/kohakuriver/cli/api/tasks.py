"""
Task-related API wrappers.
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
# Synchronous wrappers for auto-completion
# =============================================================================


def get_tasks_sync(status: str | None = None) -> list[dict]:
    """Synchronous wrapper for get_tasks (for shell completion)."""
    try:
        return get_tasks(status=status)
    except Exception:
        return []
