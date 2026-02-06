"""
Filesystem REST API endpoints for task/VPS containers on the Runner.

Provides file browsing and editing capabilities inside Docker containers
via Docker exec commands.

Includes WebSocket endpoint for real-time file system change notifications.
"""

import asyncio
import base64
import contextlib
import os
import shlex
from datetime import datetime
from typing import Literal

import docker
from docker.errors import APIError as DockerAPIError
from docker.errors import NotFound as DockerNotFound
from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Module-level dependencies (set by app on startup)
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
    from kohakuriver.runner.services.vm_ssh import ssh_exec

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


# =============================================================================
# REST Endpoints
# =============================================================================


@router.get("/fs/{task_id}/list", response_model=ListDirectoryResponse)
async def list_directory(
    task_id: int = Path(..., description="Task ID"),
    path: str = Query("/", description="Directory path to list"),
    show_hidden: bool = Query(False, description="Include hidden files"),
):
    """List contents of a directory inside the container or VM."""
    path = _get_validated_path(path)

    async with _exec_context(task_id) as exec_fn:
        # Build ls command - try GNU ls first, fallback to BusyBox compatible
        flags = "-la" if show_hidden else "-lA"

        # Try GNU ls with --time-style first
        cmd = ["ls", flags, "--time-style=+%s", path]
        exit_code, stdout, stderr = await exec_fn(cmd)

        # If --time-style not supported (BusyBox), fallback to basic ls
        if exit_code != 0 and "unrecognized option" in stderr:
            cmd = ["ls", flags, path]
            exit_code, stdout, stderr = await exec_fn(cmd)

        if exit_code != 0:
            if "No such file or directory" in stderr:
                raise HTTPException(status_code=404, detail=f"Path not found: {path}")
            elif "Permission denied" in stderr:
                raise HTTPException(
                    status_code=403, detail=f"Permission denied: {path}"
                )
            elif "Not a directory" in stderr:
                raise HTTPException(status_code=400, detail=f"Not a directory: {path}")
            else:
                raise HTTPException(status_code=500, detail=f"ls failed: {stderr}")

        entries = _parse_ls_output(stdout, path)

        # Limit entries
        if len(entries) > MAX_DIRECTORY_ENTRIES:
            entries = entries[:MAX_DIRECTORY_ENTRIES]
            logger.warning(
                f"Directory listing truncated to {MAX_DIRECTORY_ENTRIES} entries"
            )

        # Calculate parent path
        parent = os.path.dirname(path) if path != "/" else None

        return ListDirectoryResponse(path=path, entries=entries, parent=parent)


@router.get("/fs/{task_id}/read", response_model=ReadFileResponse)
async def read_file(
    task_id: int = Path(..., description="Task ID"),
    path: str = Query(..., description="File path to read"),
    encoding: Literal["utf-8", "base64"] = Query(
        "utf-8", description="Output encoding"
    ),
    limit: int = Query(MAX_FILE_READ_SIZE, description="Max bytes to read"),
):
    """Read contents of a file inside the container or VM."""
    path = _get_validated_path(path)

    # Clamp limit
    limit = min(limit, MAX_FILE_READ_SIZE)

    async with _exec_context(task_id) as exec_fn:
        # First check if it's a file and get size
        # Try GNU stat first, then BusyBox stat
        stat_cmd = ["stat", "--format=%F|%s", path]
        exit_code, stdout, stderr = await exec_fn(stat_cmd)

        # Fallback to BusyBox stat format
        if exit_code != 0 and "unrecognized option" in stderr:
            stat_cmd = ["stat", "-c", "%F|%s", path]
            exit_code, stdout, stderr = await exec_fn(stat_cmd)

        if exit_code != 0:
            if "No such file or directory" in stderr:
                raise HTTPException(status_code=404, detail=f"File not found: {path}")
            elif "Permission denied" in stderr:
                raise HTTPException(
                    status_code=403, detail=f"Permission denied: {path}"
                )
            else:
                raise HTTPException(status_code=500, detail=f"stat failed: {stderr}")

        parts = stdout.strip().split("|")
        file_type = parts[0] if parts else ""
        file_size = int(parts[1]) if len(parts) > 1 else 0

        if "directory" in file_type.lower():
            raise HTTPException(
                status_code=400, detail=f"Cannot read directory: {path}"
            )

        # Read file with size limit
        cmd = ["head", "-c", str(limit), path]
        exit_code, stdout, stderr = await exec_fn(cmd)

        if exit_code != 0:
            raise HTTPException(status_code=500, detail=f"read failed: {stderr}")

        truncated = file_size > limit
        content = stdout
        actual_encoding = encoding

        # If requested encoding is utf-8, try to decode, fallback to base64 if binary
        if encoding == "utf-8":
            try:
                # Check if content is valid UTF-8
                content.encode("utf-8")
            except (UnicodeDecodeError, UnicodeEncodeError):
                # Binary file - use base64
                content = base64.b64encode(stdout.encode("latin-1")).decode("ascii")
                actual_encoding = "base64"
        else:
            # base64 requested
            content = base64.b64encode(stdout.encode("latin-1")).decode("ascii")
            actual_encoding = "base64"

        return ReadFileResponse(
            path=path,
            content=content,
            encoding=actual_encoding,
            size=len(stdout),
            truncated=truncated,
        )


@router.post("/fs/{task_id}/write", response_model=WriteFileResponse)
async def write_file(
    task_id: int = Path(..., description="Task ID"),
    request: WriteFileRequest = ...,
):
    """Write contents to a file inside the container or VM."""
    path = _get_validated_path(request.path)

    # Decode content if base64
    if request.encoding == "base64":
        try:
            content_bytes = base64.b64decode(request.content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 content: {e}")
    else:
        content_bytes = request.content.encode("utf-8")

    # Check size limit
    if len(content_bytes) > MAX_FILE_WRITE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_WRITE_SIZE} bytes.",
        )

    async with _exec_context(task_id) as exec_fn:
        # Create parent directories if requested
        if request.create_parents:
            parent_dir = os.path.dirname(path)
            if parent_dir and parent_dir != "/":
                mkdir_cmd = ["mkdir", "-p", parent_dir]
                exit_code, _, stderr = await exec_fn(mkdir_cmd)
                if exit_code != 0:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to create parent directories: {stderr}",
                    )

        # Write file using base64 for safe transfer
        b64_content = base64.b64encode(content_bytes).decode("ascii")
        escaped_path = shlex.quote(path)

        # Use sh -c with base64 decode and write
        write_cmd = [
            "sh",
            "-c",
            f'echo "{b64_content}" | base64 -d > {escaped_path}',
        ]
        exit_code, stdout, stderr = await exec_fn(write_cmd)

        if exit_code != 0:
            if "Permission denied" in stderr:
                raise HTTPException(
                    status_code=403, detail=f"Permission denied: {path}"
                )
            raise HTTPException(status_code=500, detail=f"Write failed: {stderr}")

        return WriteFileResponse(path=path, size=len(content_bytes), success=True)


@router.post("/fs/{task_id}/mkdir")
async def create_directory(
    task_id: int = Path(..., description="Task ID"),
    request: MkdirRequest = ...,
):
    """Create a directory inside the container or VM."""
    path = _get_validated_path(request.path)

    async with _exec_context(task_id) as exec_fn:
        flags = "-p" if request.parents else ""
        cmd = ["mkdir", flags, path] if flags else ["mkdir", path]

        exit_code, stdout, stderr = await exec_fn(cmd)

        if exit_code != 0:
            if "Permission denied" in stderr:
                raise HTTPException(
                    status_code=403, detail=f"Permission denied: {path}"
                )
            elif "File exists" in stderr:
                raise HTTPException(
                    status_code=409, detail=f"Directory already exists: {path}"
                )
            raise HTTPException(status_code=500, detail=f"mkdir failed: {stderr}")

        return {"message": f"Directory created: {path}", "path": path}


@router.post("/fs/{task_id}/rename")
async def rename_item(
    task_id: int = Path(..., description="Task ID"),
    request: RenameRequest = ...,
):
    """Rename or move a file/directory inside the container or VM."""
    source = _get_validated_path(request.source)
    destination = _get_validated_path(request.destination)

    async with _exec_context(task_id) as exec_fn:
        # Check if destination exists (unless overwrite is true)
        if not request.overwrite:
            check_cmd = ["test", "-e", destination]
            exit_code, _, _ = await exec_fn(check_cmd)
            if exit_code == 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Destination already exists: {destination}",
                )

        cmd = ["mv", source, destination]
        exit_code, stdout, stderr = await exec_fn(cmd)

        if exit_code != 0:
            if "No such file or directory" in stderr:
                raise HTTPException(
                    status_code=404, detail=f"Source not found: {source}"
                )
            elif "Permission denied" in stderr:
                raise HTTPException(status_code=403, detail="Permission denied")
            raise HTTPException(status_code=500, detail=f"rename failed: {stderr}")

        return {
            "message": f"Renamed {source} to {destination}",
            "source": source,
            "destination": destination,
        }


@router.delete("/fs/{task_id}/delete")
async def delete_item(
    task_id: int = Path(..., description="Task ID"),
    path: str = Query(..., description="Path to delete"),
    recursive: bool = Query(False, description="Delete directories recursively"),
):
    """Delete a file or directory inside the container or VM."""
    path = _get_validated_path(path)

    async with _exec_context(task_id) as exec_fn:
        # Use rm with appropriate flags
        if recursive:
            cmd = ["rm", "-rf", path]
        else:
            cmd = ["rm", "-f", path]

        exit_code, stdout, stderr = await exec_fn(cmd)

        if exit_code != 0:
            if "No such file or directory" in stderr:
                raise HTTPException(status_code=404, detail=f"Path not found: {path}")
            elif "Permission denied" in stderr:
                raise HTTPException(
                    status_code=403, detail=f"Permission denied: {path}"
                )
            elif "Is a directory" in stderr:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete directory without recursive flag: {path}",
                )
            raise HTTPException(status_code=500, detail=f"delete failed: {stderr}")

        return {"message": f"Deleted: {path}", "path": path}


@router.get("/fs/{task_id}/stat", response_model=FileStatResponse)
async def stat_file(
    task_id: int = Path(..., description="Task ID"),
    path: str = Query(..., description="Path to stat"),
):
    """Get file/directory metadata inside the container or VM."""
    path = _get_validated_path(path)

    async with _exec_context(task_id) as exec_fn:
        # stat with custom format: type|size|mtime|owner|group|permissions
        # Try GNU stat first, then BusyBox stat
        cmd = ["stat", "--format=%F|%s|%Y|%U|%G|%a", path]
        exit_code, stdout, stderr = await exec_fn(cmd)

        # Fallback to BusyBox stat format
        if exit_code != 0 and "unrecognized option" in stderr:
            cmd = ["stat", "-c", "%F|%s|%Y|%U|%G|%a", path]
            exit_code, stdout, stderr = await exec_fn(cmd)

        if exit_code != 0:
            if "No such file or directory" in stderr:
                raise HTTPException(status_code=404, detail=f"Path not found: {path}")
            elif "Permission denied" in stderr:
                raise HTTPException(
                    status_code=403, detail=f"Permission denied: {path}"
                )
            raise HTTPException(status_code=500, detail=f"stat failed: {stderr}")

        parts = stdout.strip().split("|")
        if len(parts) < 6:
            raise HTTPException(status_code=500, detail="Invalid stat output")

        file_type_str = parts[0].lower()
        size = int(parts[1]) if parts[1] else 0
        mtime_unix = int(parts[2]) if parts[2] else 0
        owner = parts[3]
        # group = parts[4]
        permissions_octal = parts[5]

        # Map file type
        if "directory" in file_type_str:
            file_type = "directory"
        elif "symbolic link" in file_type_str:
            file_type = "symlink"
        elif "regular" in file_type_str or "empty" in file_type_str:
            file_type = "file"
        else:
            file_type = "other"

        # Convert mtime
        try:
            mtime = datetime.fromtimestamp(mtime_unix).isoformat()
        except (ValueError, OSError):
            mtime = datetime.now().isoformat()

        # Convert octal permissions to rwx format
        try:
            perms_int = int(permissions_octal, 8)
            permissions = ""
            for shift in [6, 3, 0]:
                p = (perms_int >> shift) & 7
                permissions += "r" if p & 4 else "-"
                permissions += "w" if p & 2 else "-"
                permissions += "x" if p & 1 else "-"
        except ValueError:
            permissions = permissions_octal

        # Check if binary by looking at file extension
        is_binary = False
        if file_type == "file":
            binary_extensions = {
                ".bin",
                ".exe",
                ".dll",
                ".so",
                ".dylib",
                ".o",
                ".a",
                ".zip",
                ".tar",
                ".gz",
                ".bz2",
                ".xz",
                ".7z",
                ".rar",
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".bmp",
                ".ico",
                ".webp",
                ".mp3",
                ".wav",
                ".ogg",
                ".flac",
                ".mp4",
                ".mkv",
                ".avi",
                ".pdf",
                ".doc",
                ".docx",
                ".xls",
                ".xlsx",
                ".ppt",
                ".pptx",
                ".pyc",
                ".pyo",
                ".class",
                ".jar",
                ".war",
            }
            ext = os.path.splitext(path)[1].lower()
            is_binary = ext in binary_extensions

        return FileStatResponse(
            path=path,
            type=file_type,
            size=size,
            mtime=mtime,
            permissions=permissions,
            owner=owner,
            is_readable=True,  # If we got here, it's readable
            is_writable=True,  # Assume writable (would need more checks)
            is_binary=is_binary,
        )


# =============================================================================
# File System Watcher WebSocket Endpoint
# =============================================================================


async def watch_filesystem_handler(
    websocket: WebSocket,
    task_id: int,
    paths: str = "/shared,/local_temp",
):
    """
    WebSocket handler for real-time filesystem change notifications.

    Called from main app.py with /ws prefix.
    Supports both Docker containers and VMs.

    Uses inotifywait inside the container/VM to monitor file changes.
    Falls back to polling if inotifywait is not available.

    Events sent to client:
    - {"type": "change", "event": "CREATE|MODIFY|DELETE|MOVE", "path": "/path/to/file", "is_dir": bool}
    - {"type": "error", "message": "error description"}
    - {"type": "watching", "paths": ["/path1", "/path2"]}
    """
    await websocket.accept()

    # Resolve task
    task_data = _resolve_task_data(task_id)
    if not task_data:
        await websocket.send_json(
            {"type": "error", "message": f"Task {task_id} not found on this runner."}
        )
        await websocket.close()
        return

    # Parse paths to watch
    watch_paths = [p.strip() for p in paths.split(",") if p.strip()]
    if not watch_paths:
        watch_paths = ["/shared", "/local_temp"]

    if _is_vm_task(task_data):
        vm_ip = task_data.get("vm_ip")
        if not vm_ip:
            await websocket.send_json(
                {"type": "error", "message": f"VM {task_id} has no IP address."}
            )
            await websocket.close()
            return
        await _watch_vm_filesystem(websocket, task_id, vm_ip, watch_paths)
    else:
        await _watch_docker_filesystem(websocket, task_id, task_data, watch_paths)


async def _watch_docker_filesystem(
    websocket: WebSocket,
    task_id: int,
    task_data: dict,
    watch_paths: list[str],
):
    """Watch filesystem changes in a Docker container."""
    container_name = task_data.get("container_name")
    if not container_name:
        await websocket.send_json(
            {"type": "error", "message": f"Task {task_id} has no container."}
        )
        await websocket.close()
        return

    try:
        client = docker.from_env(timeout=30)
        container = client.containers.get(container_name)
        if container.status != "running":
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Container is not running (status: {container.status}).",
                }
            )
            await websocket.close()
            return
    except Exception as e:
        await websocket.send_json(
            {"type": "error", "message": f"Failed to connect to container: {e}"}
        )
        await websocket.close()
        return

    # Validate paths exist
    valid_paths = []
    for path in watch_paths:
        try:
            exit_code, _, _ = await _exec_in_container(
                container, ["test", "-d", path], timeout=5
            )
            if exit_code == 0:
                valid_paths.append(path)
        except Exception:
            pass

    if not valid_paths:
        await websocket.send_json(
            {"type": "error", "message": "No valid paths to watch."}
        )
        await websocket.close()
        client.close()
        return

    logger.info(
        f"[FS Watch] Starting Docker file watcher for task {task_id}, paths: {valid_paths}"
    )

    # Check if inotifywait is available
    exit_code, _, _ = await _exec_in_container(
        container, ["which", "inotifywait"], timeout=5
    )
    use_inotify = exit_code == 0

    if use_inotify:
        await _watch_with_inotify(websocket, container, valid_paths, task_id)
    else:
        await _watch_with_polling(websocket, container, valid_paths, task_id)

    client.close()


async def _watch_vm_filesystem(
    websocket: WebSocket,
    task_id: int,
    vm_ip: str,
    watch_paths: list[str],
):
    """Watch filesystem changes in a VM via SSH."""
    from kohakuriver.runner.services.vm_ssh import ssh_connect, ssh_exec

    # Validate paths exist
    valid_paths = []
    for path in watch_paths:
        try:
            exit_code, _, _ = await ssh_exec(vm_ip, ["test", "-d", path], timeout=5)
            if exit_code == 0:
                valid_paths.append(path)
        except Exception:
            pass

    if not valid_paths:
        await websocket.send_json(
            {"type": "error", "message": "No valid paths to watch."}
        )
        await websocket.close()
        return

    logger.info(
        f"[FS Watch] Starting VM file watcher for task {task_id}, paths: {valid_paths}"
    )

    # Check if inotifywait is available
    exit_code, _, _ = await ssh_exec(vm_ip, ["which", "inotifywait"], timeout=5)
    use_inotify = exit_code == 0

    if use_inotify:
        await _watch_vm_with_inotify(websocket, task_id, vm_ip, valid_paths)
    else:
        await _watch_vm_with_polling(websocket, task_id, vm_ip, valid_paths)


async def _watch_vm_with_inotify(
    websocket: WebSocket,
    task_id: int,
    vm_ip: str,
    paths: list[str],
):
    """Watch filesystem in VM via SSH inotifywait."""
    from kohakuriver.runner.services.vm_ssh import ssh_connect

    conn = None
    process = None

    try:
        conn = await ssh_connect(vm_ip, timeout=15.0)

        # Build inotifywait command
        paths_str = " ".join(shlex.quote(p) for p in paths)
        cmd = (
            f"inotifywait -m -r -e create,modify,delete,move "
            f"--format '%e|%w%f|%:e' {paths_str}"
        )
        process = await conn.create_process(cmd)

        logger.info(f"[FS Watch] Using inotifywait via SSH for VM {task_id}")
        await websocket.send_json(
            {"type": "watching", "paths": paths, "method": "inotify"}
        )

        stop_event = asyncio.Event()

        async def read_output():
            try:
                while not stop_event.is_set():
                    line = await process.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue

                    parts = line.split("|")
                    if len(parts) >= 2:
                        events = parts[0]
                        file_path = parts[1]
                        is_dir = "ISDIR" in events if len(parts) > 2 else False

                        event_type = "MODIFY"
                        if "CREATE" in events:
                            event_type = "CREATE"
                        elif "DELETE" in events:
                            event_type = "DELETE"
                        elif "MOVE" in events:
                            event_type = "MOVE"

                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": event_type,
                                "path": file_path,
                                "is_dir": is_dir,
                            }
                        )
            except asyncio.CancelledError:
                pass
            except Exception as e:
                if not stop_event.is_set():
                    logger.error(f"[FS Watch] VM inotify read error: {e}")

        async def handle_ws():
            try:
                while not stop_event.is_set():
                    try:
                        message = await asyncio.wait_for(
                            websocket.receive_json(), timeout=1.0
                        )
                        if message.get("type") == "ping":
                            await websocket.send_json({"type": "pong"})
                    except asyncio.TimeoutError:
                        continue
            except WebSocketDisconnect:
                pass
            finally:
                stop_event.set()

        read_task = asyncio.create_task(read_output())
        ws_task = asyncio.create_task(handle_ws())
        await asyncio.wait([read_task, ws_task], return_when=asyncio.FIRST_COMPLETED)

    finally:
        if process:
            try:
                process.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    logger.info(f"[FS Watch] Stopped VM inotify watcher for task {task_id}")


async def _watch_vm_with_polling(
    websocket: WebSocket,
    task_id: int,
    vm_ip: str,
    paths: list[str],
    interval: float = 2.0,
):
    """Watch filesystem in VM via SSH polling."""
    from kohakuriver.runner.services.vm_ssh import ssh_exec

    logger.info(
        f"[FS Watch] Using polling via SSH for VM {task_id} (inotifywait not available)"
    )
    await websocket.send_json(
        {"type": "watching", "paths": paths, "method": "polling", "interval": interval}
    )

    file_states: dict[str, dict[str, float]] = {}

    async def get_file_list(path: str) -> dict[str, float]:
        cmd = ["find", path, "-maxdepth", "3", "-printf", r"%p|%T@\n"]
        exit_code, stdout, _ = await ssh_exec(vm_ip, cmd, timeout=30)

        if exit_code != 0:
            cmd = ["find", path, "-maxdepth", "3"]
            exit_code, stdout, _ = await ssh_exec(vm_ip, cmd, timeout=30)
            if exit_code != 0:
                return {}
            return {
                line.strip(): 0 for line in stdout.strip().split("\n") if line.strip()
            }

        result = {}
        for line in stdout.strip().split("\n"):
            if "|" in line:
                file_path, mtime_str = line.rsplit("|", 1)
                try:
                    result[file_path.strip()] = float(mtime_str.strip())
                except ValueError:
                    result[file_path.strip()] = 0
        return result

    async def is_dir(path: str) -> bool:
        exit_code, _, _ = await ssh_exec(vm_ip, ["test", "-d", path], timeout=2)
        return exit_code == 0

    # Get initial state
    for path in paths:
        file_states[path] = await get_file_list(path)

    stop_event = asyncio.Event()

    async def poll_changes():
        while not stop_event.is_set():
            await asyncio.sleep(interval)
            for path in paths:
                try:
                    new_state = await get_file_list(path)
                    old_state = file_states.get(path, {})
                    old_files = set(old_state.keys())
                    new_files = set(new_state.keys())

                    for f in new_files - old_files:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": "CREATE",
                                "path": f,
                                "is_dir": await is_dir(f),
                            }
                        )
                    for f in old_files - new_files:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": "DELETE",
                                "path": f,
                                "is_dir": False,
                            }
                        )
                    for f in old_files & new_files:
                        if old_state[f] != new_state[f]:
                            await websocket.send_json(
                                {
                                    "type": "change",
                                    "event": "MODIFY",
                                    "path": f,
                                    "is_dir": await is_dir(f),
                                }
                            )
                    file_states[path] = new_state
                except Exception as e:
                    logger.warning(f"[FS Watch] VM poll error for {path}: {e}")

    async def handle_ws():
        try:
            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=1.0
                    )
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            stop_event.set()

    try:
        poll_task = asyncio.create_task(poll_changes())
        ws_task = asyncio.create_task(handle_ws())
        await asyncio.wait([poll_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()

    logger.info(f"[FS Watch] Stopped VM polling for task {task_id}")


async def _watch_with_inotify(
    websocket: WebSocket,
    container,
    paths: list[str],
    task_id: int,
):
    """
    Watch filesystem using inotifywait.
    """
    # Build inotifywait command
    # -m: monitor mode (continuous)
    # -r: recursive
    # -e: events to watch
    # --format: output format
    paths_str = " ".join(paths)
    cmd = [
        "inotifywait",
        "-m",
        "-r",
        "-e",
        "create,modify,delete,move",
        "--format",
        "%e|%w%f|%:e",
    ] + paths

    logger.info(f"[FS Watch] Using inotifywait for task {task_id}")

    # Notify client we're watching
    await websocket.send_json({"type": "watching", "paths": paths, "method": "inotify"})

    # Create exec instance for inotifywait
    exec_instance = container.client.api.exec_create(
        container.id,
        cmd=cmd,
        stdout=True,
        stderr=True,
        stdin=False,
        tty=False,
    )

    # Start exec and get socket
    socket_stream = container.client.api.exec_start(
        exec_instance["Id"],
        socket=True,
        stream=True,
        tty=False,
        demux=False,
    )

    if not hasattr(socket_stream, "_sock") or not socket_stream._sock:
        await websocket.send_json(
            {"type": "error", "message": "Failed to get socket for inotifywait."}
        )
        return

    raw_socket = socket_stream._sock
    raw_socket.settimeout(1.0)

    stop_event = asyncio.Event()

    async def read_inotify_output():
        """Read output from inotifywait and send to WebSocket."""
        buffer = ""
        while not stop_event.is_set():
            try:
                data = await asyncio.to_thread(raw_socket.recv, 4096)
                if not data:
                    break

                # Decode and process output
                text = data.decode("utf-8", errors="replace")
                buffer += text

                # Process complete lines
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    # Parse inotifywait output: EVENT|PATH|IS_DIR
                    parts = line.split("|")
                    if len(parts) >= 2:
                        events = parts[0]
                        file_path = parts[1]
                        is_dir = "ISDIR" in events if len(parts) > 2 else False

                        # Map inotify events to our event types
                        event_type = "MODIFY"
                        if "CREATE" in events:
                            event_type = "CREATE"
                        elif "DELETE" in events:
                            event_type = "DELETE"
                        elif "MOVE" in events:
                            event_type = "MOVE"
                        elif "MODIFY" in events:
                            event_type = "MODIFY"

                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": event_type,
                                "path": file_path,
                                "is_dir": is_dir,
                            }
                        )

            except TimeoutError:
                # Check for WebSocket messages during timeout
                continue
            except OSError:
                if stop_event.is_set():
                    break
                raise
            except Exception as e:
                if not stop_event.is_set():
                    logger.error(f"[FS Watch] Error reading inotify: {e}")
                break

    async def handle_websocket_input():
        """Handle incoming WebSocket messages (for close/ping)."""
        try:
            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=1.0
                    )
                    # Handle ping
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            stop_event.set()

    # Run both tasks
    try:
        read_task = asyncio.create_task(read_inotify_output())
        ws_task = asyncio.create_task(handle_websocket_input())

        await asyncio.wait([read_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()
        try:
            raw_socket.close()
        except Exception:
            pass

    logger.info(f"[FS Watch] Stopped watching for task {task_id}")


async def _watch_with_polling(
    websocket: WebSocket,
    container,
    paths: list[str],
    task_id: int,
    interval: float = 2.0,
):
    """
    Watch filesystem using polling (fallback when inotifywait is not available).
    """
    logger.info(
        f"[FS Watch] Using polling for task {task_id} (inotifywait not available)"
    )

    # Notify client we're watching
    await websocket.send_json(
        {"type": "watching", "paths": paths, "method": "polling", "interval": interval}
    )

    # State: path -> {name -> mtime}
    file_states: dict[str, dict[str, float]] = {}

    async def get_file_list(path: str) -> dict[str, float]:
        """Get files and mtimes in a directory."""
        cmd = ["find", path, "-maxdepth", "3", "-printf", "%p|%T@\\n"]
        exit_code, stdout, _ = await _exec_in_container(container, cmd, timeout=30)

        if exit_code != 0:
            # Fallback to simpler command
            cmd = ["find", path, "-maxdepth", "3"]
            exit_code, stdout, _ = await _exec_in_container(container, cmd, timeout=30)
            if exit_code != 0:
                return {}
            # No mtime available, use 0
            return {
                line.strip(): 0 for line in stdout.strip().split("\n") if line.strip()
            }

        result = {}
        for line in stdout.strip().split("\n"):
            if "|" in line:
                file_path, mtime_str = line.rsplit("|", 1)
                try:
                    result[file_path.strip()] = float(mtime_str.strip())
                except ValueError:
                    result[file_path.strip()] = 0
        return result

    # Get initial state
    for path in paths:
        file_states[path] = await get_file_list(path)

    stop_event = asyncio.Event()

    async def poll_changes():
        """Poll for file changes."""
        while not stop_event.is_set():
            await asyncio.sleep(interval)

            for path in paths:
                try:
                    new_state = await get_file_list(path)
                    old_state = file_states.get(path, {})

                    # Find changes
                    old_files = set(old_state.keys())
                    new_files = set(new_state.keys())

                    # Created files
                    for f in new_files - old_files:
                        is_dir = f.endswith("/") or await _is_directory(container, f)
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": "CREATE",
                                "path": f,
                                "is_dir": is_dir,
                            }
                        )

                    # Deleted files
                    for f in old_files - new_files:
                        await websocket.send_json(
                            {
                                "type": "change",
                                "event": "DELETE",
                                "path": f,
                                "is_dir": False,  # Can't know for deleted
                            }
                        )

                    # Modified files
                    for f in old_files & new_files:
                        if old_state[f] != new_state[f]:
                            is_dir = await _is_directory(container, f)
                            await websocket.send_json(
                                {
                                    "type": "change",
                                    "event": "MODIFY",
                                    "path": f,
                                    "is_dir": is_dir,
                                }
                            )

                    file_states[path] = new_state

                except Exception as e:
                    logger.warning(f"[FS Watch] Poll error for {path}: {e}")

    async def handle_websocket_input():
        """Handle incoming WebSocket messages."""
        try:
            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=1.0
                    )
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    continue
        except WebSocketDisconnect:
            pass
        finally:
            stop_event.set()

    # Run both tasks
    try:
        poll_task = asyncio.create_task(poll_changes())
        ws_task = asyncio.create_task(handle_websocket_input())

        await asyncio.wait([poll_task, ws_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()

    logger.info(f"[FS Watch] Stopped polling for task {task_id}")


async def _is_directory(container, path: str) -> bool:
    """Check if path is a directory."""
    try:
        exit_code, _, _ = await _exec_in_container(
            container, ["test", "-d", path], timeout=2
        )
        return exit_code == 0
    except Exception:
        return False
