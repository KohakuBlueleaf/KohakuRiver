"""
Database models for HakuRiver.

This module re-exports all database models for backward compatibility.
Prefer importing from specific modules:
    - kohakuriver.db.task for Task
    - kohakuriver.db.node for Node
    - kohakuriver.db.auth for User, Session, Token, Invitation, etc.
    - kohakuriver.db.base for BaseModel, db, initialize_database
"""

# Re-export for backward compatibility
from kohakuriver.db.base import BaseModel, db, initialize_database
from kohakuriver.db.node import Node
from kohakuriver.db.task import Task

# Auth models
from kohakuriver.db.auth import (
    Group,
    Invitation,
    Session,
    Token,
    User,
    UserGroup,
    UserRole,
    VpsAssignment,
)

__all__ = [
    "db",
    "BaseModel",
    "Node",
    "Task",
    "initialize_database",
    # Auth models
    "User",
    "Session",
    "Token",
    "Invitation",
    "Group",
    "UserGroup",
    "UserRole",
    "VpsAssignment",
]
