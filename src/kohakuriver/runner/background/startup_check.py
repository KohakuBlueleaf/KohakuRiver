"""
Startup check background task.

Verifies running containers and VMs on startup and reports status.
Handles VPS port recovery and VM re-adoption after runner restart.

All Docker operations are wrapped in asyncio.to_thread to prevent blocking.
"""

import asyncio
import datetime
import json
import os
import subprocess

from kohakuriver.docker.client import DockerManager
from kohakuriver.docker.naming import (
    VPS_PREFIX,
    extract_task_id_from_name,
    is_kohakuriver_container,
)
from kohakuriver.models.requests import TaskStatusUpdate
from kohakuriver.qemu import get_qemu_manager, vfio
from kohakuriver.qemu.naming import vm_instance_dir, vm_pidfile_path, vm_qmp_socket_path
from kohakuriver.runner.config import config
from kohakuriver.runner.services.task_executor import report_status_to_host
from kohakuriver.runner.services.vm_network_manager import (
    VMNetworkInfo,
    get_vm_network_manager,
)
from kohakuriver.runner.services.vm_ssh import start_ssh_proxy, stop_ssh_proxy
from kohakuriver.storage.vault import TaskStateStore
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

VM_CONTAINER_PREFIX = "vm-"


def _find_ssh_port(container_name: str) -> int:
    """
    Find the mapped SSH port for a container.

    Returns:
        SSH port number, or 0 if not found (VPS will still work via TTY).
    """
    try:
        result = subprocess.run(
            ["docker", "port", container_name, "22"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Parse: "0.0.0.0:32792\n[::]:32792\n"
        port_mapping = result.stdout.splitlines()[0].strip()
        return int(port_mapping.split(":")[1])
    except subprocess.CalledProcessError:
        logger.warning(
            f"SSH port not available for container '{container_name}'. VPS will work via TTY only."
        )
        return 0
    except (IndexError, ValueError) as e:
        logger.warning(
            f"Failed to parse SSH port for '{container_name}': {e}. VPS will work via TTY only."
        )
        return 0


def _get_running_containers() -> tuple[list, set[str]]:
    """Get running containers (blocking, run in executor)."""
    docker_manager = DockerManager()
    all_running = docker_manager.list_containers(all=False)
    running_container_names = {
        c.name for c in all_running if is_kohakuriver_container(c.name)
    }
    return all_running, running_container_names


def _stop_and_remove_container(container_name: str, timeout: int = 10):
    """Stop and remove container (blocking, run in executor)."""
    docker_manager = DockerManager()
    docker_manager.stop_container(container_name, timeout=timeout)
    docker_manager.remove_container(container_name)


def _is_process_running(pid: int) -> bool:
    """Check if a process is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# =============================================================================
# Persistent VM State Recovery
# =============================================================================


def _restore_vm_state_from_disk(task_store: TaskStateStore) -> None:
    """Scan VM instance directories for persistent vm-state.json files.

    The vault (task_store) lives in LOCAL_TEMP_DIR which may be volatile
    (/tmp). If the vault was wiped (e.g. reboot cleared /tmp), this
    function re-populates it from the JSON state files persisted in
    VM_INSTANCES_DIR (which is on persistent storage).
    """
    instances_dir = config.VM_INSTANCES_DIR
    if not os.path.isdir(instances_dir):
        return

    restored = 0
    for entry in os.listdir(instances_dir):
        instance_dir = os.path.join(instances_dir, entry)
        if not os.path.isdir(instance_dir):
            continue

        state_file = os.path.join(instance_dir, "vm-state.json")
        if not os.path.isfile(state_file):
            continue

        try:
            task_id = int(entry)
        except ValueError:
            continue

        # Skip if already in vault
        if task_store.get_task(task_id) is not None:
            continue

        try:
            with open(state_file) as f:
                vm_data = json.load(f)
            task_store[str(task_id)] = vm_data
            restored += 1
            logger.info(
                f"[VM Recovery] Restored VM {task_id} state from persistent storage"
            )
        except Exception as e:
            logger.warning(f"[VM Recovery] Failed to read VM state for {entry}: {e}")

    if restored:
        logger.info(
            f"[VM Recovery] Restored {restored} VM state(s) from persistent storage"
        )


def _remove_vm_state_file(task_id: int) -> None:
    """Remove the persistent VM state file."""
    instance_dir = vm_instance_dir(config.VM_INSTANCES_DIR, task_id)
    state_file = os.path.join(instance_dir, "vm-state.json")
    try:
        os.unlink(state_file)
    except OSError:
        pass


# =============================================================================
# VM Recovery
# =============================================================================


async def _recover_vm_task(
    task_id: int, task_data: dict, task_store: TaskStateStore
) -> None:
    """
    Recover a VM task on startup.

    If the QEMU daemon is still running (PID from pidfile alive):
    - Re-adopt into QEMUManager
    - Re-register network allocation
    - Report running to host

    If dead:
    - Clean up VFIO GPUs, TAP devices, QMP sockets
    - Report stopped to host
    - Remove from vault
    """
    instance_dir = vm_instance_dir(config.VM_INSTANCES_DIR, task_id)
    pidfile = vm_pidfile_path(instance_dir)

    # Read PID from pidfile
    pid = None
    try:

        def _read_pidfile():
            return int(open(pidfile).read().strip())

        pid = await asyncio.to_thread(_read_pidfile)
    except (FileNotFoundError, ValueError):
        pass

    if pid and _is_process_running(pid):
        # VM is still running — re-adopt
        await _readopt_running_vm(task_id, task_data, task_store)
    else:
        # VM is dead — clean up
        logger.warning(
            f"[VM Recovery] VM {task_id} not running (PID={pid}). Cleaning up."
        )
        await _cleanup_dead_vm(task_id, task_data, task_store)


async def _readopt_running_vm(
    task_id: int, task_data: dict, task_store: TaskStateStore
) -> None:
    """Re-adopt a running VM into QEMUManager and network manager."""
    qemu = get_qemu_manager()
    vm = qemu.recover_vm(task_id, task_data)
    if not vm:
        logger.warning(f"[VM Recovery] Failed to re-adopt VM {task_id}")
        await _cleanup_dead_vm(task_id, task_data, task_store)
        return

    # Re-register network allocation so cleanup works on stop
    net_manager = get_vm_network_manager()
    _recover_network_allocation(net_manager, task_id, task_data)

    # Restart SSH port proxy if ssh_port is known
    ssh_port = task_data.get("ssh_port")
    if ssh_port and vm.vm_ip:
        await start_ssh_proxy(task_id, ssh_port, vm.vm_ip)

    logger.info(f"[VM Recovery] Re-adopted VM {task_id} (PID={vm.pid}, IP={vm.vm_ip})")

    # Report running to host
    await report_status_to_host(
        TaskStatusUpdate(
            task_id=task_id,
            status="running",
            message="VM recovered after runner restart",
        )
    )


def _recover_network_allocation(net_manager, task_id: int, task_data: dict) -> None:
    """Re-register VM network allocation in VMNetworkManager so cleanup works."""
    vm_ip = task_data.get("vm_ip", "")
    if not vm_ip:
        return

    info = VMNetworkInfo(
        tap_device=task_data.get("tap_device", ""),
        mac_address=task_data.get("mac_address", ""),
        vm_ip=vm_ip,
        gateway=task_data.get("gateway", ""),
        bridge_name=task_data.get("bridge_name", ""),
        netmask="",  # Not needed for cleanup
        prefix_len=task_data.get("prefix_len", 24),
        dns_servers=[],
        mode=task_data.get("network_mode", "standard"),
        runner_url="",
    )
    net_manager._allocations[task_id] = info

    # Re-register IP in standard mode pool so it doesn't get double-allocated
    if info.mode == "standard":
        net_manager._used_local_ips.add(vm_ip)


async def _cleanup_dead_vm(
    task_id: int, task_data: dict, task_store: TaskStateStore
) -> None:
    """Clean up a dead VM: unbind VFIO GPUs, remove TAP, report stopped."""
    # Stop SSH proxy if it was running
    try:
        await stop_ssh_proxy(task_id)
    except Exception:
        pass

    # Unbind VFIO GPUs
    gpu_addrs = task_data.get("gpu_pci_addresses", [])
    if gpu_addrs:
        try:
            unbound = set()
            for addr in gpu_addrs:
                if addr not in unbound:
                    try:
                        group_unbound = await vfio.unbind_iommu_group(addr)
                        unbound.update(group_unbound)
                    except Exception as e:
                        logger.warning(
                            f"[VM Recovery] Failed to unbind VFIO for {addr}: {e}"
                        )
        except ImportError:
            pass

    # Delete TAP device
    tap = task_data.get("tap_device", "")
    if tap:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ip",
                "link",
                "del",
                tap,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            logger.info(f"[VM Recovery] Deleted TAP {tap}")
        except Exception:
            pass

    # Clean up QMP socket
    try:
        os.unlink(vm_qmp_socket_path(task_id))
    except OSError:
        pass

    # Report stopped to host
    await report_status_to_host(
        TaskStatusUpdate(
            task_id=task_id,
            status="stopped",
            exit_code=-1,
            message="VM not running on runner startup (runner or machine restarted).",
            completed_at=datetime.datetime.now(),
        )
    )

    # Remove from vault and persistent state file
    task_store.remove_task(task_id)
    _remove_vm_state_file(task_id)
    logger.info(f"[VM Recovery] Cleaned up dead VM {task_id}")


# =============================================================================
# Main Startup Check
# =============================================================================


async def startup_check(task_store: TaskStateStore):
    """
    Check all running containers and VMs on startup and reconcile state.

    This function:
    0. Restore VM state from persistent storage if vault was lost
    1. Gets all tracked tasks from the store
    2. For VM tasks (container_name starts with "vm-"):
       - Check QEMU pidfile, re-adopt if running, cleanup if dead
    3. For Docker tasks:
       - Check if containers are still running
       - Report stopped for missing, recover SSH ports for running VPS
    4. Check for orphan Docker containers
    """
    # Phase 0: Restore VM state from persistent JSON files if vault was wiped
    _restore_vm_state_from_disk(task_store)

    # Separate VM tasks from Docker tasks
    tracked_tasks = list(task_store.items())
    vm_tasks = []
    docker_tasks = []

    for task_id_str, task_data in tracked_tasks:
        container_name = task_data.get("container_name", "")
        if container_name.startswith(VM_CONTAINER_PREFIX):
            vm_tasks.append((int(task_id_str), task_data))
        else:
            docker_tasks.append((int(task_id_str), task_data))

    # --- Phase 1: Recover VM tasks ---
    if vm_tasks:
        logger.info(f"[VM Recovery] Found {len(vm_tasks)} VM task(s) in vault")
        for task_id, task_data in vm_tasks:
            try:
                await _recover_vm_task(task_id, task_data, task_store)
            except Exception as e:
                logger.error(f"[VM Recovery] Error recovering VM {task_id}: {e}")
                # Still try to report stopped and clean up
                try:
                    await _cleanup_dead_vm(task_id, task_data, task_store)
                except Exception:
                    task_store.remove_task(task_id)

    # --- Phase 2: Recover Docker tasks ---
    all_running, running_container_names = await asyncio.to_thread(
        _get_running_containers
    )

    for task_id, task_data in docker_tasks:
        container_name = task_data.get("container_name")

        if container_name not in running_container_names:
            # Container is not running - report as "stopped"
            logger.warning(
                f"Container {container_name} for task {task_id} not found. "
                "Reporting as stopped."
            )

            await report_status_to_host(
                TaskStatusUpdate(
                    task_id=task_id,
                    status="stopped",
                    exit_code=-1,
                    message="Container not found on runner startup (runner may have restarted).",
                    completed_at=datetime.datetime.now(),
                )
            )

            task_store.remove_task(task_id)

        else:
            # Container is still running
            # For VPS containers, recover the SSH port and report to host
            if container_name.startswith(VPS_PREFIX):
                ssh_port = _find_ssh_port(container_name)
                if ssh_port > 0:
                    logger.info(
                        f"VPS container {container_name} for task {task_id} recovered, "
                        f"SSH port: {ssh_port}"
                    )
                else:
                    logger.warning(
                        f"VPS container {container_name} for task {task_id} has no SSH port. "
                        "VPS will work via TTY only."
                    )

                # Report running status to host (host may have marked as "lost" during downtime)
                recovery_message = f"VPS recovered after runner restart" + (
                    "" if ssh_port > 0 else " (TTY-only, no SSH)"
                )
                logger.info(
                    f"[VPS Recovery] Reporting tracked VPS {task_id} as 'running' to host. "
                    f"Message: {recovery_message}"
                )
                await report_status_to_host(
                    TaskStatusUpdate(
                        task_id=task_id,
                        status="running",
                        message=recovery_message,
                        ssh_port=ssh_port if ssh_port > 0 else None,
                    )
                )

            logger.info(
                f"Container {container_name} for task {task_id} is still running."
            )

    # --- Phase 3: Check for orphan Docker containers ---
    for container in all_running:
        if not is_kohakuriver_container(container.name):
            continue

        task_id = extract_task_id_from_name(container.name)
        if task_id is None:
            continue

        task_data = task_store.get_task(task_id)
        if task_data is None:
            # Orphan container
            if container.name.startswith(VPS_PREFIX):
                ssh_port = _find_ssh_port(container.name)
                logger.info(
                    f"Recovering orphan VPS container {container.name} "
                    f"(task_id={task_id}), SSH port: {ssh_port}"
                )

                task_store.add_task(
                    task_id=task_id,
                    container_name=container.name,
                    allocated_cores=None,
                    allocated_gpus=None,
                    numa_node=None,
                )

                recovery_message = f"VPS recovered after runner restart" + (
                    "" if ssh_port > 0 else " (TTY-only, no SSH)"
                )
                await report_status_to_host(
                    TaskStatusUpdate(
                        task_id=task_id,
                        status="running",
                        message=recovery_message,
                        ssh_port=ssh_port if ssh_port > 0 else None,
                    )
                )
            else:
                # Regular task container - clean up
                logger.warning(
                    f"Found orphan task container {container.name} (task_id={task_id}). "
                    "Stopping and removing."
                )
                try:
                    await asyncio.to_thread(
                        _stop_and_remove_container, container.name, 10
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to cleanup orphan container {container.name}: {e}"
                    )
