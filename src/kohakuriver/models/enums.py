"""
Enumeration types for HakuRiver.

This module defines all enumeration types used throughout the HakuRiver system
for consistent status tracking, categorization, and configuration options.
"""

from enum import Enum


# =============================================================================
# Task-Related Enums
# =============================================================================


class TaskStatus(str, Enum):
    """
    Task execution lifecycle status.

    State transitions:
        PENDING_APPROVAL -> PENDING (approved) or REJECTED
        PENDING -> ASSIGNING -> RUNNING -> COMPLETED/FAILED/KILLED
        RUNNING -> PAUSED -> RUNNING (resume)
        RUNNING -> STOPPED (graceful stop)
        RUNNING -> KILLED_OOM (out of memory)
        Any -> LOST (runner connection lost)
    """

    PENDING_APPROVAL = "pending_approval"  # User task awaiting operator/admin approval
    REJECTED = "rejected"  # Task rejected by operator/admin
    PENDING = "pending"  # Task submitted, waiting for assignment
    ASSIGNING = "assigning"  # Task being assigned to a runner
    RUNNING = "running"  # Task actively executing
    PAUSED = "paused"  # Task execution paused
    COMPLETED = "completed"  # Task finished successfully
    FAILED = "failed"  # Task finished with error
    KILLED = "killed"  # Task terminated by user request
    KILLED_OOM = "killed_oom"  # Task killed due to out-of-memory
    LOST = "lost"  # Runner lost connection, task status unknown
    STOPPED = "stopped"  # Task gracefully stopped


class TaskType(str, Enum):
    """
    Type of task to execute.

    - COMMAND: One-shot command execution with stdout/stderr capture
    - VPS: Long-running interactive session with SSH access
    """

    COMMAND = "command"
    VPS = "vps"


# =============================================================================
# Node-Related Enums
# =============================================================================


class NodeStatus(str, Enum):
    """
    Runner node health status.

    Determined by heartbeat presence within configured timeout.
    """

    ONLINE = "online"  # Node responding to heartbeats
    OFFLINE = "offline"  # Node not responding (missed heartbeats)


# =============================================================================
# Configuration Enums
# =============================================================================


class LogLevel(str, Enum):
    """
    Logging verbosity levels for HakuRiver components.

    Levels (from most to least verbose):
        - FULL: Complete trace with detailed stack information
        - DEBUG: Debug messages and above
        - INFO: Informational messages and above
        - WARNING: Only warnings and errors
    """

    FULL = "full"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"


class SSHKeyMode(str, Enum):
    """
    SSH key configuration mode for VPS creation.

    Determines how SSH authentication is handled:
        - NONE: Passwordless root login (least secure)
        - UPLOAD: User provides their public key (recommended)
        - GENERATE: Server generates keypair, returns private key
    """

    NONE = "none"
    UPLOAD = "upload"
    GENERATE = "generate"
