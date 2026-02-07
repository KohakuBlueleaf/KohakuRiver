"""
FastAPI dependencies for authentication.

Provides dependency functions for extracting and validating users from
requests, and role-based access control.
"""

import datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from kohakuriver.db.auth import Session, Token, User, UserRole
from kohakuriver.host.auth.utils import hash_token
from kohakuriver.host.config import config as _host_config
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Config Access
# =============================================================================


@lru_cache()
def _get_config():
    """Get host config (cached)."""
    return _host_config


def is_auth_enabled() -> bool:
    """Check if authentication is enabled."""
    return _get_config().AUTH_ENABLED


# =============================================================================
# User Extraction
# =============================================================================


def _get_user_from_session(session_id: str) -> User | None:
    """
    Get user from session cookie.

    Args:
        session_id: Session ID from cookie.

    Returns:
        User if session is valid, None otherwise.
    """
    try:
        session = Session.get_or_none(Session.session_id == session_id)
        if session is None:
            return None

        if session.is_expired():
            # Clean up expired session
            session.delete_instance()
            return None

        user = session.user
        if not user.is_active:
            return None

        return user
    except Exception as e:
        logger.warning(f"Session lookup failed: {e}")
        return None


def _get_user_from_token(token: str) -> User | None:
    """
    Get user from API token (Authorization header).

    Args:
        token: API token from Authorization header.

    Returns:
        User if token is valid, None otherwise.
    """
    try:
        token_hash = hash_token(token)
        token_record = Token.get_or_none(Token.token_hash == token_hash)
        if token_record is None:
            return None

        user = token_record.user
        if not user.is_active:
            return None

        # Update last used timestamp
        token_record.update_last_used()

        return user
    except Exception as e:
        logger.warning(f"Token lookup failed: {e}")
        return None


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extract token from Authorization header."""
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    return authorization[7:]


# =============================================================================
# Authentication Dependencies
# =============================================================================


async def get_current_user_optional(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session_id: Annotated[str | None, Cookie(alias="kohakuriver_session")] = None,
) -> User:
    """
    Get current user if authenticated, pseudo user otherwise.

    Checks both session cookie and Authorization header.
    Returns admin pseudo-user when auth is disabled (all operations allowed).
    Returns anonymous pseudo-user when auth is enabled but user not authenticated.
    """
    config = _get_config()

    # If auth is disabled, return admin pseudo user (all operations allowed)
    if not config.AUTH_ENABLED:
        return _create_mock_admin_user()

    # Check admin secret header (for bootstrap)
    admin_token = request.headers.get("X-Admin-Token")
    if admin_token and config.ADMIN_SECRET and admin_token == config.ADMIN_SECRET:
        # Return admin pseudo user for bootstrap operations
        return _create_mock_admin_user()

    # Try session cookie first
    if session_id:
        user = _get_user_from_session(session_id)
        if user:
            return user

    # Try Authorization header
    token = _extract_bearer_token(authorization)
    if token:
        user = _get_user_from_token(token)
        if user:
            return user

    return _create_anonymous_user()


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session_id: Annotated[str | None, Cookie(alias="kohakuriver_session")] = None,
) -> User:
    """
    Get current authenticated user.

    Raises HTTPException 401 if not authenticated.
    If auth is disabled, raises HTTPException 503.
    """
    config = _get_config()

    if not config.AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not enabled on this server",
        )

    user = await get_current_user_optional(request, authorization, session_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# =============================================================================
# Role-Based Access Control
# =============================================================================


def require_role(required_role: str):
    """
    Create a dependency that requires a specific role or higher.

    Args:
        required_role: Minimum required role (anony, viewer, user, operator, admin).

    Returns:
        Dependency function that validates user role.
    """

    async def role_checker(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        session_id: Annotated[str | None, Cookie(alias="kohakuriver_session")] = None,
    ) -> User:
        user = await get_current_user_optional(request, authorization, session_id)

        # Check if user meets role requirement
        if not user.has_role(required_role):
            # Anonymous user trying to access protected resource
            if user.role == UserRole.ANONY:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # Authenticated user with insufficient permissions
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}",
            )

        return user

    return role_checker


def _create_mock_admin_user() -> User:
    """Create a mock admin user for when auth is disabled."""
    user = User()
    user.id = 0
    user.username = "_system"
    user.display_name = "System (Auth Disabled)"
    user.is_active = True
    user.role = UserRole.ADMIN
    user.created_at = datetime.datetime.now()
    return user


def _create_anonymous_user() -> User:
    """Create an anonymous user for unauthenticated access."""
    user = User()
    user.id = -1
    user.username = "_anonymous"
    user.display_name = "Anonymous"
    user.is_active = True
    user.role = UserRole.ANONY
    user.created_at = datetime.datetime.now()
    return user


# =============================================================================
# Convenience Dependencies
# =============================================================================


# Pre-built dependencies for common role requirements
require_viewer = require_role(UserRole.VIEWER)
require_user = require_role(UserRole.USER)
require_operator = require_role(UserRole.OPERATOR)
require_admin = require_role(UserRole.ADMIN)


# Type aliases for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User, Depends(get_current_user_optional)]
ViewerUser = Annotated[User, Depends(require_viewer)]
AuthUser = Annotated[User, Depends(require_user)]
OperatorUser = Annotated[User, Depends(require_operator)]
AdminUser = Annotated[User, Depends(require_admin)]


# =============================================================================
# Admin Token Check
# =============================================================================


async def check_admin_token(
    request: Request,
) -> bool:
    """
    Check if request has valid admin token.

    Used for bootstrap operations (creating first invitation).

    Returns:
        True if valid admin token present, False otherwise.
    """
    config = _get_config()

    if not config.ADMIN_SECRET:
        return False

    admin_token = request.headers.get("X-Admin-Token")
    if not admin_token:
        return False

    return admin_token == config.ADMIN_SECRET
