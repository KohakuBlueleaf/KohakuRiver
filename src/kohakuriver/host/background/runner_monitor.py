"""
Runner Monitoring Background Task.

Detects dead runners via heartbeat timeouts and marks their tasks as lost.
"""

import asyncio
import datetime

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.host.config import config
from kohakuriver.host.state import get_overlay_manager
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Background Task
# =============================================================================


async def check_dead_runners() -> None:
    """
    Check for runners that have missed heartbeats.

    Runs periodically and marks offline runners and their running tasks as lost.
    Also cleans up orphaned pending tasks that will never be scheduled.
    """
    while True:
        await asyncio.sleep(config.CLEANUP_CHECK_INTERVAL_SECONDS)

        try:
            dead_nodes = _find_dead_nodes()

            for node in dead_nodes:
                _mark_node_offline(node)
                _mark_node_tasks_lost(node)
                # Mark overlay allocation as inactive (not deleted)
                await _mark_overlay_inactive(node.hostname)

            # Clean up orphaned pending tasks (assigned to offline/unknown nodes,
            # or unassigned and stuck too long)
            _cleanup_orphaned_pending_tasks()

        except Exception as e:
            logger.error(f"Error checking dead runners: {e}")


# =============================================================================
# Helper Functions
# =============================================================================


def _find_dead_nodes() -> list[Node]:
    """Find nodes that have missed their heartbeat timeout."""
    timeout_threshold = datetime.datetime.now() - datetime.timedelta(
        seconds=config.HEARTBEAT_INTERVAL_SECONDS * config.HEARTBEAT_TIMEOUT_FACTOR
    )

    return list(
        Node.select().where(
            (Node.status == "online") & (Node.last_heartbeat < timeout_threshold)
        )
    )


def _mark_node_offline(node: Node) -> None:
    """Mark a node as offline."""
    logger.warning(
        f"Runner {node.hostname} missed heartbeat threshold "
        f"(last seen: {node.last_heartbeat}). Marking as offline"
    )
    node.status = "offline"
    node.save()


def _mark_node_tasks_lost(node: Node) -> None:
    """Mark all running/assigning/pending tasks on a node as lost."""
    tasks_to_fail: list[Task] = list(
        Task.select().where(
            (Task.assigned_node == node.hostname)
            & (Task.status.in_(["running", "assigning", "pending"]))
        )
    )

    for task in tasks_to_fail:
        logger.warning(
            f"Marking task {task.task_id} as 'lost' "
            f"because node {node.hostname} went offline"
        )
        task.status = "lost"
        task.error_message = f"Node {node.hostname} went offline (heartbeat timeout)"
        task.completed_at = datetime.datetime.now()
        task.exit_code = -1
        task.save()


def _cleanup_orphaned_pending_tasks() -> None:
    """Clean up pending tasks assigned to offline or unknown nodes.

    Catches two cases:
    1. Tasks assigned to a node that is now offline (not caught by
       _mark_node_tasks_lost because the node was already offline)
    2. Tasks with no assigned node that have been pending too long
       (e.g. no suitable runner was ever found)

    Uses a generous timeout: 10 minutes for assigned tasks,
    30 minutes for unassigned tasks.
    """
    now = datetime.datetime.now()

    # Case 1: Pending tasks assigned to offline nodes
    offline_nodes = set(
        n.hostname for n in Node.select(Node.hostname).where(Node.status == "offline")
    )

    if offline_nodes:
        stale_assigned: list[Task] = list(
            Task.select().where(
                (Task.status == "pending")
                & (Task.assigned_node.in_(list(offline_nodes)))
            )
        )
        for task in stale_assigned:
            task.status = "failed"
            task.error_message = (
                f"Assigned node {task.assigned_node} is offline. "
                "Task cannot be scheduled."
            )
            task.completed_at = now
            task.exit_code = -1
            task.save()
            logger.warning(
                f"Task {task.task_id} pending on offline node "
                f"{task.assigned_node} — marked as failed"
            )

    # Case 2: Unassigned pending tasks stuck too long (30 minutes)
    unassigned_timeout = now - datetime.timedelta(minutes=30)
    stale_unassigned: list[Task] = list(
        Task.select().where(
            (Task.status == "pending")
            & (Task.assigned_node.is_null())
            & (Task.submitted_at < unassigned_timeout)
        )
    )
    for task in stale_unassigned:
        task.status = "failed"
        task.error_message = (
            "Task pending for over 30 minutes without assignment. "
            "No suitable runner was available."
        )
        task.completed_at = now
        task.exit_code = -1
        task.save()
        logger.warning(
            f"Task {task.task_id} unassigned and pending for "
            f"{(now - task.submitted_at).total_seconds():.0f}s — marked as failed"
        )


async def _mark_overlay_inactive(hostname: str) -> None:
    """
    Mark overlay allocation as inactive when runner goes offline.

    Note: We don't delete the allocation - the runner may come back
    and containers may still be running. LRU cleanup happens only
    when all 255 IPs are exhausted.
    """
    if not config.OVERLAY_ENABLED:
        return

    overlay_manager = get_overlay_manager()
    if overlay_manager:
        await overlay_manager.mark_runner_inactive(hostname)
        logger.info(
            f"Marked overlay allocation inactive for offline runner: {hostname}"
        )
