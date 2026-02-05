"""
Task database model for HakuRiver.

This module defines the Task model which represents submitted tasks
in the cluster, including both command execution and VPS sessions.
"""

import datetime
import json

import peewee

from kohakuriver.db.base import BaseModel
from kohakuriver.models.enums import TaskStatus, TaskType


# =============================================================================
# Task Model
# =============================================================================


class Task(BaseModel):
    """
    Represents a task submitted to the cluster.

    Tasks can be either:
        - command: One-shot command execution with stdout/stderr capture
        - vps: Long-running interactive session with SSH access

    Attributes:
        task_id: Unique snowflake ID (primary key).
        task_type: Type of task ('command' or 'vps').
        batch_id: ID linking tasks submitted together.
        command: Command to execute (or SSH public key for VPS).
        status: Current task status.
    """

    # -------------------------------------------------------------------------
    # Primary Identification
    # -------------------------------------------------------------------------

    task_id = peewee.BigIntegerField(primary_key=True)
    task_type = peewee.CharField(default=TaskType.COMMAND.value)
    batch_id = peewee.BigIntegerField(null=True, index=True)

    # -------------------------------------------------------------------------
    # Command Specification
    # -------------------------------------------------------------------------

    command = peewee.TextField()
    arguments = peewee.TextField(default="[]")  # JSON array
    env_vars = peewee.TextField(default="{}")  # JSON object

    # -------------------------------------------------------------------------
    # Resource Requirements
    # -------------------------------------------------------------------------

    required_cores = peewee.IntegerField(default=1)
    required_gpus = peewee.TextField(default="[]")  # JSON array of GPU indices
    required_memory_bytes = peewee.BigIntegerField(null=True)
    target_numa_node_id = peewee.IntegerField(null=True)

    # -------------------------------------------------------------------------
    # Naming (optional user-friendly name)
    # -------------------------------------------------------------------------

    name = peewee.CharField(null=True)  # Optional user-defined name

    # -------------------------------------------------------------------------
    # Ownership (for auth)
    # -------------------------------------------------------------------------

    owner_id = peewee.IntegerField(null=True, index=True)  # References User.id

    # -------------------------------------------------------------------------
    # Approval (for user role tasks)
    # -------------------------------------------------------------------------

    # null = auto-approved (operator/admin), 'pending', 'approved', 'rejected'
    approval_status = peewee.CharField(null=True, index=True)
    approved_by_id = peewee.IntegerField(null=True)  # References User.id
    approved_at = peewee.DateTimeField(null=True)
    rejection_reason = peewee.TextField(null=True)

    # -------------------------------------------------------------------------
    # Assignment and Status
    # -------------------------------------------------------------------------

    status = peewee.CharField(default=TaskStatus.PENDING.value)
    assigned_node = peewee.CharField(null=True, index=True)
    assignment_suspicion_count = peewee.IntegerField(default=0)

    # -------------------------------------------------------------------------
    # Docker Configuration
    # -------------------------------------------------------------------------

    container_name = peewee.CharField(null=True)  # HakuRiver environment name
    registry_image = peewee.CharField(
        null=True
    )  # Docker registry image (e.g. ubuntu:22.04)
    docker_image_name = peewee.CharField(null=True)  # Full image tag
    docker_privileged = peewee.BooleanField(default=False)
    docker_mount_dirs = peewee.TextField(null=True)  # JSON array of mounts

    # -------------------------------------------------------------------------
    # VPS Specific
    # -------------------------------------------------------------------------

    ssh_port = peewee.IntegerField(null=True)

    # -------------------------------------------------------------------------
    # Output Paths
    # -------------------------------------------------------------------------

    stdout_path = peewee.TextField(default="")
    stderr_path = peewee.TextField(default="")

    # -------------------------------------------------------------------------
    # Results
    # -------------------------------------------------------------------------

    exit_code = peewee.IntegerField(null=True)
    error_message = peewee.TextField(null=True)

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------

    submitted_at = peewee.DateTimeField(default=datetime.datetime.now)
    started_at = peewee.DateTimeField(null=True)
    completed_at = peewee.DateTimeField(null=True)

    class Meta:
        table_name = "tasks"

    # =========================================================================
    # JSON Field Accessors
    # =========================================================================

    def get_arguments(self) -> list[str]:
        """Parse arguments JSON to list."""
        if not self.arguments:
            return []
        try:
            return json.loads(self.arguments)
        except json.JSONDecodeError:
            return []

    def set_arguments(self, args: list[str] | None) -> None:
        """Store arguments list as JSON."""
        self.arguments = json.dumps(args or [])

    def get_env_vars(self) -> dict[str, str]:
        """Parse env_vars JSON to dict."""
        if not self.env_vars:
            return {}
        try:
            return json.loads(self.env_vars)
        except json.JSONDecodeError:
            return {}

    def set_env_vars(self, env: dict[str, str] | None) -> None:
        """Store env vars dict as JSON."""
        self.env_vars = json.dumps(env or {})

    def get_required_gpus(self) -> list[int]:
        """Parse required_gpus JSON to list of GPU indices."""
        if not self.required_gpus:
            return []
        try:
            return json.loads(self.required_gpus)
        except json.JSONDecodeError:
            return []

    def set_required_gpus(self, gpus: list[int] | None) -> None:
        """Store GPU indices list as JSON."""
        self.required_gpus = json.dumps(gpus or [])

    def get_docker_mount_dirs(self) -> list[str]:
        """Parse docker_mount_dirs JSON to list."""
        if not self.docker_mount_dirs:
            return []
        try:
            return json.loads(self.docker_mount_dirs)
        except json.JSONDecodeError:
            return []

    def set_docker_mount_dirs(self, mounts: list[str] | None) -> None:
        """Store mount dirs list as JSON."""
        self.docker_mount_dirs = json.dumps(mounts or [])

    # =========================================================================
    # Status Helpers
    # =========================================================================

    def is_pending(self) -> bool:
        """Check if task is pending."""
        return self.status == TaskStatus.PENDING.value

    def is_running(self) -> bool:
        """Check if task is running."""
        return self.status == TaskStatus.RUNNING.value

    def is_paused(self) -> bool:
        """Check if task is paused."""
        return self.status == TaskStatus.PAUSED.value

    def is_finished(self) -> bool:
        """Check if task has finished (completed, failed, killed, etc.)."""
        return self.status in (
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.KILLED.value,
            TaskStatus.KILLED_OOM.value,
            TaskStatus.LOST.value,
            TaskStatus.STOPPED.value,
        )

    def is_vps(self) -> bool:
        """Check if task is a VPS session."""
        return self.task_type == TaskType.VPS.value

    # =========================================================================
    # Status Transitions
    # =========================================================================

    def mark_running(self, node_hostname: str) -> None:
        """Mark task as running on a node."""
        self.status = TaskStatus.RUNNING.value
        self.assigned_node = node_hostname
        self.started_at = datetime.datetime.now()

    def mark_completed(self, exit_code: int = 0) -> None:
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED.value
        self.exit_code = exit_code
        self.completed_at = datetime.datetime.now()

    def mark_failed(self, error_message: str | None = None, exit_code: int = 1) -> None:
        """Mark task as failed."""
        self.status = TaskStatus.FAILED.value
        self.error_message = error_message
        self.exit_code = exit_code
        self.completed_at = datetime.datetime.now()

    def mark_killed(self, oom: bool = False) -> None:
        """Mark task as killed."""
        self.status = TaskStatus.KILLED_OOM.value if oom else TaskStatus.KILLED.value
        self.completed_at = datetime.datetime.now()

    def mark_lost(self) -> None:
        """Mark task as lost (node went offline)."""
        self.status = TaskStatus.LOST.value
        self.completed_at = datetime.datetime.now()

    def mark_paused(self) -> None:
        """Mark task as paused."""
        self.status = TaskStatus.PAUSED.value

    def mark_resumed(self) -> None:
        """Mark task as running (resumed from pause)."""
        self.status = TaskStatus.RUNNING.value

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self, include_owner: bool = True) -> dict:
        """Convert task to dictionary for API responses."""
        result = {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "batch_id": self.batch_id,
            "name": self.name,
            "owner_id": self.owner_id,
            "owner_username": None,
            "approval_status": self.approval_status,
            "approved_by_id": self.approved_by_id,
            "approved_by_username": None,
            "approved_at": (self.approved_at.isoformat() if self.approved_at else None),
            "rejection_reason": self.rejection_reason,
            "command": self.command,
            "arguments": self.get_arguments(),
            "env_vars": self.get_env_vars(),
            "required_cores": self.required_cores,
            "required_gpus": self.get_required_gpus(),
            "required_memory_bytes": self.required_memory_bytes,
            "target_numa_node_id": self.target_numa_node_id,
            "status": self.status,
            "assigned_node": self.assigned_node,
            "container_name": self.container_name,
            "docker_image_name": self.docker_image_name,
            "docker_privileged": self.docker_privileged,
            "docker_mount_dirs": self.get_docker_mount_dirs(),
            "ssh_port": self.ssh_port,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "submitted_at": (
                self.submitted_at.isoformat() if self.submitted_at else None
            ),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
        }

        # Fetch owner and approver usernames
        if include_owner:
            try:
                from kohakuriver.db.auth import User

                if self.owner_id:
                    user = User.get_or_none(User.id == self.owner_id)
                    if user:
                        result["owner_username"] = user.username

                if self.approved_by_id:
                    approver = User.get_or_none(User.id == self.approved_by_id)
                    if approver:
                        result["approved_by_username"] = approver.username
            except ImportError:
                pass  # Auth module not available (auth disabled)
            except Exception as e:
                # Log other errors but don't fail the whole response
                import logging

                logging.getLogger(__name__).warning(
                    f"Error fetching user info for task {self.task_id}: {e}"
                )

        return result
