"""
Node Management Endpoints.

Handles node registration, heartbeats, and status queries.
Provides the core functionality for cluster node lifecycle management.
"""

import datetime
import json
import re
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Path

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.host.config import config
from kohakuriver.host.services.node_manager import get_all_nodes_status
from kohakuriver.models.requests import HeartbeatRequest, RegisterRequest
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _extract_ip_from_url(url: str) -> str:
    """Extract IP address from a runner URL."""
    parsed = urlparse(url)
    return parsed.hostname or "127.0.0.1"


# =============================================================================
# Node Registration
# =============================================================================


@router.post("/register")
async def register_node(request: RegisterRequest):
    """
    Register a runner node with the host.

    Creates a new node record or updates an existing one.
    Called by runners on startup to join the cluster.

    Returns overlay network configuration if overlay is enabled.
    """
    hostname = request.hostname
    url = request.url
    total_cores = request.total_cores
    numa_topology = request.numa_topology
    gpu_info = request.gpu_info

    logger.info(f"Registering node: {hostname} at {url} with {total_cores} cores")

    # Upsert node record
    node, created = Node.get_or_create(
        hostname=hostname,
        defaults={
            "url": url,
            "total_cores": total_cores,
            "status": "online",
            "last_heartbeat": datetime.datetime.now(),
            "numa_topology": json.dumps(numa_topology) if numa_topology else "{}",
            "gpu_info": json.dumps(gpu_info) if gpu_info else "[]",
        },
    )

    if not created:
        # Update existing node with new information
        node.url = url
        node.total_cores = total_cores
        node.status = "online"
        node.last_heartbeat = datetime.datetime.now()
        if numa_topology:
            node.numa_topology = json.dumps(numa_topology)
        if gpu_info:
            node.gpu_info = json.dumps(gpu_info)
        node.save()
        logger.info(f"Updated existing node: {hostname}")
    else:
        logger.info(f"Created new node: {hostname}")

    # Handle overlay network allocation if enabled
    overlay_info = None
    if config.OVERLAY_ENABLED:
        overlay_info = await _allocate_overlay_for_runner(hostname, url)

    return {
        "message": f"Node {hostname} registered successfully.",
        "created": created,
        "overlay": overlay_info,
    }


async def _allocate_overlay_for_runner(hostname: str, url: str) -> dict | None:
    """
    Allocate overlay network configuration for a runner.

    Returns overlay info dict or None if overlay manager is not available.
    """
    from kohakuriver.host.app import get_overlay_manager

    overlay_manager = get_overlay_manager()
    if not overlay_manager:
        return None

    try:
        physical_ip = _extract_ip_from_url(url)
        allocation = await overlay_manager.allocate_for_runner(hostname, physical_ip)

        overlay_info = {
            "runner_id": allocation.runner_id,
            "overlay_subnet": allocation.subnet,
            "overlay_gateway": allocation.gateway,
            "host_overlay_ip": config.OVERLAY_HOST_IP,
            "host_physical_ip": config.HOST_REACHABLE_ADDRESS,
        }

        logger.info(
            f"Overlay allocated for {hostname}: runner_id={allocation.runner_id}, "
            f"subnet={allocation.subnet}"
        )
        return overlay_info

    except Exception as e:
        logger.error(f"Failed to allocate overlay for {hostname}: {e}")
        return None


# =============================================================================
# Heartbeat Processing
# =============================================================================


@router.put("/heartbeat/{hostname}")
async def heartbeat(hostname: str, request: HeartbeatRequest):
    """
    Receive heartbeat from a runner node.

    Updates node health metrics and reconciles task states.
    Processes killed_tasks and running_tasks for task reconciliation.
    """
    node: Node | None = Node.get_or_none(Node.hostname == hostname)
    if not node:
        logger.warning(f"Heartbeat from unknown node: {hostname}")
        raise HTTPException(
            status_code=404,
            detail=f"Node {hostname} not registered. Please register first.",
        )

    now = datetime.datetime.now()

    # Update heartbeat timestamp and metrics
    _update_node_metrics(node, request, now)

    # Process task reconciliation
    _process_killed_tasks(request.killed_tasks, hostname, now)
    _reconcile_assigning_tasks(request.running_tasks, hostname, now)

    # Mark overlay allocation as active on heartbeat
    if config.OVERLAY_ENABLED:
        await _mark_overlay_active(hostname)

    return {"message": "Heartbeat received"}


async def _mark_overlay_active(hostname: str) -> None:
    """Mark runner's overlay allocation as active on heartbeat."""
    from kohakuriver.host.app import get_overlay_manager

    overlay_manager = get_overlay_manager()
    if overlay_manager:
        await overlay_manager.mark_runner_active(hostname)


def _update_node_metrics(
    node: Node, request: HeartbeatRequest, now: datetime.datetime
) -> None:
    """Update node with heartbeat metrics."""
    node.last_heartbeat = now
    node.cpu_percent = request.cpu_percent
    node.memory_percent = request.memory_percent
    node.memory_used_bytes = request.memory_used_bytes
    node.memory_total_bytes = request.memory_total_bytes
    node.current_avg_temp = request.current_avg_temp
    node.current_max_temp = request.current_max_temp

    if request.gpu_info:
        node.gpu_info = json.dumps(request.gpu_info)

    # Mark as online if it was offline
    if node.status != "online":
        logger.info(f"Node {node.hostname} came back online")
        node.status = "online"

    node.save()


def _process_killed_tasks(
    killed_tasks: list | None, hostname: str, now: datetime.datetime
) -> None:
    """Process killed tasks reported by runner."""
    if not killed_tasks:
        return

    logger.info(f"Heartbeat from {hostname} reported killed tasks: {killed_tasks}")

    terminal_statuses = {
        "completed",
        "failed",
        "killed",
        "lost",
        "killed_oom",
        "stopped",
    }

    for killed_info in killed_tasks:
        task: Task | None = Task.get_or_none(Task.task_id == killed_info.task_id)

        if not task:
            logger.warning(
                f"Runner reported killed task {killed_info.task_id}, but task not found"
            )
            continue

        if task.status in terminal_statuses:
            logger.debug(
                f"Runner reported killed task {killed_info.task_id}, "
                f"but already in terminal state '{task.status}'"
            )
            continue

        # Update task to failed/killed state
        original_status = task.status
        new_status = "killed_oom" if killed_info.reason == "oom" else "failed"

        task.status = new_status
        task.exit_code = -9
        task.error_message = f"Killed by runner: {killed_info.reason}"
        task.completed_at = now
        task.save()

        logger.warning(
            f"Task {killed_info.task_id} on {hostname} marked as '{new_status}' "
            f"(was '{original_status}'): {killed_info.reason}"
        )


def _reconcile_assigning_tasks(
    running_tasks: list[int], hostname: str, now: datetime.datetime
) -> None:
    """Reconcile tasks in 'assigning' state with runner's running tasks."""
    assigning_tasks: list[Task] = list(
        Task.select().where(
            (Task.assigned_node == hostname) & (Task.status == "assigning")
        )
    )

    if not assigning_tasks:
        return

    runner_running_set = set(running_tasks)
    heartbeat_interval = config.HEARTBEAT_INTERVAL_SECONDS

    logger.debug(
        f"Reconciling {len(assigning_tasks)} assigning tasks on {hostname}. "
        f"Runner reports running: {runner_running_set}"
    )

    for task in assigning_tasks:
        if task.task_id in runner_running_set:
            _confirm_task_running(task, hostname, now)
        else:
            _check_task_assignment_timeout(task, hostname, now, heartbeat_interval)


def _confirm_task_running(task: Task, hostname: str, now: datetime.datetime) -> None:
    """Confirm task is running based on runner report."""
    logger.info(
        f"Task {task.task_id} confirmed running by {hostname}. "
        "Updating status from 'assigning' to 'running'"
    )

    task.status = "running"
    if task.started_at is None:
        task.started_at = now
    if task.assignment_suspicion_count > 0:
        task.assignment_suspicion_count = 0
    task.save()


def _check_task_assignment_timeout(
    task: Task, hostname: str, now: datetime.datetime, heartbeat_interval: int
) -> None:
    """Check if assigning task has timed out."""
    time_since_submit = now - task.submitted_at
    timeout_threshold = datetime.timedelta(seconds=heartbeat_interval * 3)

    if time_since_submit <= timeout_threshold:
        return

    if task.assignment_suspicion_count < 2:
        # Increment suspicion counter
        task.assignment_suspicion_count += 1
        task.save()
        logger.warning(
            f"Task {task.task_id} (on {hostname}) still 'assigning' and not reported running. "
            f"Marked as suspect ({task.assignment_suspicion_count})"
        )
    else:
        # Mark as failed after too many suspicions
        task.status = "failed"
        task.error_message = (
            f"Task assignment failed. Runner {hostname} did not confirm start "
            "after multiple checks."
        )
        task.completed_at = now
        task.exit_code = -1
        task.save()
        logger.error(
            f"Task {task.task_id} (on {hostname}) failed assignment. "
            f"Marked as failed (suspect count: {task.assignment_suspicion_count})"
        )


# =============================================================================
# Node Status
# =============================================================================


@router.get("/nodes")
async def get_nodes_status():
    """Get status of all registered nodes."""
    return get_all_nodes_status()


# =============================================================================
# Overlay Network Status
# =============================================================================


@router.get("/overlay/status")
async def get_overlay_status():
    """
    Get overlay network status and allocations.

    Returns:
        - enabled: Whether overlay network is enabled
        - host_ip: Host's IP on the overlay network
        - bridge: Bridge name
        - allocations: List of runner allocations
        - stats: Overlay network statistics
    """
    if not config.OVERLAY_ENABLED:
        return {"enabled": False}

    from kohakuriver.host.app import get_overlay_manager

    overlay_manager = get_overlay_manager()
    if not overlay_manager:
        return {"enabled": True, "error": "Overlay manager not initialized"}

    allocations = await overlay_manager.get_all_allocations()
    stats = await overlay_manager.get_stats()

    return {
        "enabled": True,
        "host_ip": f"{config.OVERLAY_HOST_IP}/{config.OVERLAY_HOST_PREFIX}",
        "bridge": config.OVERLAY_BRIDGE_NAME,
        "allocations": [
            {
                "runner_name": a.runner_name,
                "runner_id": a.runner_id,
                "subnet": a.subnet,
                "gateway": a.gateway,
                "physical_ip": a.physical_ip,
                "is_active": a.is_active,
                "last_used": a.last_used.isoformat(),
                "vxlan_device": a.vxlan_device,
            }
            for a in allocations
        ],
        "stats": stats,
    }


@router.post("/overlay/release/{runner_name}")
async def release_overlay_allocation(runner_name: str = Path(...)):
    """
    Manually release an overlay allocation for a runner.

    WARNING: This will disconnect the runner from the overlay network.
    Use with caution - running containers may lose connectivity.
    """
    if not config.OVERLAY_ENABLED:
        raise HTTPException(status_code=400, detail="Overlay network is not enabled")

    from kohakuriver.host.app import get_overlay_manager

    overlay_manager = get_overlay_manager()
    if not overlay_manager:
        raise HTTPException(status_code=500, detail="Overlay manager not initialized")

    released = await overlay_manager.release_runner(runner_name)
    if released:
        logger.info(f"Released overlay allocation for {runner_name}")
        return {"released": True, "runner_name": runner_name}
    else:
        return {"released": False, "reason": f"No allocation found for {runner_name}"}


@router.post("/overlay/cleanup")
async def cleanup_overlay():
    """
    Force cleanup of all inactive overlay allocations.

    This removes VXLAN tunnels for runners that are not currently active.
    Use with caution - only do this when you're sure no containers need
    the overlay network.
    """
    if not config.OVERLAY_ENABLED:
        raise HTTPException(status_code=400, detail="Overlay network is not enabled")

    from kohakuriver.host.app import get_overlay_manager

    overlay_manager = get_overlay_manager()
    if not overlay_manager:
        raise HTTPException(status_code=500, detail="Overlay manager not initialized")

    cleaned_count = await overlay_manager.cleanup_inactive()
    logger.info(f"Cleaned up {cleaned_count} inactive overlay allocations")
    return {"cleaned_count": cleaned_count}
