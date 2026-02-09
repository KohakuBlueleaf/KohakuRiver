"""
VM VPS management service.

Handles VM VPS lifecycle using the qemu package.
Called by vps.py endpoints when vps_backend="qemu".
"""

import asyncio
import datetime
import json
import os
import time as _time

from kohakuriver.models.requests import TaskStatusUpdate
from kohakuriver.qemu import VMCreateOptions, get_qemu_manager, get_vm_capability
from kohakuriver.qemu.capability import GPUInfo
from kohakuriver.qemu.naming import vm_instance_dir
from kohakuriver.runner.config import config
from kohakuriver.runner.services.task_executor import report_status_to_host
from kohakuriver.runner.services.vm_network_manager import get_vm_network_manager
from kohakuriver.runner.services.vm_ssh import (
    get_runner_public_key,
    start_ssh_proxy,
    stop_ssh_proxy,
)
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import format_traceback, get_logger

logger = get_logger(__name__)


def _resolve_gpu_pci_addresses(
    gpu_ids: list[int],
    vfio_gpus: list[GPUInfo],
    task_id: int,
) -> list[str]:
    """Map GPU integer IDs to PCI addresses for VFIO passthrough.

    For each requested GPU ID:
    - Finds the matching VfioGpu object
    - Includes its audio companion device if present
    - Auto-includes co-grouped GPUs sharing the same IOMMU group

    Non-GPU IOMMU peers (PLX DMA, bridges, etc.) are ignored —
    ACS override handles isolation.

    Returns a deduplicated, order-preserving list of PCI addresses.
    """
    gpu_pci_addresses: list[str] = []
    gpu_by_addr = {g.pci_address: g for g in vfio_gpus}
    requested_gpu_addrs: set[str] = set()

    for gpu_id in gpu_ids:
        for vfio_gpu in vfio_gpus:
            if vfio_gpu.gpu_id == gpu_id:
                requested_gpu_addrs.add(vfio_gpu.pci_address)
                gpu_pci_addresses.append(vfio_gpu.pci_address)
                if vfio_gpu.audio_pci:
                    gpu_pci_addresses.append(vfio_gpu.audio_pci)
                # Auto-include IOMMU group peers (other GPUs sharing the group)
                for peer in vfio_gpu.iommu_group_peers:
                    if peer in gpu_by_addr and peer not in requested_gpu_addrs:
                        peer_gpu = gpu_by_addr[peer]
                        logger.info(
                            f"VM VPS {task_id}: GPU {vfio_gpu.pci_address} shares "
                            f"IOMMU group {vfio_gpu.iommu_group} with GPU "
                            f"{peer} — both will be passed through"
                        )
                        requested_gpu_addrs.add(peer)
                        gpu_pci_addresses.append(peer)
                        if peer_gpu.audio_pci:
                            gpu_pci_addresses.append(peer_gpu.audio_pci)
                    # Non-GPU peers (PLX DMA, etc.) are ignored —
                    # ACS override handles IOMMU isolation.
                break
        else:
            logger.warning(f"VM VPS {task_id}: GPU {gpu_id} not available for VFIO")

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for addr in gpu_pci_addresses:
        if addr not in seen:
            seen.add(addr)
            deduped.append(addr)
    return deduped


def _build_vm_create_options(
    task_id: int,
    vm_image: str,
    cores: int,
    memory_mb: int,
    disk_size: str,
    gpu_pci_addresses: list[str],
    ssh_public_key: str | None,
    runner_pubkey: str,
    net_info,
) -> VMCreateOptions:
    """Assemble VMCreateOptions including shared filesystem path setup.

    Creates the local temp directory for the task and builds the full
    options dataclass for QEMUManager.create_vm().
    """
    shared_host = os.path.join(config.SHARED_DIR, "shared_data")
    local_temp_host = os.path.join(config.LOCAL_TEMP_DIR, str(task_id))
    os.makedirs(local_temp_host, exist_ok=True)

    return VMCreateOptions(
        task_id=task_id,
        base_image=vm_image,
        cores=cores,
        memory_mb=memory_mb,
        disk_size=disk_size,
        gpu_pci_addresses=gpu_pci_addresses,
        ssh_public_key=ssh_public_key or "",
        runner_public_key=runner_pubkey,
        mac_address=net_info.mac_address,
        vm_ip=net_info.vm_ip,
        tap_device=net_info.tap_device,
        gateway=net_info.gateway,
        prefix_len=net_info.prefix_len,
        dns_servers=net_info.dns_servers,
        runner_url=net_info.runner_url,
        shared_dir_host=shared_host,
        local_temp_dir_host=local_temp_host,
    )


def _persist_vm_task_state(
    task_store: TaskStateStore,
    task_id: int,
    cores: int,
    gpu_ids: list[int] | None,
    gpu_pci_addresses: list[str],
    net_info,
    ssh_port: int | None,
    container_name: str,
) -> None:
    """Write VPS state to the task store and a persistent JSON file.

    The vault (task_store) may live in /tmp which can be lost on reboot.
    The JSON state file in the VM instance directory (under VM_INSTANCES_DIR)
    is always on persistent storage, enabling recovery even when the vault
    is wiped.
    """
    state_data = {
        "task_id": task_id,
        "container_name": container_name,
        "allocated_cores": cores,
        "allocated_gpus": gpu_ids or [],
        "numa_node": None,
        # VM recovery fields
        "vm_ip": net_info.vm_ip,
        "tap_device": net_info.tap_device,
        "mac_address": net_info.mac_address,
        "gpu_pci_addresses": gpu_pci_addresses,
        "network_mode": net_info.mode,
        "bridge_name": net_info.bridge_name,
        "gateway": net_info.gateway,
        "prefix_len": net_info.prefix_len,
        "ssh_port": ssh_port,
    }
    task_store[str(task_id)] = state_data

    # Also persist to a JSON file in the instance directory
    _write_vm_state_file(task_id, state_data)


def _write_vm_state_file(task_id: int, state_data: dict) -> None:
    """Write VM state to a persistent JSON file in the instance directory."""
    instance_dir = vm_instance_dir(config.VM_INSTANCES_DIR, task_id)
    state_file = os.path.join(instance_dir, "vm-state.json")
    try:
        os.makedirs(instance_dir, exist_ok=True)
        with open(state_file, "w") as f:
            json.dump(state_data, f, indent=2)
    except Exception as e:
        logger.warning(f"VM {task_id}: failed to write persistent state file: {e}")


def remove_vm_state_file(task_id: int) -> None:
    """Remove the persistent VM state file."""
    instance_dir = vm_instance_dir(config.VM_INSTANCES_DIR, task_id)
    state_file = os.path.join(instance_dir, "vm-state.json")
    try:
        os.unlink(state_file)
    except OSError:
        pass


async def _cloud_init_watchdog(
    task_id: int,
    qemu_manager,
    has_gpu: bool,
    timeout_minutes: int = 10,
) -> None:
    """Watch for cloud-init completion and fail the task if it times out.

    For GPU VMs the default timeout is 15 minutes (driver install is slow);
    for non-GPU VMs it is 5 minutes. The caller can override via
    *timeout_minutes*, but the has_gpu flag sets the actual timeout used
    internally (15 min vs 5 min), matching the original behaviour.
    """
    timeout = 900 if has_gpu else 300  # 15 min for GPU, 5 min otherwise
    try:
        await asyncio.sleep(timeout)
        # Check if VM agent has phoned home
        vm_check = qemu_manager.get_vm(task_id)
        if vm_check and not vm_check.ssh_ready:
            logger.error(
                f"VM VPS {task_id}: cloud-init did not complete within "
                f"{timeout}s — marking as failed"
            )
            await report_status_to_host(
                TaskStatusUpdate(
                    task_id=task_id,
                    status="failed",
                    message=f"Cloud-init timed out after {timeout}s",
                    completed_at=datetime.datetime.now(),
                )
            )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"VM VPS {task_id}: cloud-init watchdog error: {e}")


async def create_vm_vps(
    task_id: int,
    vm_image: str,
    cores: int,
    memory_mb: int,
    disk_size: str,
    gpu_ids: list[int] | None,
    ssh_public_key: str | None,
    ssh_port: int | None,
    task_store: TaskStateStore,
) -> dict:
    """
    Create a VM VPS instance.

    Steps:
    1. Report pending status
    2. Check VM capability
    3. Setup network (overlay or NAT -- VMNetworkManager handles both)
    4. Create VM via QEMUManager
    5. Wait for cloud-init to complete (phone-home triggers "running")

    The VM stays in "assigning" state while cloud-init runs (apt update,
    NVIDIA driver install, etc.). It is marked "running" only when the
    VM agent phones home, which is the last step in cloud-init runcmd.
    """
    start_time = datetime.datetime.now()

    # Report pending status
    await report_status_to_host(
        TaskStatusUpdate(
            task_id=task_id,
            status="pending",
        )
    )

    try:
        # Check VM capability
        capability = get_vm_capability()
        if not capability.vm_capable:
            error_msg = f"Node is not VM-capable: {'; '.join(capability.errors)}"
            logger.error(f"VM VPS {task_id}: {error_msg}")
            await report_status_to_host(
                TaskStatusUpdate(
                    task_id=task_id,
                    status="failed",
                    message=error_msg,
                    completed_at=datetime.datetime.now(),
                )
            )
            return {"success": False, "error": error_msg}

        # Resolve GPU PCI addresses from GPU IDs
        gpu_pci_addresses = (
            _resolve_gpu_pci_addresses(gpu_ids, capability.vfio_gpus, task_id)
            if gpu_ids
            else []
        )

        # Setup network
        net_manager = get_vm_network_manager()
        net_info = await net_manager.create_vm_network(task_id)
        logger.info(
            f"VM VPS {task_id}: network ready - IP={net_info.vm_ip}, "
            f"mode={net_info.mode}, bridge={net_info.bridge_name}"
        )

        # Get runner public key for VM access
        runner_pubkey = ""
        try:
            runner_pubkey = get_runner_public_key()
        except Exception as e:
            logger.warning(f"VM VPS {task_id}: could not get runner pubkey: {e}")

        # Build VM creation options
        qemu = get_qemu_manager()
        options = _build_vm_create_options(
            task_id=task_id,
            vm_image=vm_image,
            cores=cores,
            memory_mb=memory_mb,
            disk_size=disk_size,
            gpu_pci_addresses=gpu_pci_addresses,
            ssh_public_key=ssh_public_key,
            runner_pubkey=runner_pubkey,
            net_info=net_info,
        )

        # Create VM
        vm = await qemu.create_vm(options)

        # Start SSH port proxy (so host SSH proxy can reach VM)
        if ssh_port:
            await start_ssh_proxy(task_id, ssh_port, net_info.vm_ip)

        # Persist VPS state for recovery and tracking
        _persist_vm_task_state(
            task_store=task_store,
            task_id=task_id,
            cores=cores,
            gpu_ids=gpu_ids,
            gpu_pci_addresses=gpu_pci_addresses,
            net_info=net_info,
            ssh_port=ssh_port,
            container_name=f"vm-{task_id}",
        )

        # Report assigning status while cloud-init provisions the VM
        has_gpu = bool(gpu_pci_addresses)
        if has_gpu:
            provision_msg = "Provisioning VM — installing packages and NVIDIA drivers via cloud-init"
        else:
            provision_msg = "Provisioning VM — installing packages via cloud-init"

        await report_status_to_host(
            TaskStatusUpdate(
                task_id=task_id,
                status="assigning",
                message=provision_msg,
            )
        )
        logger.info(
            f"VM VPS {task_id}: QEMU started, waiting for cloud-init to "
            f"complete (phone-home will mark as running)"
        )

        # Spawn background watchdog for cloud-init timeout
        asyncio.create_task(_cloud_init_watchdog(task_id, qemu, has_gpu))

        return {
            "success": True,
            "vm_ip": net_info.vm_ip,
            "ssh_ready": False,
            "network_mode": net_info.mode,
        }

    except Exception as e:
        error_msg = f"VM VPS creation failed: {e}"
        logger.error(error_msg)
        logger.debug(format_traceback(e))

        # Cleanup network on failure
        try:
            net_manager = get_vm_network_manager()
            await net_manager.cleanup_vm_network(task_id)
        except Exception:
            pass

        await report_status_to_host(
            TaskStatusUpdate(
                task_id=task_id,
                status="failed",
                message=error_msg,
                completed_at=datetime.datetime.now(),
            )
        )

        return {"success": False, "error": error_msg}


async def stop_vm_vps(
    task_id: int,
    task_store: TaskStateStore,
) -> bool:
    """Stop a VM VPS instance."""
    try:
        qemu = get_qemu_manager()

        # Stop VM
        success = await qemu.stop_vm(task_id)

        # Stop SSH port proxy
        await stop_ssh_proxy(task_id)

        # Cleanup network
        net_manager = get_vm_network_manager()
        await net_manager.cleanup_vm_network(task_id)

        # Remove from tracking
        task_store.remove_task(task_id)
        remove_vm_state_file(task_id)

        logger.info(f"VM VPS {task_id} stopped")
        return success

    except Exception as e:
        logger.error(f"Failed to stop VM VPS {task_id}: {e}")
        return False


async def restart_vm_vps(task_id: int) -> bool:
    """Restart a VM VPS instance with proper VFIO GPU reset.

    Performs a full stop → VFIO unbind/rebind → start cycle so that
    NVIDIA drivers inside the guest reinitialize cleanly. The overlay
    disk preserves all filesystem state; cloud-init won't re-run.
    """
    try:
        qemu = get_qemu_manager()
        vm = qemu.get_vm(task_id)
        if not vm:
            logger.error(f"VM VPS {task_id}: not found for restart")
            return False

        # Mark VM as not ready during reboot
        vm.ssh_ready = False
        old_heartbeat = vm.last_heartbeat

        # Full restart with VFIO PCI reset
        success = await qemu.restart_vm(task_id)
        if not success:
            return False

        logger.info(f"VM VPS {task_id}: restarted, waiting for VM agent to come back")

        # Spawn background watchdog to verify VM comes back
        asyncio.create_task(_reboot_watchdog(task_id, qemu, old_heartbeat))

        return True
    except Exception as e:
        logger.error(f"Failed to restart VM VPS {task_id}: {e}")
        return False


async def _reboot_watchdog(
    task_id: int,
    qemu_manager,
    old_heartbeat: float | None,
    timeout_seconds: int = 180,
) -> None:
    """Watch for VM agent heartbeat after reboot.

    Polls every 5 seconds for up to *timeout_seconds* (default 3 min).
    If the VM agent sends a new heartbeat (timestamp > old_heartbeat),
    it marks ssh_ready = True and reports running. If it times out,
    logs a warning but does NOT fail the task (the VM process is still
    alive, it may just be slow to boot).
    """
    try:
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(5)
            vm = qemu_manager.get_vm(task_id)
            if not vm:
                # VM was stopped/deleted during reboot
                return

            # Check for a new heartbeat after the reset
            if vm.last_heartbeat and (
                old_heartbeat is None or vm.last_heartbeat > old_heartbeat
            ):
                vm.ssh_ready = True
                logger.info(f"VM VPS {task_id}: agent heartbeat resumed after reboot")
                return

        # Timeout — VM agent didn't come back
        vm = qemu_manager.get_vm(task_id)
        if vm and not vm.ssh_ready:
            logger.warning(
                f"VM VPS {task_id}: agent did not resume heartbeat within "
                f"{timeout_seconds}s after reboot"
            )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"VM VPS {task_id}: reboot watchdog error: {e}")


async def get_vm_status(task_id: int) -> dict | None:
    """Get VM status."""
    qemu = get_qemu_manager()
    vm = qemu.get_vm(task_id)
    if not vm:
        return None

    return {
        "task_id": vm.task_id,
        "vm_ip": vm.vm_ip,
        "pid": vm.pid,
        "ssh_ready": vm.ssh_ready,
        "created_at": vm.created_at,
        "last_heartbeat": vm.last_heartbeat,
        "gpu_pci_addresses": vm.gpu_pci_addresses,
    }


async def receive_vm_heartbeat(task_id: int, payload: dict) -> None:
    """Process heartbeat from VM agent. Stores GPU and system info for aggregation."""
    qemu = get_qemu_manager()
    vm = qemu.get_vm(task_id)
    if vm:
        first_heartbeat = vm.last_heartbeat is None
        vm.last_heartbeat = payload.get("timestamp", _time.time())
        vm.ssh_ready = True
        # Store VM GPU info for runner heartbeat aggregation
        if payload.get("gpus"):
            vm.vm_gpu_info = payload["gpus"]
        if payload.get("system"):
            vm.vm_system_info = payload["system"]
        logger.debug(f"VM {task_id} heartbeat received (gpus={len(vm.vm_gpu_info)})")

        # On first heartbeat, ensure host knows VM is running
        if first_heartbeat:
            await _ensure_running_reported(task_id, vm.created_at)


async def mark_vm_ready(task_id: int) -> None:
    """Mark VM as ready (phone-home callback from cloud-init).

    This is called when the VM agent starts — the last step in cloud-init
    runcmd, meaning all packages/drivers are installed.
    """
    qemu = get_qemu_manager()
    vm = qemu.get_vm(task_id)
    if vm:
        vm.ssh_ready = True
        logger.info(
            f"VM {task_id} phone-home: cloud-init complete, "
            f"all packages installed, marking as running"
        )
        await _ensure_running_reported(task_id, vm.created_at)


async def _ensure_running_reported(
    task_id: int,
    started_at: float | None = None,
) -> None:
    """Report running status to host. Safe to call multiple times — host ignores
    duplicate running updates for already-running tasks."""
    try:
        start = None
        if started_at:
            start = datetime.datetime.fromtimestamp(started_at)
        await report_status_to_host(
            TaskStatusUpdate(
                task_id=task_id,
                status="running",
                message="",  # Clear provisioning message
                started_at=start or datetime.datetime.now(),
            )
        )
    except Exception as e:
        logger.warning(f"VM {task_id}: failed to report running to host: {e}")
