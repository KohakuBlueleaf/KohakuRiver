"""
Runner Monitoring Background Task.

Detects dead runners via heartbeat timeouts and marks their tasks as lost.
"""

import asyncio
import datetime

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.host.config import config
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Background Task
# =============================================================================


async def check_dead_runners() -> None:
    """
    Check for runners that have missed heartbeats.

    Runs periodically and marks offline runners and their running tasks as lost.
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
    """Mark all running/assigning tasks on a node as lost."""
    tasks_to_fail: list[Task] = list(
        Task.select().where(
            (Task.assigned_node == node.hostname)
            & (Task.status.in_(["running", "assigning"]))
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


async def _mark_overlay_inactive(hostname: str) -> None:
    """
    Mark overlay allocation as inactive when runner goes offline.

    Note: We don't delete the allocation - the runner may come back
    and containers may still be running. LRU cleanup happens only
    when all 255 IPs are exhausted.
    """
    if not config.OVERLAY_ENABLED:
        return

    from kohakuriver.host.app import get_overlay_manager

    overlay_manager = get_overlay_manager()
    if overlay_manager:
        await overlay_manager.mark_runner_inactive(hostname)
        logger.info(
            f"Marked overlay allocation inactive for offline runner: {hostname}"
        )
