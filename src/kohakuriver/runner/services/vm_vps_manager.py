"""
VM VPS management service.

Handles VM VPS lifecycle using the qemu package.
Called by vps.py endpoints when vps_backend="qemu".
"""

import asyncio
import datetime
import os

from kohakuriver.models.requests import TaskStatusUpdate
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
        from kohakuriver.qemu import get_vm_capability

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
        gpu_pci_addresses = []
        gpu_by_addr = {g.pci_address: g for g in capability.vfio_gpus}
        requested_gpu_addrs = set()
        if gpu_ids:
            for gpu_id in gpu_ids:
                for vfio_gpu in capability.vfio_gpus:
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
                            elif peer not in gpu_by_addr:
                                # Non-GPU peer endpoint — still needs to be co-bound
                                gpu_pci_addresses.append(peer)
                        break
                else:
                    logger.warning(
                        f"VM VPS {task_id}: GPU {gpu_id} not available for VFIO"
                    )
            # Deduplicate while preserving order
            seen = set()
            deduped = []
            for addr in gpu_pci_addresses:
                if addr not in seen:
                    seen.add(addr)
                    deduped.append(addr)
            gpu_pci_addresses = deduped

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

        # Create VM
        from kohakuriver.qemu import VMCreateOptions, get_qemu_manager

        # Shared filesystem paths (mirror Docker bind mounts)
        shared_host = os.path.join(config.SHARED_DIR, "shared_data")
        local_temp_host = os.path.join(config.LOCAL_TEMP_DIR, str(task_id))
        os.makedirs(local_temp_host, exist_ok=True)

        qemu = get_qemu_manager()
        options = VMCreateOptions(
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

        vm = await qemu.create_vm(options)

        # Start SSH port proxy (so host SSH proxy can reach VM)
        if ssh_port:
            await start_ssh_proxy(task_id, ssh_port, net_info.vm_ip)

        # Store VPS state (include VM-specific fields for recovery)
        task_store[str(task_id)] = {
            "task_id": task_id,
            "container_name": f"vm-{task_id}",
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

        # VM stays in "assigning" until cloud-init completes and the VM agent
        # phones home (mark_vm_ready → _ensure_running_reported).
        # Cloud-init installs packages, NVIDIA drivers (if GPU), then starts
        # the VM agent as the last runcmd step.
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

        # Background: watch for cloud-init completion timeout
        async def _cloud_init_watchdog():
            timeout = 900 if has_gpu else 300  # 15 min for GPU, 5 min otherwise
            try:
                await asyncio.sleep(timeout)
                # Check if VM agent has phoned home
                vm_check = qemu.get_vm(task_id)
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

        asyncio.create_task(_cloud_init_watchdog())

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
        from kohakuriver.qemu import get_qemu_manager

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

        logger.info(f"VM VPS {task_id} stopped")
        return success

    except Exception as e:
        logger.error(f"Failed to stop VM VPS {task_id}: {e}")
        return False


async def restart_vm_vps(task_id: int) -> bool:
    """Restart a VM VPS instance."""
    try:
        from kohakuriver.qemu import get_qemu_manager

        qemu = get_qemu_manager()
        return await qemu.restart_vm(task_id)
    except Exception as e:
        logger.error(f"Failed to restart VM VPS {task_id}: {e}")
        return False


async def get_vm_status(task_id: int) -> dict | None:
    """Get VM status."""
    from kohakuriver.qemu import get_qemu_manager

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
    import time as _time

    from kohakuriver.qemu import get_qemu_manager

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
    from kohakuriver.qemu import get_qemu_manager

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
