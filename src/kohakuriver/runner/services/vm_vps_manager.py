"""
VM VPS management service.

Handles VM VPS lifecycle using the qemu package.
Called by vps.py endpoints when vps_backend="qemu".
"""

import asyncio
import datetime

from kohakuriver.models.requests import TaskStatusUpdate
from kohakuriver.runner.config import config
from kohakuriver.runner.services.task_executor import report_status_to_host
from kohakuriver.runner.services.vm_network_manager import get_vm_network_manager
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
    task_store: TaskStateStore,
) -> dict:
    """
    Create a VM VPS instance.

    Steps:
    1. Report pending status
    2. Check VM capability
    3. Setup network (overlay or NAT -- VMNetworkManager handles both)
    4. Create VM via QEMUManager
    5. Wait for SSH ready
    6. Report running status
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

        # Create VM
        from kohakuriver.qemu import VMCreateOptions, get_qemu_manager

        qemu = get_qemu_manager()
        options = VMCreateOptions(
            task_id=task_id,
            base_image=vm_image,
            cores=cores,
            memory_mb=memory_mb,
            disk_size=disk_size,
            gpu_pci_addresses=gpu_pci_addresses,
            ssh_public_key=ssh_public_key or "",
            vm_ip=net_info.vm_ip,
            tap_device=net_info.tap_device,
            gateway=net_info.gateway,
            prefix_len=net_info.prefix_len,
            dns_servers=net_info.dns_servers,
            runner_url=net_info.runner_url,
        )

        vm = await qemu.create_vm(options)

        # Store VPS state
        task_store.add_task(
            task_id=task_id,
            container_name=f"vm-{task_id}",
            allocated_cores=cores,
            allocated_gpus=gpu_ids or [],
            numa_node=None,
        )

        # Wait for SSH (non-blocking, report running either way)
        ssh_ready = await qemu._wait_for_ssh(
            net_info.vm_ip, timeout=config.VM_SSH_READY_TIMEOUT_SECONDS
        )
        vm.ssh_ready = ssh_ready

        if ssh_ready:
            logger.info(f"VM VPS {task_id}: SSH ready at {net_info.vm_ip}:22")
        else:
            logger.warning(
                f"VM VPS {task_id}: SSH not ready after timeout, "
                "but VM is running. VM agent will phone home when ready."
            )

        # Report running status
        await report_status_to_host(
            TaskStatusUpdate(
                task_id=task_id,
                status="running",
                started_at=start_time,
            )
        )

        return {
            "success": True,
            "vm_ip": net_info.vm_ip,
            "ssh_ready": ssh_ready,
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
    """Process heartbeat from VM agent."""
    from kohakuriver.qemu import get_qemu_manager

    qemu = get_qemu_manager()
    vm = qemu.get_vm(task_id)
    if vm:
        vm.last_heartbeat = payload.get("timestamp", __import__("time").time())
        vm.ssh_ready = True
        logger.debug(f"VM {task_id} heartbeat received")


async def mark_vm_ready(task_id: int) -> None:
    """Mark VM as ready (phone-home callback from cloud-init)."""
    from kohakuriver.qemu import get_qemu_manager

    qemu = get_qemu_manager()
    vm = qemu.get_vm(task_id)
    if vm:
        vm.ssh_ready = True
        logger.info(f"VM {task_id} phone-home: boot complete, SSH ready")
