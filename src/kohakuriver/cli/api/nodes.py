"""
Node, overlay network, and IP reservation API wrappers.
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
# Synchronous wrappers for auto-completion
# =============================================================================


def get_nodes_sync() -> list[dict]:
    """Synchronous wrapper for get_nodes (for shell completion)."""
    try:
        return get_nodes()
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
