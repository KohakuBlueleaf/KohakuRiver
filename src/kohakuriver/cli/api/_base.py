"""
Shared HTTP client setup, base URL config, and error handling.

All domain-specific API modules import from here.
"""

import httpx

from kohakuriver.cli import config as cli_config
from kohakuriver.cli.commands.auth import get_stored_token
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Authentication Header
# =============================================================================


def _get_auth_headers() -> dict[str, str]:
    """Get authorization headers if logged in."""
    try:
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
