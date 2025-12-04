"""
Filesystem proxy endpoints for task/VPS containers.

Proxies filesystem REST API requests from the host to the appropriate runner.
"""

import asyncio
import json
from urllib.parse import urlencode, urlparse

import httpx
import websockets
from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response
from pydantic import BaseModel

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Timeout for proxied requests (filesystem operations can be slow for large files)
PROXY_TIMEOUT = 60.0


# =============================================================================
# Request Models (same as runner)
# =============================================================================


class WriteFileRequest(BaseModel):
    """Request for file write."""

    path: str
    content: str
    encoding: str = "utf-8"
    create_parents: bool = True


class MkdirRequest(BaseModel):
    """Request for creating directory."""

    path: str
    parents: bool = True


class RenameRequest(BaseModel):
    """Request for rename/move operation."""

    source: str
    destination: str
    overwrite: bool = False


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_runner_url(task_id: int) -> str:
    """
    Get the runner URL for a task.

    Returns the base URL of the runner hosting the task.
    Raises HTTPException on error.
    """
    # Look up task in database
    task = await asyncio.to_thread(Task.get_or_none, Task.task_id == task_id)

    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found.")

    # Validate task type and status
    if task.task_type not in ("vps", "command"):
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} is not a container task (type: {task.task_type}).",
        )

    if task.status != "running":
        raise HTTPException(
            status_code=400,
            detail=f"Task is not running (status: {task.status}).",
        )

    # Get runner node
    if not task.assigned_node:
        raise HTTPException(
            status_code=500, detail=f"Task {task_id} has no assigned node."
        )

    node = await asyncio.to_thread(
        Node.get_or_none, Node.hostname == task.assigned_node
    )

    if not node:
        raise HTTPException(
            status_code=503,
            detail=f"Runner node '{task.assigned_node}' not found.",
        )

    if node.status != "online":
        raise HTTPException(
            status_code=503,
            detail=f"Runner node '{task.assigned_node}' is not online (status: {node.status}).",
        )

    return node.url


async def _proxy_get(
    task_id: int, endpoint: str, params: dict | None = None
) -> Response:
    """Proxy a GET request to the runner."""
    runner_url = await _get_runner_url(task_id)

    url = f"{runner_url}/api/fs/{task_id}/{endpoint}"
    if params:
        url += "?" + urlencode(params)

    logger.debug(f"Proxying GET to {url}")

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.get(url)

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type"),
            )
    except httpx.RequestError as e:
        logger.error(f"Failed to proxy request to runner: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to connect to runner: {e}")


async def _proxy_post(
    task_id: int, endpoint: str, json_body: dict | None = None
) -> Response:
    """Proxy a POST request to the runner."""
    runner_url = await _get_runner_url(task_id)

    url = f"{runner_url}/api/fs/{task_id}/{endpoint}"

    logger.debug(f"Proxying POST to {url}")

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.post(url, json=json_body)

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type"),
            )
    except httpx.RequestError as e:
        logger.error(f"Failed to proxy request to runner: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to connect to runner: {e}")


async def _proxy_delete(
    task_id: int, endpoint: str, params: dict | None = None
) -> Response:
    """Proxy a DELETE request to the runner."""
    runner_url = await _get_runner_url(task_id)

    url = f"{runner_url}/api/fs/{task_id}/{endpoint}"
    if params:
        url += "?" + urlencode(params)

    logger.debug(f"Proxying DELETE to {url}")

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            response = await client.delete(url)

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type"),
            )
    except httpx.RequestError as e:
        logger.error(f"Failed to proxy request to runner: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to connect to runner: {e}")


# =============================================================================
# REST Proxy Endpoints
# =============================================================================


@router.get("/fs/{task_id}/list")
async def list_directory(
    task_id: int = Path(..., description="Task ID"),
    path: str = Query("/", description="Directory path to list"),
    show_hidden: bool = Query(False, description="Include hidden files"),
):
    """List contents of a directory inside the container (proxied to runner)."""
    params = {"path": path, "show_hidden": str(show_hidden).lower()}
    return await _proxy_get(task_id, "list", params)


@router.get("/fs/{task_id}/read")
async def read_file(
    task_id: int = Path(..., description="Task ID"),
    path: str = Query(..., description="File path to read"),
    encoding: str = Query("utf-8", description="Output encoding"),
    limit: int = Query(10485760, description="Max bytes to read"),
):
    """Read contents of a file inside the container (proxied to runner)."""
    params = {"path": path, "encoding": encoding, "limit": str(limit)}
    return await _proxy_get(task_id, "read", params)


@router.post("/fs/{task_id}/write")
async def write_file(
    task_id: int = Path(..., description="Task ID"),
    request: WriteFileRequest = ...,
):
    """Write contents to a file inside the container (proxied to runner)."""
    return await _proxy_post(task_id, "write", request.model_dump())


@router.post("/fs/{task_id}/mkdir")
async def create_directory(
    task_id: int = Path(..., description="Task ID"),
    request: MkdirRequest = ...,
):
    """Create a directory inside the container (proxied to runner)."""
    return await _proxy_post(task_id, "mkdir", request.model_dump())


@router.post("/fs/{task_id}/rename")
async def rename_item(
    task_id: int = Path(..., description="Task ID"),
    request: RenameRequest = ...,
):
    """Rename or move a file/directory inside the container (proxied to runner)."""
    return await _proxy_post(task_id, "rename", request.model_dump())


@router.delete("/fs/{task_id}/delete")
async def delete_item(
    task_id: int = Path(..., description="Task ID"),
    path: str = Query(..., description="Path to delete"),
    recursive: bool = Query(False, description="Delete directories recursively"),
):
    """Delete a file or directory inside the container (proxied to runner)."""
    params = {"path": path, "recursive": str(recursive).lower()}
    return await _proxy_delete(task_id, "delete", params)


@router.get("/fs/{task_id}/stat")
async def stat_file(
    task_id: int = Path(..., description="Task ID"),
    path: str = Query(..., description="Path to stat"),
):
    """Get file/directory metadata inside the container (proxied to runner)."""
    params = {"path": path}
    return await _proxy_get(task_id, "stat", params)


# =============================================================================
# WebSocket Proxy Function for File Watching
# =============================================================================


async def watch_filesystem_proxy(
    websocket: WebSocket,
    task_id: int,
    paths: str = "/shared,/local_temp",
):
    """
    WebSocket proxy for real-time filesystem change notifications.

    Proxies the connection to the runner hosting the task.
    Called from main app.py with /ws prefix.
    """
    await websocket.accept()

    # Get runner URL
    try:
        runner_url = await _get_runner_url(task_id)
    except HTTPException as e:
        await websocket.send_json({"type": "error", "message": e.detail})
        await websocket.close()
        return

    # Convert HTTP URL to WebSocket URL (runner uses /ws prefix)
    parsed = urlparse(runner_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    runner_ws_url = f"{ws_scheme}://{parsed.netloc}/ws/fs/{task_id}/watch?paths={paths}"

    logger.info(f"[FS Watch Proxy] Connecting to runner: {runner_ws_url}")

    try:
        async with websockets.connect(runner_ws_url) as runner_ws:
            # Create tasks for bidirectional message passing
            stop_event = asyncio.Event()

            async def client_to_runner():
                """Forward messages from client to runner."""
                try:
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(
                                websocket.receive_json(), timeout=1.0
                            )
                            await runner_ws.send(json.dumps(message))
                        except asyncio.TimeoutError:
                            continue
                except WebSocketDisconnect:
                    pass
                finally:
                    stop_event.set()

            async def runner_to_client():
                """Forward messages from runner to client."""
                try:
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(
                                runner_ws.recv(), timeout=1.0
                            )
                            data = json.loads(message)
                            await websocket.send_json(data)
                        except asyncio.TimeoutError:
                            continue
                except websockets.exceptions.ConnectionClosed:
                    pass
                except Exception as e:
                    logger.error(f"[FS Watch Proxy] Error forwarding to client: {e}")
                finally:
                    stop_event.set()

            # Run both tasks
            client_task = asyncio.create_task(client_to_runner())
            runner_task = asyncio.create_task(runner_to_client())

            await asyncio.wait(
                [client_task, runner_task], return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel remaining tasks
            stop_event.set()
            tasks_to_cancel = [t for t in [client_task, runner_task] if not t.done()]
            for task in tasks_to_cancel:
                task.cancel()
            if tasks_to_cancel:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    except websockets.exceptions.WebSocketException as e:
        logger.error(f"[FS Watch Proxy] Failed to connect to runner: {e}")
        await websocket.send_json(
            {"type": "error", "message": f"Failed to connect to runner: {e}"}
        )
    except Exception as e:
        logger.error(f"[FS Watch Proxy] Unexpected error: {e}")
        await websocket.send_json({"type": "error", "message": f"Proxy error: {e}"})

    logger.info(f"[FS Watch Proxy] Connection closed for task {task_id}")
