"""
Authentication database models for KohakuRiver.

This module defines models for user authentication, sessions, API tokens,
invitations, groups, and VPS assignments.
"""

import datetime
import json

import peewee

from kohakuriver.db.base import BaseModel


# =============================================================================
# Role Enum
# =============================================================================


class UserRole:
    """User role constants with hierarchy."""

    ANONY = "anony"
    VIEWER = "viewer"
    USER = "user"
    OPERATOR = "operator"
    ADMIN = "admin"

    # Role hierarchy (lower index = less privilege)
    _HIERARCHY = [ANONY, VIEWER, USER, OPERATOR, ADMIN]

    @classmethod
    def is_at_least(cls, user_role: str, required_role: str) -> bool:
        """Check if user_role has at least the required_role privilege level."""
        try:
            user_level = cls._HIERARCHY.index(user_role)
            required_level = cls._HIERARCHY.index(required_role)
            return user_level >= required_level
        except ValueError:
            return False

    @classmethod
    def all_roles(cls) -> list[str]:
        """Return all valid roles."""
        return cls._HIERARCHY.copy()


# =============================================================================
# Group Model
# =============================================================================


class Group(BaseModel):
    """
    Represents a user group with resource quotas.

    Groups can be used to organize users and set resource limits.
    """

    id = peewee.AutoField()
    name = peewee.CharField(unique=True, max_length=100)
    tier = peewee.IntegerField(default=0)  # Higher tier = more privileges
    limits_json = peewee.TextField(
        default="{}"
    )  # JSON: max_tasks, max_vps, gpu_cap, etc.
    created_at = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = "groups"

    def get_limits(self) -> dict:
        """Parse limits_json to dict."""
        if not self.limits_json:
            return {}
        try:
            return json.loads(self.limits_json)
        except json.JSONDecodeError:
            return {}

    def set_limits(self, limits: dict) -> None:
        """Store limits dict as JSON."""
        self.limits_json = json.dumps(limits)


# =============================================================================
# User Model
# =============================================================================


class User(BaseModel):
    """
    Represents a registered user.

    Users can authenticate via username/password and create API tokens.
    """

    id = peewee.AutoField()
    username = peewee.CharField(unique=True, max_length=50, index=True)
    display_name = peewee.CharField(max_length=100, null=True)
    password_hash = peewee.CharField(max_length=255)  # bcrypt hash
    is_active = peewee.BooleanField(default=True)
    role = peewee.CharField(default=UserRole.USER, max_length=20)
    created_at = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = "users"

    def has_role(self, required_role: str) -> bool:
        """Check if user has at least the required role."""
        return UserRole.is_at_least(self.role, required_role)

    def is_admin(self) -> bool:
        """Check if user is an admin."""
        return self.role == UserRole.ADMIN

    def is_operator(self) -> bool:
        """Check if user has operator or higher role."""
        return self.has_role(UserRole.OPERATOR)

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Convert user to dictionary for API responses."""
        data = {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "is_active": self.is_active,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        return data


# =============================================================================
# Session Model
# =============================================================================


class Session(BaseModel):
    """
    Represents an active user session (cookie-based auth).

    Sessions are created on login and destroyed on logout or expiration.
    """

    id = peewee.AutoField()
    session_id = peewee.CharField(unique=True, max_length=64, index=True)
    user = peewee.ForeignKeyField(User, backref="sessions", on_delete="CASCADE")
    expires_at = peewee.DateTimeField()
    created_at = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = "sessions"

    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.datetime.now() > self.expires_at


# =============================================================================
# Token Model
# =============================================================================


class Token(BaseModel):
    """
    Represents an API token for programmatic access.

    Tokens are stored as SHA3-512 hashes; plaintext is only shown once on creation.
    """

    id = peewee.AutoField()
    user = peewee.ForeignKeyField(User, backref="tokens", on_delete="CASCADE")
    token_hash = peewee.CharField(max_length=128, unique=True, index=True)  # SHA3-512
    name = peewee.CharField(max_length=100)  # User-provided name for the token
    last_used = peewee.DateTimeField(null=True)
    created_at = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = "tokens"

    def update_last_used(self) -> None:
        """Update the last_used timestamp."""
        self.last_used = datetime.datetime.now()
        self.save()

    def to_dict(self) -> dict:
        """Convert token to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# Invitation Model
# =============================================================================


class Invitation(BaseModel):
    """
    Represents an invitation for user registration.

    Invitations are required for new user signup (invitation-only system).
    """

    id = peewee.AutoField()
    token = peewee.CharField(unique=True, max_length=64, index=True)
    role = peewee.CharField(default=UserRole.USER, max_length=20)
    group = peewee.ForeignKeyField(
        Group, null=True, backref="invitations", on_delete="SET NULL"
    )
    max_usage = peewee.IntegerField(default=1)
    usage_count = peewee.IntegerField(default=0)
    expires_at = peewee.DateTimeField()
    created_by = peewee.ForeignKeyField(
        User, null=True, backref="created_invitations", on_delete="SET NULL"
    )
    created_at = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = "invitations"

    def is_valid(self) -> bool:
        """Check if invitation is still valid (not expired and has remaining uses)."""
        if datetime.datetime.now() > self.expires_at:
            return False
        if self.usage_count >= self.max_usage:
            return False
        return True

    def use(self) -> bool:
        """
        Mark invitation as used once.

        Returns:
            True if successfully used, False if invalid.
        """
        if not self.is_valid():
            return False
        self.usage_count += 1
        self.save()
        return True

    def to_dict(self) -> dict:
        """Convert invitation to dictionary for API responses."""
        return {
            "id": self.id,
            "token": self.token,
            "role": self.role,
            "group_id": self.group_id if self.group else None,
            "max_usage": self.max_usage,
            "usage_count": self.usage_count,
            "remaining_uses": self.max_usage - self.usage_count,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_valid": self.is_valid(),
            "created_by_id": self.created_by_id if self.created_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# UserGroup Model
# =============================================================================


class UserGroup(BaseModel):
    """
    Many-to-many relationship between users and groups.

    Allows users to belong to multiple groups with optional role override.
    """

    id = peewee.AutoField()
    user = peewee.ForeignKeyField(User, backref="user_groups", on_delete="CASCADE")
    group = peewee.ForeignKeyField(Group, backref="user_groups", on_delete="CASCADE")
    role_override = peewee.CharField(
        null=True, max_length=20
    )  # Optional role override within group
    created_at = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = "user_groups"
        indexes = (
            # Unique constraint on user-group pair
            (("user", "group"), True),
        )


# =============================================================================
# VpsAssignment Model
# =============================================================================


class VpsAssignment(BaseModel):
    """
    Many-to-many relationship between VPS tasks and users.

    Allows operators to assign VPS access to specific users.
    """

    id = peewee.AutoField()
    vps_task_id = peewee.BigIntegerField(index=True)  # References Task.task_id
    user = peewee.ForeignKeyField(User, backref="vps_assignments", on_delete="CASCADE")
    created_at = peewee.DateTimeField(default=datetime.datetime.now)

    class Meta:
        table_name = "vps_assignments"
        indexes = (
            # Unique constraint on vps-user pair
            (("vps_task_id", "user"), True),
        )


# =============================================================================
# Auth Tables List
# =============================================================================

AUTH_TABLES = [
    Group,
    User,
    Session,
    Token,
    Invitation,
    UserGroup,
    VpsAssignment,
]
