"""WebSocket terminal proxy for task/VPS containers on remote runners."""

import asyncio
from urllib.parse import urlparse

import websockets
from fastapi import Path, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


class WebSocketOutputMessage(BaseModel):
    """Model for messages sent TO the client over WebSocket."""

    type: str  # "output" or "error"
    data: str


async def task_terminal_proxy_endpoint(
    websocket: WebSocket,
    task_id: int = Path(..., description="Task or VPS ID to connect to."),
):
    """
    Proxy WebSocket connection to the runner hosting the task/VPS container.

    This endpoint validates the task exists and is running, then proxies
    the WebSocket connection to the appropriate runner.
    """
    await websocket.accept()
    logger.info(f"WebSocket terminal proxy connection accepted for task {task_id}")

    runner_ws = None

    try:
        # 1. Look up task in database
        task = await asyncio.to_thread(Task.get_or_none, Task.task_id == task_id)

        if not task:
            logger.warning(f"Task {task_id} not found for terminal proxy.")
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Task {task_id} not found."
                ).model_dump()
            )
            await websocket.close(code=1008)
            return

        # 2. Validate task type and status
        if task.task_type not in ("vps", "command"):
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error",
                    data=f"Task {task_id} is not a container task (type: {task.task_type}).",
                ).model_dump()
            )
            await websocket.close(code=1008)
            return

        if task.status != "running":
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error",
                    data=f"Task is not running (status: {task.status}).",
                ).model_dump()
            )
            await websocket.close(code=1008)
            return

        # 3. Look up runner node
        if not task.assigned_node:
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Task {task_id} has no assigned node."
                ).model_dump()
            )
            await websocket.close(code=1011)
            return

        node = await asyncio.to_thread(
            Node.get_or_none, Node.hostname == task.assigned_node
        )

        if not node:
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error",
                    data=f"Runner node '{task.assigned_node}' not found.",
                ).model_dump()
            )
            await websocket.close(code=1011)
            return

        if node.status != "online":
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error",
                    data=f"Runner node '{task.assigned_node}' is not online (status: {node.status}).",
                ).model_dump()
            )
            await websocket.close(code=1011)
            return

        # 4. Build runner WebSocket URL from node.url
        # node.url format: "http://192.168.1.101:8001"
        parsed = urlparse(node.url)
        runner_ws_url = f"ws://{parsed.netloc}/ws/task/{task_id}/terminal"

        logger.info(f"Proxying terminal for task {task_id} to {runner_ws_url}")

        # 5. Connect to runner WebSocket
        try:
            runner_ws = await websockets.connect(runner_ws_url)
        except Exception as e:
            logger.error(
                f"Failed to connect to runner WebSocket at {runner_ws_url}: {e}"
            )
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Failed to connect to runner: {e}"
                ).model_dump()
            )
            await websocket.close(code=1011)
            return

        logger.debug(f"Connected to runner WebSocket for task {task_id}")

        # 6. Proxy messages bidirectionally
        async def client_to_runner():
            """Forward messages from client to runner."""
            try:
                while True:
                    msg = await websocket.receive_text()
                    await runner_ws.send(msg)
            except WebSocketDisconnect:
                logger.debug(f"Client WebSocket disconnected for task {task_id}")
            except Exception as e:
                logger.debug(f"Client to runner error for task {task_id}: {e}")

        async def runner_to_client():
            """Forward messages from runner to client."""
            try:
                async for msg in runner_ws:
                    await websocket.send_text(msg)
            except websockets.exceptions.ConnectionClosed:
                logger.debug(f"Runner WebSocket closed for task {task_id}")
            except Exception as e:
                logger.debug(f"Runner to client error for task {task_id}: {e}")

        # Run both forwarding tasks concurrently
        done, pending = await asyncio.wait(
            [
                asyncio.create_task(client_to_runner()),
                asyncio.create_task(runner_to_client()),
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        logger.info(f"Terminal proxy session ended for task {task_id}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected cleanly for task {task_id}")
    except Exception as e:
        logger.exception(f"Unexpected error in terminal proxy for task {task_id}: {e}")
        try:
            await websocket.send_json(
                WebSocketOutputMessage(
                    type="error", data=f"Proxy error: {e}"
                ).model_dump()
            )
        except Exception:
            pass
    finally:
        # Clean up runner WebSocket
        if runner_ws:
            try:
                await runner_ws.close()
            except Exception:
                pass

        # Clean up client WebSocket
        try:
            await websocket.close(code=1000)
        except Exception:
            pass

        logger.debug(f"Terminal proxy cleanup complete for task {task_id}")
