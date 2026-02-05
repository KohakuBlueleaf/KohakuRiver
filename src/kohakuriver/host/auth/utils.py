"""
Authentication utilities for KohakuRiver.

Provides functions for password hashing (bcrypt), token generation,
and token hashing (SHA3-512).
"""

import hashlib
import secrets

import bcrypt

from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Password Hashing (bcrypt)
# =============================================================================


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password.

    Returns:
        Bcrypt hash string.
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against a bcrypt hash.

    Args:
        password: Plain text password to verify.
        password_hash: Bcrypt hash to check against.

    Returns:
        True if password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception as e:
        logger.warning(f"Password verification failed: {e}")
        return False


# =============================================================================
# Token Generation and Hashing
# =============================================================================


def generate_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random token.

    Args:
        length: Number of random bytes (token will be 2x this in hex).

    Returns:
        Hex-encoded random token string.
    """
    return secrets.token_hex(length)


def generate_session_id() -> str:
    """
    Generate a session ID.

    Returns:
        32-byte hex-encoded session ID (64 chars).
    """
    return generate_token(32)


def hash_token(token: str) -> str:
    """
    Hash a token using SHA3-512.

    Tokens are stored as hashes for security; the plaintext is only
    shown once when created.

    Args:
        token: Plain text token.

    Returns:
        SHA3-512 hash as hex string (128 chars).
    """
    return hashlib.sha3_512(token.encode("utf-8")).hexdigest()


# =============================================================================
# Invitation Token Generation
# =============================================================================


def generate_invitation_token() -> str:
    """
    Generate an invitation token.

    Returns:
        32-byte hex-encoded invitation token (64 chars).
    """
    return generate_token(32)
