"""
Authentication module for KohakuRiver Host.

Provides utilities, dependencies, and routes for authentication.
"""

from kohakuriver.host.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_admin,
    require_operator,
    require_role,
    require_user,
    require_viewer,
)
from kohakuriver.host.auth.utils import (
    generate_session_id,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)

__all__ = [
    # Utils
    "hash_password",
    "verify_password",
    "generate_token",
    "hash_token",
    "generate_session_id",
    # Dependencies
    "get_current_user",
    "get_current_user_optional",
    "require_role",
    "require_viewer",
    "require_user",
    "require_operator",
    "require_admin",
]
