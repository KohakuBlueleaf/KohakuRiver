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
from kohakuriver.version import __version__

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


def _collect_gpu_stats_with_vm_info() -> list[dict]:
    """Collect GPU stats and merge in VM agent GPU info from QEMU manager.

    Calls get_gpu_stats(), then attempts to merge GPU info reported by
    VM agents (for VFIO-passthrough GPUs) via the QEMU manager's list_vms().

    Returns:
        List of GPU stat dicts, including any VM-reported GPU entries.
    """
    gpu_info = get_gpu_stats()

    try:
        from kohakuriver.qemu import get_qemu_manager

        qemu_mgr = get_qemu_manager()
        for vm in qemu_mgr.list_vms():
            if vm.vm_gpu_info:
                for gpu in vm.vm_gpu_info:
                    gpu["vm_task_id"] = vm.task_id
                gpu_info.extend(vm.vm_gpu_info)
    except ImportError:
        pass  # qemu module not available
    except Exception as e:
        logger.debug(f"Failed to merge VM GPU info: {e}")

    return gpu_info


def _collect_vm_capability() -> tuple[bool, list[dict] | None]:
    """Collect VM capability and serialize VFIO GPU information.

    Attempts to call get_vm_capability() and, if VFIO GPUs are present,
    serializes them into plain dicts for the heartbeat payload.

    Returns:
        Tuple of (vm_capable, vfio_gpus_list). vm_capable is False and
        vfio_gpus_list is None if the qemu module is unavailable or
        capability check fails.
    """
    vm_capable = False
    vfio_gpus: list[dict] | None = None

    try:
        from kohakuriver.qemu import get_vm_capability

        cap = get_vm_capability()
        vm_capable = cap.vm_capable
        if cap.vfio_gpus:
            vfio_gpus = [
                {
                    "gpu_id": g.gpu_id,
                    "pci_address": g.pci_address,
                    "name": g.name,
                    "vendor_id": g.vendor_id,
                    "device_id": g.device_id,
                    "iommu_group": g.iommu_group,
                    "audio_pci": g.audio_pci,
                    "iommu_group_peers": g.iommu_group_peers,
                }
                for g in cap.vfio_gpus
            ]
    except ImportError as e:
        logger.warning(f"QEMU module not available, VM capability disabled: {e}")
    except Exception as e:
        logger.warning(f"VM capability check failed: {e}")

    return vm_capable, vfio_gpus


def _build_heartbeat_payload(
    running_task_ids: list[int],
    killed_payload: list[HeartbeatKilledTaskInfo],
    stats: dict,
    gpu_info: list[dict],
    vm_capable: bool,
    vfio_gpus: list[dict] | None,
) -> HeartbeatRequest:
    """Assemble the HeartbeatRequest from collected data.

    Pure construction function — no side effects.

    Args:
        running_task_ids: Currently running task IDs.
        killed_payload: Killed task reports to include.
        stats: System stats dict from get_system_stats().
        gpu_info: GPU info list (possibly including VM GPU entries).
        vm_capable: Whether this node supports VMs.
        vfio_gpus: Serialized VFIO GPU list, or None.

    Returns:
        Fully constructed HeartbeatRequest.
    """
    return HeartbeatRequest(
        running_tasks=running_task_ids,
        killed_tasks=killed_payload,
        cpu_percent=stats["cpu_percent"],
        memory_percent=stats["memory_percent"],
        memory_used_bytes=stats["memory_used_bytes"],
        memory_total_bytes=stats["memory_total_bytes"],
        current_avg_temp=stats["current_avg_temp"],
        current_max_temp=stats["current_max_temp"],
        gpu_info=gpu_info,
        vm_capable=vm_capable,
        vfio_gpus=vfio_gpus,
        runner_version=__version__,
    )


async def _send_heartbeat_to_host(
    host_url: str,
    hostname: str,
    payload: HeartbeatRequest,
    killed_tasks_pending_report: list[HeartbeatKilledTaskInfo],
    killed_payload: list[HeartbeatKilledTaskInfo],
    register_fn: Callable,
) -> None:
    """Send the heartbeat payload to the host via HTTP PUT.

    Handles three exception types:
    - httpx.HTTPStatusError: logs the rejection; if 404, attempts re-registration.
    - httpx.RequestError: logs the connection failure.
    - Exception: logs unexpected errors.

    On ANY failure, killed tasks from killed_payload are re-queued into
    killed_tasks_pending_report so they are retried on the next heartbeat.

    Args:
        host_url: Base URL of the host server.
        hostname: This runner's hostname.
        payload: The heartbeat request to send.
        killed_tasks_pending_report: The global pending report list (mutated on failure).
        killed_payload: The killed task snapshot for this heartbeat cycle.
        register_fn: Async callback to re-register the node.
    """
    success = False
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
            success = True

    except httpx.HTTPStatusError as e:
        logger.warning(
            f"Host rejected heartbeat: {e.response.status_code} - " f"{e.response.text}"
        )
        if e.response.status_code == 404:
            logger.warning("Node seems unregistered, attempting to re-register...")
            await register_fn()

    except httpx.RequestError as e:
        logger.warning(f"Failed to send heartbeat to host: {e}")

    except Exception as e:
        logger.exception(f"Unexpected error sending heartbeat: {e}")

    finally:
        # Consolidate killed-task re-queue: on any failure, put them back
        if not success and killed_payload:
            killed_tasks_pending_report.extend(killed_payload)
            logger.warning(
                f"Re-added {len(killed_payload)} killed task reports for next heartbeat."
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
        gpu_info = _collect_gpu_stats_with_vm_info()

        # Gather VM capability info
        vm_capable, vfio_gpus = _collect_vm_capability()

        # Build heartbeat payload (matches old HeartbeatData)
        payload = _build_heartbeat_payload(
            running_task_ids, killed_payload, stats, gpu_info, vm_capable, vfio_gpus
        )

        # Send heartbeat to host
        await _send_heartbeat_to_host(
            host_url,
            hostname,
            payload,
            killed_tasks_pending_report,
            killed_payload,
            register_callback,
        )
