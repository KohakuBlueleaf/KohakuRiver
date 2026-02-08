"""
Filesystem CRUD REST API endpoints for task/VPS containers on the Runner.

Provides file browsing and editing capabilities inside Docker containers and VMs
via Docker exec commands or SSH.
"""

import base64
import os
import shlex
from typing import Literal

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    Query,
)

from kohakuriver.runner.endpoints.filesystem_shared import (
    MAX_DIRECTORY_ENTRIES,
    MAX_FILE_READ_SIZE,
    MAX_FILE_WRITE_SIZE,
    FileStatResponse,
    ListDirectoryResponse,
    MkdirRequest,
    ReadFileResponse,
    RenameRequest,
    WriteFileRequest,
    WriteFileResponse,
    _exec_context,
    _get_validated_path,
    _parse_ls_output,
)
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


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
            raise HTTPException(
                status_code=400, detail=f"Invalid base64 content: {e}"
            ) from e
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
        from datetime import datetime

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
