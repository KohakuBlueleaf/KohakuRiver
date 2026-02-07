"""
Authentication API routes for KohakuRiver.

Provides endpoints for:
- Login/logout
- User info
- Registration with invitations
- API token management
- Invitation management (admin)
"""

import datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from kohakuriver.db.auth import (
    Group,
    Invitation,
    Session,
    Token,
    User,
    UserRole,
)
from kohakuriver.host.auth.dependencies import (
    AdminUser,
    CurrentUser,
    OperatorUser,
    OptionalUser,
    is_auth_enabled,
)
from kohakuriver.host.config import config as _host_config
from kohakuriver.host.auth.utils import (
    generate_invitation_token,
    generate_session_id,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


# =============================================================================
# Request/Response Models
# =============================================================================


class LoginRequest(BaseModel):
    """Login request body."""

    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response."""

    message: str
    user: dict


class RegisterRequest(BaseModel):
    """Registration request body."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    display_name: str | None = Field(None, max_length=100)


class RegisterResponse(BaseModel):
    """Registration response."""

    message: str
    user: dict


class UserResponse(BaseModel):
    """User info response."""

    id: int
    username: str
    display_name: str | None
    role: str
    is_active: bool
    created_at: str | None


class TokenCreateRequest(BaseModel):
    """Token creation request."""

    name: str = Field(..., min_length=1, max_length=100)


class TokenCreateResponse(BaseModel):
    """Token creation response (includes plaintext token)."""

    id: int
    name: str
    token: str  # Plaintext token - only shown once
    created_at: str


class TokenResponse(BaseModel):
    """Token info response (no plaintext)."""

    id: int
    name: str
    last_used: str | None
    created_at: str


class InvitationCreateRequest(BaseModel):
    """Invitation creation request."""

    role: str = Field(default=UserRole.USER)
    group_id: int | None = None
    max_usage: int = Field(default=1, ge=1)
    expires_hours: int = Field(default=72, ge=1, le=720)  # Max 30 days


class InvitationResponse(BaseModel):
    """Invitation info response."""

    id: int
    token: str
    role: str
    group_id: int | None
    max_usage: int
    usage_count: int
    remaining_uses: int
    expires_at: str
    is_valid: bool
    created_by_id: int | None
    created_at: str


# =============================================================================
# Helper Functions
# =============================================================================


def _get_config():
    """Get host config."""
    return _host_config


def _set_session_cookie(response: Response, session_id: str) -> None:
    """Set the session cookie on the response."""
    config = _get_config()
    max_age = config.SESSION_EXPIRE_HOURS * 3600

    response.set_cookie(
        key="kohakuriver_session",
        value=session_id,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True if using HTTPS
    )


def _clear_session_cookie(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key="kohakuriver_session")


# =============================================================================
# Auth Status Endpoint
# =============================================================================


@router.get("/status")
async def auth_status():
    """Get authentication system status."""
    config = _get_config()
    return {
        "auth_enabled": config.AUTH_ENABLED,
        "session_expire_hours": (
            config.SESSION_EXPIRE_HOURS if config.AUTH_ENABLED else None
        ),
    }


# =============================================================================
# Login/Logout Endpoints
# =============================================================================


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """
    Login with username and password.

    Creates a session and sets a session cookie.
    """
    if not is_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not enabled",
        )

    # Find user
    user = User.get_or_none(User.username == request.username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Check password
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    # Create session
    config = _get_config()
    session_id = generate_session_id()
    expires_at = datetime.datetime.now() + datetime.timedelta(
        hours=config.SESSION_EXPIRE_HOURS
    )

    Session.create(
        session_id=session_id,
        user=user,
        expires_at=expires_at,
    )

    # Set cookie
    _set_session_cookie(response, session_id)

    logger.info(f"User '{user.username}' logged in")

    return LoginResponse(
        message="Login successful",
        user=user.to_dict(),
    )


@router.post("/logout")
async def logout(
    response: Response,
    session_id: Annotated[str | None, Cookie(alias="kohakuriver_session")] = None,
):
    """
    Logout and destroy session.

    Clears the session cookie and deletes the session from database.
    """
    if session_id:
        # Delete session from database
        deleted = Session.delete().where(Session.session_id == session_id).execute()
        if deleted:
            logger.debug(f"Session destroyed on logout")

    # Clear cookie
    _clear_session_cookie(response)

    return {"message": "Logged out successfully"}


# =============================================================================
# User Info Endpoint
# =============================================================================


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: CurrentUser):
    """Get current authenticated user's information."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=(
            current_user.created_at.isoformat() if current_user.created_at else None
        ),
    )


# =============================================================================
# Registration Endpoint
# =============================================================================


@router.post("/register", response_model=RegisterResponse)
async def register(
    request: RegisterRequest,
    response: Response,
    token: str = Query(..., description="Invitation token"),
):
    """
    Register a new user with an invitation token.

    Registration URL: /register?token=xxx

    Special case: If token matches ADMIN_REGISTER_SECRET, creates an admin account.
    This allows bootstrapping the first admin user via the web UI.
    """
    if not is_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not enabled",
        )

    config = _get_config()

    # Check for admin registration secret (bootstrap)
    is_admin_bootstrap = (
        config.ADMIN_REGISTER_SECRET and token == config.ADMIN_REGISTER_SECRET
    )

    if is_admin_bootstrap:
        # Admin bootstrap registration
        role = UserRole.ADMIN
        logger.info(f"Admin bootstrap registration for '{request.username}'")
    else:
        # Normal invitation-based registration
        invitation = Invitation.get_or_none(Invitation.token == token)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitation token",
            )

        if not invitation.is_valid():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation has expired or reached usage limit",
            )

        role = invitation.role

    # Check if username is taken
    existing = User.get_or_none(User.username == request.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    # Create user
    password_hash = hash_password(request.password)
    user = User.create(
        username=request.username,
        display_name=request.display_name or request.username,
        password_hash=password_hash,
        role=role,
        is_active=True,
    )

    # Mark invitation as used (only for normal invitations)
    if not is_admin_bootstrap:
        invitation.use()

    # Auto-login: create session
    session_id = generate_session_id()
    expires_at = datetime.datetime.now() + datetime.timedelta(
        hours=config.SESSION_EXPIRE_HOURS
    )

    Session.create(
        session_id=session_id,
        user=user,
        expires_at=expires_at,
    )

    _set_session_cookie(response, session_id)

    logger.info(f"New user '{user.username}' registered with role '{user.role}'")

    return RegisterResponse(
        message="Registration successful",
        user=user.to_dict(),
    )


# =============================================================================
# API Token Endpoints
# =============================================================================


@router.get("/tokens", response_model=list[TokenResponse])
async def list_tokens(current_user: CurrentUser):
    """List current user's API tokens."""
    tokens = (
        Token.select()
        .where(Token.user == current_user)
        .order_by(Token.created_at.desc())
    )

    return [
        TokenResponse(
            id=t.id,
            name=t.name,
            last_used=t.last_used.isoformat() if t.last_used else None,
            created_at=t.created_at.isoformat() if t.created_at else None,
        )
        for t in tokens
    ]


@router.post("/tokens/create", response_model=TokenCreateResponse)
async def create_token(request: TokenCreateRequest, current_user: CurrentUser):
    """
    Create a new API token.

    The plaintext token is only returned once - store it securely!
    """
    # Generate token
    plaintext_token = generate_token(32)
    token_hash = hash_token(plaintext_token)

    # Create token record
    token = Token.create(
        user=current_user,
        token_hash=token_hash,
        name=request.name,
    )

    logger.info(f"User '{current_user.username}' created API token '{request.name}'")

    return TokenCreateResponse(
        id=token.id,
        name=token.name,
        token=plaintext_token,  # Only returned once!
        created_at=token.created_at.isoformat(),
    )


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: int, current_user: CurrentUser):
    """Revoke (delete) an API token."""
    token = Token.get_or_none((Token.id == token_id) & (Token.user == current_user))

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    token_name = token.name
    token.delete_instance()

    logger.info(f"User '{current_user.username}' revoked API token '{token_name}'")

    return {"message": f"Token '{token_name}' revoked"}


# =============================================================================
# Invitation Endpoints (Admin)
# =============================================================================


@router.get("/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    request: Request,
    current_user: OptionalUser,
):
    """
    List all invitations (admin only).

    Can also be accessed with X-Admin-Token header for bootstrap.
    """
    # Check admin access (admin token already returns admin pseudo user)
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    invitations = Invitation.select().order_by(Invitation.created_at.desc())

    return [
        InvitationResponse(
            id=inv.id,
            token=inv.token,
            role=inv.role,
            group_id=inv.group_id if inv.group else None,
            max_usage=inv.max_usage,
            usage_count=inv.usage_count,
            remaining_uses=inv.max_usage - inv.usage_count,
            expires_at=inv.expires_at.isoformat() if inv.expires_at else None,
            is_valid=inv.is_valid(),
            created_by_id=inv.created_by_id if inv.created_by else None,
            created_at=inv.created_at.isoformat() if inv.created_at else None,
        )
        for inv in invitations
    ]


@router.post("/invitations", response_model=InvitationResponse)
async def create_invitation(
    request_body: InvitationCreateRequest,
    current_user: OptionalUser,
):
    """
    Create a new invitation.

    Access rules:
    - Admin: Can create invitations for any role
    - Operator: Can only create 'viewer' invitations
    - Can also be accessed with X-Admin-Token header for bootstrap
    """
    # Check access: must be at least operator
    if not current_user.is_operator():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator access required",
        )

    # Operators can only create viewer invitations
    if not current_user.is_admin() and request_body.role != UserRole.VIEWER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operators can only create viewer invitations",
        )

    # Validate role
    if request_body.role not in UserRole.all_roles():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {UserRole.all_roles()}",
        )

    # Validate group if provided
    group = None
    if request_body.group_id:
        group = Group.get_or_none(Group.id == request_body.group_id)
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group not found",
            )

    # Generate invitation
    token = generate_invitation_token()
    expires_at = datetime.datetime.now() + datetime.timedelta(
        hours=request_body.expires_hours
    )

    invitation = Invitation.create(
        token=token,
        role=request_body.role,
        group=group,
        max_usage=request_body.max_usage,
        expires_at=expires_at,
        created_by=current_user if current_user and current_user.id > 0 else None,
    )

    logger.info(
        f"Invitation created: role={request_body.role}, "
        f"max_usage={request_body.max_usage}, "
        f"expires_at={expires_at.isoformat()}"
    )

    return InvitationResponse(
        id=invitation.id,
        token=invitation.token,
        role=invitation.role,
        group_id=invitation.group_id if invitation.group else None,
        max_usage=invitation.max_usage,
        usage_count=invitation.usage_count,
        remaining_uses=invitation.max_usage - invitation.usage_count,
        expires_at=invitation.expires_at.isoformat(),
        is_valid=invitation.is_valid(),
        created_by_id=invitation.created_by_id if invitation.created_by else None,
        created_at=invitation.created_at.isoformat(),
    )


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: int,
    current_user: OptionalUser,
):
    """Revoke (delete) an invitation (admin only)."""
    # Check admin access (admin token already returns admin pseudo user)
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    invitation = Invitation.get_or_none(Invitation.id == invitation_id)
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )

    invitation.delete_instance()

    logger.info(f"Invitation {invitation_id} revoked")

    return {"message": f"Invitation {invitation_id} revoked"}


# =============================================================================
# User Management Endpoints (Admin/Operator)
# =============================================================================


@router.get("/users", response_model=list[UserResponse])
async def list_users(current_user: OperatorUser):
    """List all users (operator+ can view)."""
    users = User.select().order_by(User.created_at.desc())

    return [
        UserResponse(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at.isoformat() if u.created_at else None,
        )
        for u in users
    ]


class UserUpdateRequest(BaseModel):
    """User update request."""

    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, request: UserUpdateRequest, admin_user: AdminUser):
    """Update a user (admin only)."""
    user = User.get_or_none(User.id == user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Prevent admin from demoting themselves
    if user.id == admin_user.id and request.role and request.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot demote yourself",
        )

    # Update fields
    if request.display_name is not None:
        user.display_name = request.display_name
    if request.role is not None:
        if request.role not in UserRole.all_roles():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role. Must be one of: {UserRole.all_roles()}",
            )
        user.role = request.role
    if request.is_active is not None:
        # Prevent admin from disabling themselves
        if user.id == admin_user.id and not request.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot disable yourself",
            )
        user.is_active = request.is_active

    user.save()

    logger.info(f"Admin '{admin_user.username}' updated user '{user.username}'")

    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin_user: AdminUser):
    """Delete a user (admin only)."""
    user = User.get_or_none(User.id == user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Prevent admin from deleting themselves
    if user.id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )

    username = user.username
    user.delete_instance()

    logger.info(f"Admin '{admin_user.username}' deleted user '{username}'")

    return {"message": f"User '{username}' deleted"}
