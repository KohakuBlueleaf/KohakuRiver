"""
Task execution endpoints.

Handles task execution, control, and status requests.
"""

import os

from fastapi import APIRouter, BackgroundTasks, HTTPException

from kohakuriver.models.requests import TaskControlRequest, TaskExecuteRequest
from kohakuriver.runner.config import config
from kohakuriver.runner.services.task_executor import (
    execute_task,
    kill_task,
    pause_task,
    resume_task,
)
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# These will be set by the app on startup
task_store = None
numa_topology = None


def set_dependencies(store, topology):
    """Set module dependencies from app startup."""
    global task_store, numa_topology
    task_store = store
    numa_topology = topology


@router.post("/execute")
async def execute_task_endpoint(
    request: TaskExecuteRequest,
    background_tasks: BackgroundTasks,
):
    """Accept and execute a task."""
    task_id = request.task_id

    # Check if already running
    if task_store and task_store.get_task(task_id):
        logger.warning(f"Task {task_id} is already running.")
        raise HTTPException(
            status_code=409,
            detail=f"Task {task_id} is already running on this node.",
        )

    # Check local temp directory
    if not os.path.isdir(config.LOCAL_TEMP_DIR):
        logger.error(f"Local temp directory '{config.LOCAL_TEMP_DIR}' not found.")
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: LOCAL_TEMP_DIR missing on node.",
        )

    logger.info(
        f"Accepted task {task_id}: {request.command} "
        f"Cores: {request.required_cores}, "
        f"Memory: {request.required_memory_bytes // (1024*1024) if request.required_memory_bytes else 'N/A'}MB"
    )

    # Execute in background
    background_tasks.add_task(
        execute_task,
        task_id=task_id,
        command=request.command,
        arguments=request.arguments or [],
        env_vars=request.env_vars or {},
        required_cores=request.required_cores,
        required_gpus=request.required_gpus or [],
        required_memory_bytes=request.required_memory_bytes,
        target_numa_node_id=request.target_numa_node_id,
        container_name=request.container_name,
        working_dir=request.working_dir or "/shared",
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        numa_topology=numa_topology,
        task_store=task_store,
        reserved_ip=request.reserved_ip,
    )

    return {"message": "Task accepted for launch", "task_id": task_id}


@router.post("/kill")
async def kill_task_endpoint(request: TaskControlRequest):
    """Kill a running task."""
    task_id = request.task_id
    container_name = request.container_name
    logger.info(f"Received kill request for task {task_id}, container={container_name}")

    if not task_store or not task_store.get_task(task_id):
        logger.warning(f"Kill request for unknown task {task_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found.",
        )

    success = kill_task(task_id, container_name, task_store)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to kill task {task_id}.",
        )

    return {"message": f"Task {task_id} killed."}


@router.post("/pause")
async def pause_task_endpoint(request: TaskControlRequest):
    """Pause a running task."""
    task_id = request.task_id
    container_name = request.container_name
    logger.info(
        f"Received pause request for task {task_id}, container={container_name}"
    )

    if not task_store or not task_store.get_task(task_id):
        logger.warning(f"Pause request for unknown task {task_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found.",
        )

    success = pause_task(task_id, container_name, task_store)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to pause task {task_id}.",
        )

    return {"message": f"Task {task_id} paused."}


@router.post("/resume")
async def resume_task_endpoint(request: TaskControlRequest):
    """Resume a paused task."""
    task_id = request.task_id
    container_name = request.container_name
    logger.info(
        f"Received resume request for task {task_id}, container={container_name}"
    )

    if not task_store or not task_store.get_task(task_id):
        logger.warning(f"Resume request for unknown task {task_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found.",
        )

    success = resume_task(task_id, container_name, task_store)
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to resume task {task_id}.",
        )

    return {"message": f"Task {task_id} resumed."}
