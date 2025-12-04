"""
Heartbeat background task.

Sends periodic heartbeats to the host server.
Matches old core/runner.py behavior for compatibility.
"""

import asyncio
from typing import Callable

import httpx

from kohakuriver.models.requests import HeartbeatKilledTaskInfo, HeartbeatRequest
from kohakuriver.runner.config import config
from kohakuriver.runner.services.resource_monitor import get_gpu_stats, get_system_stats
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# List of killed tasks pending report to host
killed_tasks_pending_report: list[HeartbeatKilledTaskInfo] = []


def report_killed_task(task_id: int, reason: str):
    """Add a killed task to the pending report list."""
    killed_tasks_pending_report.append(
        HeartbeatKilledTaskInfo(task_id=task_id, reason=reason)
    )
    logger.debug(
        f"Task {task_id} added to killed tasks pending report (reason: {reason})"
    )


async def send_heartbeat(
    hostname: str,
    numa_topology: dict | None,
    task_store: TaskStateStore,
    register_callback: Callable,
):
    """
    Send periodic heartbeats to the host.

    Uses PUT /heartbeat/{hostname} to match old API.

    Args:
        hostname: This runner's hostname.
        numa_topology: Detected NUMA topology.
        task_store: Task state store for running tasks.
        register_callback: Callback to re-register if needed.
    """
    global killed_tasks_pending_report
    host_url = f"http://{config.HOST_ADDRESS}:{config.HOST_PORT}"

    while True:
        await asyncio.sleep(config.HEARTBEAT_INTERVAL_SECONDS)

        # Get current running task IDs
        running_task_ids = list(task_store.get_all_task_ids())

        # Copy and clear killed tasks list
        killed_payload = killed_tasks_pending_report.copy()
        killed_tasks_pending_report.clear()

        # Gather resource stats
        stats = get_system_stats()
        gpu_info = get_gpu_stats()

        # Build heartbeat payload (matches old HeartbeatData)
        payload = HeartbeatRequest(
            running_tasks=running_task_ids,
            killed_tasks=killed_payload,
            cpu_percent=stats["cpu_percent"],
            memory_percent=stats["memory_percent"],
            memory_used_bytes=stats["memory_used_bytes"],
            memory_total_bytes=stats["memory_total_bytes"],
            current_avg_temp=stats["current_avg_temp"],
            current_max_temp=stats["current_max_temp"],
            gpu_info=gpu_info,
        )

        try:
            async with httpx.AsyncClient() as client:
                # Use PUT /heartbeat/{hostname} to match old API
                response = await client.put(
                    f"{host_url}/api/heartbeat/{hostname}",
                    json=payload.model_dump(mode="json"),
                    timeout=10.0,
                )
                response.raise_for_status()
                # Success: killed_payload was sent

        except httpx.RequestError as e:
            logger.warning(f"Failed to send heartbeat to host: {e}")
            # Failure: Put the killed tasks back to be reported next time
            if killed_payload:
                killed_tasks_pending_report.extend(killed_payload)
                logger.warning(
                    f"Re-added {len(killed_payload)} killed task reports for next heartbeat."
                )

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"Host rejected heartbeat: {e.response.status_code} - "
                f"{e.response.text}"
            )
            if e.response.status_code == 404:
                logger.warning("Node seems unregistered, attempting to re-register...")
                await register_callback()
            # Failure: Put the killed tasks back
            if killed_payload:
                killed_tasks_pending_report.extend(killed_payload)
                logger.warning(
                    f"Re-added {len(killed_payload)} killed task reports for next heartbeat."
                )

        except Exception as e:
            logger.exception(f"Unexpected error sending heartbeat: {e}")
            # Failure: Put the killed tasks back
            if killed_payload:
                killed_tasks_pending_report.extend(killed_payload)
                logger.warning(
                    f"Re-added {len(killed_payload)} killed task reports for next heartbeat."
                )
