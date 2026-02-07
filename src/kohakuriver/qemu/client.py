"""
QEMU VM Manager.

Provides high-level VM operations using subprocess-based QEMU management.
Similar to DockerManager but for QEMU/KVM VMs.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from kohakuriver.qemu.exceptions import (
    QEMUConnectionError,
    QEMUError,
    VMCreationError,
    VMNotFoundError,
)
from kohakuriver.qemu.naming import (
    vm_cloud_init_path,
    vm_instance_dir,
    vm_name,
    vm_pidfile_path,
    vm_qmp_socket_path,
    vm_root_disk_path,
    vm_serial_log_path,
)
from kohakuriver.qemu import vfio
from kohakuriver.qemu.capability import detect_nvidia_driver_version
from kohakuriver.qemu.cloud_init import CloudInitConfig, create_cloud_init_iso
from kohakuriver.runner.config import config as runner_config
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class VMInstance:
    """Running VM instance state."""

    task_id: int
    pid: int
    vm_ip: str
    tap_device: str
    gpu_pci_addresses: list[str]
    instance_dir: str
    qmp_socket: str
    created_at: float = field(default_factory=time.time)

    # Runtime state
    ssh_ready: bool = False
    last_heartbeat: float | None = None
    vm_gpu_info: list[dict] = field(default_factory=list)
    vm_system_info: dict = field(default_factory=dict)


@dataclass
class VMCreateOptions:
    """Options for VM creation."""

    task_id: int
    base_image: str
    cores: int
    memory_mb: int
    disk_size: str
    gpu_pci_addresses: list[str]
    ssh_public_key: str
    mac_address: str
    vm_ip: str
    tap_device: str
    gateway: str
    prefix_len: int
    dns_servers: list[str]
    runner_url: str
    runner_public_key: str = ""
    shared_dir_host: str = ""  # Host path for /shared (empty = skip)
    local_temp_dir_host: str = ""  # Host path for /local_temp (empty = skip)


class QEMUManager:
    """
    QEMU VM Manager.

    Provides methods for:
    - VM lifecycle (create, start, stop, restart)
    - QMP control (shutdown, reset, query)
    - Disk management (create overlay disk)
    - Process management
    """

    def __init__(self, config):
        self.config = config
        self._vms: dict[int, VMInstance] = {}
        self._lock = asyncio.Lock()

    # --- VM Lifecycle ---

    async def create_vm(self, options: VMCreateOptions) -> VMInstance:
        """
        Create and start a new VM.

        Steps:
        1. Create instance directory
        2. Create overlay disk from base image
        3. Bind GPUs to VFIO
        4. Generate cloud-init ISO
        5. Build QEMU command
        6. Start QEMU process
        7. Track VM instance
        """
        async with self._lock:
            if options.task_id in self._vms:
                raise VMCreationError("VM already exists", options.task_id)

        instance_dir = vm_instance_dir(self.config.VM_INSTANCES_DIR, options.task_id)
        os.makedirs(instance_dir, exist_ok=True)

        # Create QMP socket directory
        qmp_socket = vm_qmp_socket_path(options.task_id)
        os.makedirs(os.path.dirname(qmp_socket), exist_ok=True)

        try:
            # Step 1: Create overlay disk
            root_disk = vm_root_disk_path(instance_dir)
            base_image_path = os.path.join(
                self.config.VM_IMAGES_DIR, f"{options.base_image}.qcow2"
            )
            if not os.path.exists(base_image_path):
                raise VMCreationError(
                    f"Base image not found: {base_image_path}", options.task_id
                )
            await self._create_overlay_disk(
                base_image_path, root_disk, options.disk_size
            )

            # Detect host NVIDIA driver version BEFORE VFIO binding
            # (binding unbinds GPU from nvidia driver, so detection must happen first)
            nvidia_driver_version = None
            if options.gpu_pci_addresses:
                nvidia_driver_version = detect_nvidia_driver_version()
                if nvidia_driver_version:
                    logger.info(
                        f"VM {options.task_id}: will install NVIDIA driver "
                        f"{nvidia_driver_version} in guest"
                    )

            # Step 2: Bind GPUs to VFIO (group-aware: binds all non-bridge
            # endpoints in each IOMMU group together)
            bound_devices = set()
            for pci_addr in options.gpu_pci_addresses:
                if pci_addr not in bound_devices:
                    group_bound = await vfio.bind_iommu_group(pci_addr)
                    bound_devices.update(group_bound)

            cloud_init_path = vm_cloud_init_path(instance_dir)
            ci_config = CloudInitConfig(
                task_id=options.task_id,
                hostname=vm_name(options.task_id),
                mac_address=options.mac_address,
                vm_ip=options.vm_ip,
                gateway=options.gateway,
                prefix_len=options.prefix_len,
                dns_servers=options.dns_servers,
                ssh_public_key=options.ssh_public_key,
                runner_public_key=options.runner_public_key,
                runner_url=options.runner_url,
                nvidia_driver_version=nvidia_driver_version,
            )
            await create_cloud_init_iso(cloud_init_path, ci_config)

            # Step 4: Build QEMU command
            qemu_cmd = self._build_qemu_command(options, instance_dir)

            # Step 5: Start QEMU process
            # With -daemonize, QEMU forks a daemon child and the parent exits
            # with 0 on success, non-zero on failure. The real daemon PID is
            # written to the pidfile.
            #
            # IMPORTANT: Do NOT use asyncio PIPE here. QEMU -daemonize forks
            # a child that may inherit pipe FDs, preventing EOF and causing
            # communicate() to hang indefinitely. Use file-based stderr instead.
            logger.info(f"Starting VM {options.task_id}: {' '.join(qemu_cmd[:5])}...")
            stderr_path = os.path.join(instance_dir, "qemu_start.err")

            def _start_qemu():
                with open(stderr_path, "w") as err_file:
                    return subprocess.run(
                        qemu_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=err_file,
                        timeout=30,
                    )

            result = await asyncio.to_thread(_start_qemu)
            if result.returncode != 0:
                error = await asyncio.to_thread(
                    lambda: Path(stderr_path).read_text(errors="replace").strip()
                )
                raise VMCreationError(
                    (
                        f"QEMU failed to start: {error}"
                        if error
                        else f"QEMU failed (exit code {result.returncode})"
                    ),
                    options.task_id,
                )

            # Read real daemon PID from pidfile
            pidfile = vm_pidfile_path(instance_dir)
            try:
                pid = int(
                    await asyncio.to_thread(lambda: Path(pidfile).read_text().strip())
                )
            except (FileNotFoundError, ValueError) as e:
                raise VMCreationError(
                    f"QEMU started but cannot read PID file {pidfile}: {e}",
                    options.task_id,
                )

            if not self._is_process_running(pid):
                raise VMCreationError(
                    "QEMU daemon exited immediately after daemonize",
                    options.task_id,
                )

            # Step 6: Track VM instance
            vm = VMInstance(
                task_id=options.task_id,
                pid=pid,
                vm_ip=options.vm_ip,
                tap_device=options.tap_device,
                gpu_pci_addresses=options.gpu_pci_addresses,
                instance_dir=instance_dir,
                qmp_socket=qmp_socket,
            )

            async with self._lock:
                self._vms[options.task_id] = vm

            logger.info(f"VM {options.task_id} started: PID={pid}, IP={options.vm_ip}")
            return vm

        except VMCreationError:
            raise
        except Exception as e:
            # Cleanup on failure
            await self._cleanup_vm_on_error(options)
            raise VMCreationError(str(e), options.task_id)

    async def stop_vm(self, task_id: int, timeout: int = 30) -> bool:
        """
        Stop a VM gracefully.

        Steps:
        1. Send QMP system_powerdown
        2. Wait for process exit (with timeout)
        3. Force kill if needed
        4. Cleanup resources
        """
        vm = self.get_vm(task_id)
        if not vm:
            logger.warning(f"VM {task_id} not found for stop")
            return False

        # Try graceful shutdown via QMP
        try:
            await self.qmp_shutdown(task_id)
        except Exception as e:
            logger.warning(f"QMP shutdown failed for VM {task_id}: {e}")

        # Wait for process to exit
        start = time.time()
        while time.time() - start < timeout:
            if not self._is_process_running(vm.pid):
                break
            await asyncio.sleep(1)

        # Force kill if still running
        if self._is_process_running(vm.pid):
            logger.warning(f"VM {task_id} didn't stop gracefully, force killing")
            try:
                os.kill(vm.pid, signal.SIGKILL)
                await asyncio.sleep(1)
            except OSError:
                pass

        # Cleanup
        await self._cleanup_vm(task_id)
        logger.info(f"VM {task_id} stopped")
        return True

    async def kill_vm(self, task_id: int) -> bool:
        """Force kill a VM immediately."""
        vm = self.get_vm(task_id)
        if not vm:
            return False

        try:
            os.kill(vm.pid, signal.SIGKILL)
        except OSError:
            pass

        await asyncio.sleep(1)
        await self._cleanup_vm(task_id)
        logger.info(f"VM {task_id} killed")
        return True

    async def restart_vm(self, task_id: int) -> bool:
        """Restart VM via QMP system_reset."""
        try:
            await self.qmp_reset(task_id)
            return True
        except Exception as e:
            logger.error(f"Failed to restart VM {task_id}: {e}")
            return False

    # --- VM Queries ---

    def get_vm(self, task_id: int) -> VMInstance | None:
        """Get VM instance by task ID."""
        return self._vms.get(task_id)

    def list_vms(self) -> list[VMInstance]:
        """List all tracked VMs."""
        return list(self._vms.values())

    def vm_exists(self, task_id: int) -> bool:
        """Check if VM exists."""
        return task_id in self._vms

    # --- VM Recovery ---

    def recover_vm(self, task_id: int, vm_data: dict) -> VMInstance | None:
        """
        Re-adopt a running VM from persisted state (startup recovery).

        Reads the daemon PID from pidfile, verifies it's running,
        and re-creates the VMInstance in the tracking dict.

        Args:
            task_id: The task ID.
            vm_data: Persisted task data from KohakuVault.

        Returns:
            VMInstance if recovery succeeded, None otherwise.
        """
        instance_dir = vm_instance_dir(self.config.VM_INSTANCES_DIR, task_id)
        pidfile = vm_pidfile_path(instance_dir)

        try:
            pid = int(Path(pidfile).read_text().strip())
        except (FileNotFoundError, ValueError):
            logger.warning(f"VM {task_id}: no valid pidfile at {pidfile}")
            return None

        if not self._is_process_running(pid):
            logger.warning(f"VM {task_id}: PID {pid} not running")
            return None

        qmp_socket = vm_qmp_socket_path(task_id)
        vm = VMInstance(
            task_id=task_id,
            pid=pid,
            vm_ip=vm_data.get("vm_ip", ""),
            tap_device=vm_data.get("tap_device", ""),
            gpu_pci_addresses=vm_data.get("gpu_pci_addresses", []),
            instance_dir=instance_dir,
            qmp_socket=qmp_socket,
        )
        vm.ssh_ready = True  # If it survived restart, SSH was working

        self._vms[task_id] = vm
        logger.info(f"VM {task_id}: recovered (PID={pid}, IP={vm.vm_ip})")
        return vm

    # --- QMP Control ---

    async def qmp_command(self, task_id: int, command: str, **args) -> dict:
        """Send QMP command to VM."""
        vm = self.get_vm(task_id)
        if not vm:
            raise VMNotFoundError(task_id)

        def _send_qmp():
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.settimeout(5)
                sock.connect(vm.qmp_socket)

                # Read QMP greeting
                sock.recv(4096)

                # Send qmp_capabilities
                sock.sendall(
                    json.dumps({"execute": "qmp_capabilities"}).encode() + b"\n"
                )
                sock.recv(4096)

                # Send actual command
                cmd = {"execute": command}
                if args:
                    cmd["arguments"] = args
                sock.sendall(json.dumps(cmd).encode() + b"\n")
                response = sock.recv(4096)
                return json.loads(response.decode())

            except (ConnectionRefusedError, FileNotFoundError) as e:
                raise QEMUConnectionError(f"Cannot connect to QMP socket: {e}")
            except socket.timeout:
                raise QEMUConnectionError("QMP socket timeout")
            finally:
                sock.close()

        return await asyncio.to_thread(_send_qmp)

    async def qmp_shutdown(self, task_id: int) -> bool:
        """Send graceful shutdown via QMP."""
        try:
            await self.qmp_command(task_id, "system_powerdown")
            return True
        except Exception as e:
            logger.warning(f"QMP shutdown failed for VM {task_id}: {e}")
            return False

    async def qmp_reset(self, task_id: int) -> bool:
        """Send reset via QMP."""
        try:
            await self.qmp_command(task_id, "system_reset")
            return True
        except Exception as e:
            logger.warning(f"QMP reset failed for VM {task_id}: {e}")
            return False

    # --- Internal Helpers ---

    def _build_qemu_command(
        self, options: VMCreateOptions, instance_dir: str
    ) -> list[str]:
        """Build QEMU command line."""
        root_disk = vm_root_disk_path(instance_dir)
        cloud_init_iso = vm_cloud_init_path(instance_dir)
        qmp_socket = vm_qmp_socket_path(options.task_id)
        serial_log = vm_serial_log_path(instance_dir)
        pidfile = vm_pidfile_path(instance_dir)

        # Find OVMF firmware
        ovmf_paths = [
            "/usr/share/OVMF/OVMF_CODE_4M.fd",
            "/usr/share/OVMF/OVMF_CODE.fd",
            "/usr/share/edk2/ovmf/OVMF_CODE.fd",
            "/usr/share/qemu/OVMF_CODE.fd",
        ]
        ovmf_code = None
        for p in ovmf_paths:
            if os.path.exists(p):
                ovmf_code = p
                break

        cmd = [
            "qemu-system-x86_64",
            "-enable-kvm",
            "-machine",
            "q35,accel=kvm",
            "-cpu",
            "host",
            "-smp",
            str(options.cores),
            "-m",
            f"{options.memory_mb}M",
            # Daemonize
            "-daemonize",
            "-pidfile",
            pidfile,
            # UEFI firmware (if available)
        ]

        if ovmf_code:
            cmd.extend(
                [
                    "-drive",
                    f"if=pflash,format=raw,readonly=on,file={ovmf_code}",
                ]
            )

        cmd.extend(
            [
                # Root disk
                "-drive",
                f"file={root_disk},format=qcow2,if=virtio,cache=writeback",
                # Cloud-init ISO
                "-drive",
                f"file={cloud_init_iso},format=raw,if=virtio,media=cdrom,readonly=on",
                # Network: TAP device
                "-netdev",
                f"tap,id=net0,ifname={options.tap_device},script=no,downscript=no",
                "-device",
                f"virtio-net-pci,netdev=net0,mac={options.mac_address}",
                # QMP control socket
                "-qmp",
                f"unix:{qmp_socket},server,nowait",
                # Serial console log
                "-serial",
                f"file:{serial_log}",
                # No display
                "-display",
                "none",
                # VGA (for cloud-init compatibility)
                "-vga",
                "std",
            ]
        )

        # Shared filesystems via virtio-9p
        if options.shared_dir_host:
            cmd.extend(
                [
                    "-fsdev",
                    f"local,id=fs_shared,path={options.shared_dir_host},security_model=passthrough",
                    "-device",
                    "virtio-9p-pci,fsdev=fs_shared,mount_tag=kohaku_shared",
                ]
            )
        if options.local_temp_dir_host:
            cmd.extend(
                [
                    "-fsdev",
                    f"local,id=fs_local,path={options.local_temp_dir_host},security_model=passthrough",
                    "-device",
                    "virtio-9p-pci,fsdev=fs_local,mount_tag=kohaku_local",
                ]
            )

        # GPU passthrough via VFIO — vm_vps_manager already resolves the
        # complete list of PCI addresses (GPUs + audio + IOMMU group peers)
        for pci_addr in options.gpu_pci_addresses:
            cmd.extend(["-device", f"vfio-pci,host={pci_addr}"])

        return cmd

    async def _create_overlay_disk(
        self, base_image: str, output: str, size: str
    ) -> None:
        """Create qcow2 overlay disk."""

        async def _create():
            # Create overlay backed by base image
            proc = await asyncio.create_subprocess_exec(
                "qemu-img",
                "create",
                "-f",
                "qcow2",
                "-b",
                base_image,
                "-F",
                "qcow2",
                output,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise QEMUError(
                    f"Failed to create overlay disk: {stderr.decode(errors='replace')}"
                )

            # Resize if needed
            if size:
                proc = await asyncio.create_subprocess_exec(
                    "qemu-img",
                    "resize",
                    output,
                    size,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logger.warning(
                        f"Failed to resize disk to {size}: {stderr.decode(errors='replace')}"
                    )

        await _create()
        logger.info(f"Created overlay disk: {output} (base={base_image}, size={size})")

    async def _wait_for_ssh(self, vm_ip: str, timeout: int = 120) -> bool:
        """Wait for SSH to become available."""

        def _probe() -> bool:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((vm_ip, 22))
                sock.close()
                return result == 0
            except (socket.error, OSError):
                return False

        start = time.time()
        while time.time() - start < timeout:
            if await asyncio.to_thread(_probe):
                logger.info(f"SSH is ready on {vm_ip}")
                return True
            await asyncio.sleep(3)

        logger.warning(f"SSH not available on {vm_ip} after {timeout}s")
        return False

    async def _cleanup_vm(self, task_id: int) -> None:
        """Cleanup VM resources (GPUs, network, files)."""
        vm = self._vms.pop(task_id, None)
        if not vm:
            return

        # Unbind GPUs from VFIO (group-aware: unbinds all co-bound devices)
        unbound = set()
        for pci_addr in vm.gpu_pci_addresses:
            if pci_addr not in unbound:
                try:
                    group_unbound = await vfio.unbind_iommu_group(pci_addr)
                    unbound.update(group_unbound)
                except Exception as e:
                    logger.warning(f"Failed to unbind IOMMU group for {pci_addr}: {e}")

        # Remove QMP socket
        try:
            os.unlink(vm.qmp_socket)
        except OSError:
            pass

    async def _cleanup_vm_on_error(self, options: VMCreateOptions) -> None:
        """Cleanup resources on VM creation failure."""
        # Unbind GPUs (group-aware)
        unbound = set()
        for pci_addr in options.gpu_pci_addresses:
            if pci_addr not in unbound:
                try:
                    group_unbound = await vfio.unbind_iommu_group(pci_addr)
                    unbound.update(group_unbound)
                except Exception:
                    pass

    def _is_process_running(self, pid: int) -> bool:
        """Check if process is running."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


# --- Global Instance ---

_qemu_manager: QEMUManager | None = None


def get_qemu_manager() -> QEMUManager:
    """Get global QEMUManager instance."""
    global _qemu_manager
    if _qemu_manager is None:
        _qemu_manager = QEMUManager(runner_config)
    return _qemu_manager
