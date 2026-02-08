"""
Shared constants, models, and helper functions for filesystem endpoints.

This module is imported by filesystem_ops.py and filesystem_watcher.py.
"""

import asyncio
import contextlib
import os
from datetime import datetime
from typing import Literal

import docker
from docker.errors import APIError as DockerAPIError
from docker.errors import NotFound as DockerNotFound
from fastapi import HTTPException
from pydantic import BaseModel

from kohakuriver.runner.services.vm_ssh import ssh_exec
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# Module-level dependencies (set by app on startup via filesystem.py)
_task_store: TaskStateStore | None = None

VM_CONTAINER_PREFIX = "vm-"


def set_dependencies(task_store: TaskStateStore):
    """Set module dependencies from app startup."""
    global _task_store
    _task_store = task_store


# =============================================================================
# Constants and Configuration
# =============================================================================

# Security: Forbidden paths that cannot be accessed
FORBIDDEN_PATHS = {"/proc", "/sys", "/dev"}

# Limits
MAX_FILE_READ_SIZE = 10 * 1024 * 1024  # 10MB
MAX_DIRECTORY_ENTRIES = 1000
MAX_FILE_WRITE_SIZE = 50 * 1024 * 1024  # 50MB


# =============================================================================
# Request/Response Models
# =============================================================================


class FileEntry(BaseModel):
    """A file or directory entry."""

    name: str
    path: str
    type: Literal["file", "directory", "symlink", "other"]
    size: int = -1  # -1 for directories
    mtime: str  # ISO format timestamp
    permissions: str  # e.g., "rwxr-xr-x"


class ListDirectoryResponse(BaseModel):
    """Response for directory listing."""

    path: str
    entries: list[FileEntry]
    parent: str | None = None


class ReadFileResponse(BaseModel):
    """Response for file read."""

    path: str
    content: str
    encoding: Literal["utf-8", "base64"]
    size: int
    truncated: bool


class WriteFileRequest(BaseModel):
    """Request for file write."""

    path: str
    content: str
    encoding: Literal["utf-8", "base64"] = "utf-8"
    create_parents: bool = True


class WriteFileResponse(BaseModel):
    """Response for file write."""

    path: str
    size: int
    success: bool = True


class MkdirRequest(BaseModel):
    """Request for creating directory."""

    path: str
    parents: bool = True


class RenameRequest(BaseModel):
    """Request for rename/move operation."""

    source: str
    destination: str
    overwrite: bool = False


class FileStatResponse(BaseModel):
    """Response for file stat."""

    path: str
    type: Literal["file", "directory", "symlink", "other"]
    size: int
    mtime: str
    permissions: str
    owner: str | None = None
    is_readable: bool = True
    is_writable: bool = True
    is_binary: bool = False


# =============================================================================
# Helper Functions
# =============================================================================


def _resolve_task_data(task_id: int) -> dict | None:
    """Resolve task_id to task data from task_store."""
    if not _task_store:
        return None
    return _task_store.get_task(task_id)


def _is_vm_task(task_data: dict) -> bool:
    """Check if task is a VM (not Docker)."""
    container_name = task_data.get("container_name", "")
    return container_name.startswith(VM_CONTAINER_PREFIX)


def _validate_path(path: str) -> tuple[bool, str | None]:
    """
    Validate path for security issues.

    Returns (is_valid, error_message).
    """
    if not path:
        return False, "Path cannot be empty"

    if not path.startswith("/"):
        return False, "Path must be absolute (start with /)"

    # Normalize to resolve .. and .
    normalized = os.path.normpath(path)

    # Check for forbidden paths
    for forbidden in FORBIDDEN_PATHS:
        if normalized == forbidden or normalized.startswith(forbidden + "/"):
            return False, f"Access to {forbidden} is forbidden"

    return True, None


def _get_validated_path(path: str) -> str:
    """Validate and normalize path, raising HTTPException on error."""
    is_valid, error = _validate_path(path)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)
    return os.path.normpath(path)


async def _exec_in_container(
    container, cmd: list[str], timeout: int = 30
) -> tuple[int, str, str]:
    """
    Execute a command in container.

    Returns (exit_code, stdout, stderr).
    """

    def _run():
        exec_instance = container.client.api.exec_create(
            container.id,
            cmd=cmd,
            stdout=True,
            stderr=True,
            stdin=False,
            tty=False,
        )
        output = container.client.api.exec_start(
            exec_instance["Id"],
            stream=False,
            demux=True,
        )
        stdout = output[0].decode("utf-8", errors="replace") if output[0] else ""
        stderr = output[1].decode("utf-8", errors="replace") if output[1] else ""
        inspect = container.client.api.exec_inspect(exec_instance["Id"])
        return inspect.get("ExitCode", -1), stdout, stderr

    return await asyncio.to_thread(_run)


async def _exec_in_vm(
    vm_ip: str, cmd: list[str], timeout: int = 30
) -> tuple[int, str, str]:
    """Execute a command in VM via SSH."""
    return await ssh_exec(vm_ip, cmd, timeout=timeout)


@contextlib.asynccontextmanager
async def _exec_context(task_id: int):
    """
    Get an exec function for a task (Docker or VM).

    Yields a callable with signature: (cmd: list[str], timeout: int) -> (exit_code, stdout, stderr)
    Handles Docker client lifecycle automatically.
    """
    task_data = _resolve_task_data(task_id)
    if not task_data:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found on this runner."
        )

    if _is_vm_task(task_data):
        vm_ip = task_data.get("vm_ip")
        if not vm_ip:
            raise HTTPException(
                status_code=500, detail=f"VM {task_id} has no IP address."
            )

        async def vm_exec(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
            return await _exec_in_vm(vm_ip, cmd, timeout)

        yield vm_exec
    else:
        container_name = task_data.get("container_name")
        if not container_name:
            raise HTTPException(
                status_code=404, detail=f"Task {task_id} has no container."
            )

        try:
            client = docker.from_env(timeout=30)
            client.ping()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise HTTPException(status_code=500, detail=f"Docker connection error: {e}")

        try:
            container = client.containers.get(container_name)
            if container.status != "running":
                raise HTTPException(
                    status_code=400,
                    detail=f"Container is not running (status: {container.status}).",
                )
        except DockerNotFound:
            client.close()
            raise HTTPException(status_code=404, detail="Container not found.")
        except DockerAPIError as e:
            client.close()
            raise HTTPException(status_code=500, detail=f"Docker API error: {e}")

        try:

            async def docker_exec(
                cmd: list[str], timeout: int = 30
            ) -> tuple[int, str, str]:
                return await _exec_in_container(container, cmd, timeout)

            yield docker_exec
        finally:
            client.close()


def _parse_ls_output(output: str, base_path: str) -> list[FileEntry]:
    """
    Parse output from ls -la command.

    Supports two formats:
    1. GNU ls with --time-style=+%s:
       drwxr-xr-x 2 root root 4096 1234567890 .
    2. BusyBox ls (no --time-style):
       drwxr-xr-x 2 root root 4096 Nov 29 01:30 .
    """
    entries = []
    lines = output.strip().split("\n")

    for line in lines:
        # Skip total line and empty lines
        if not line or line.startswith("total "):
            continue

        parts = line.split()
        if len(parts) < 6:
            continue

        permissions = parts[0]
        # parts[1] is link count
        # parts[2] is owner
        # parts[3] is group
        size_str = parts[4]

        # Detect format: GNU (epoch) vs BusyBox (month day time)
        # BusyBox: "Nov 29 01:30 filename" or "Nov 29 2024 filename"
        # GNU: "1234567890 filename"
        timestamp_str = parts[5]

        # Check if timestamp is numeric (GNU) or month name (BusyBox)
        if timestamp_str.isdigit() and len(timestamp_str) > 6:
            # GNU format: epoch timestamp
            name = " ".join(parts[6:])
            try:
                timestamp = int(timestamp_str)
                mtime = datetime.fromtimestamp(timestamp).isoformat()
            except (ValueError, OSError):
                mtime = datetime.now().isoformat()
        else:
            # BusyBox format: "Mon DD HH:MM" or "Mon DD YYYY"
            # parts[5] = month, parts[6] = day, parts[7] = time/year
            if len(parts) < 8:
                continue
            name = " ".join(parts[8:])
            # Use current time as fallback since parsing BusyBox dates is complex
            mtime = datetime.now().isoformat()

        # Skip . and ..
        if name in (".", "..") or not name:
            continue

        # Determine type from permissions
        type_char = permissions[0] if permissions else "-"
        if type_char == "d":
            entry_type = "directory"
        elif type_char == "l":
            entry_type = "symlink"
            # Remove symlink target from name (e.g., "link -> target")
            if " -> " in name:
                name = name.split(" -> ")[0]
        elif type_char == "-":
            entry_type = "file"
        else:
            entry_type = "other"

        # Parse size
        try:
            size = int(size_str) if entry_type == "file" else -1
        except ValueError:
            size = -1

        # Build full path
        if base_path == "/":
            full_path = f"/{name}"
        else:
            full_path = f"{base_path}/{name}"

        entries.append(
            FileEntry(
                name=name,
                path=full_path,
                type=entry_type,
                size=size,
                mtime=mtime,
                permissions=permissions[1:] if len(permissions) > 1 else "",
            )
        )

    return entries
