"""
QEMU/KVM integration for KohakuRiver.

Provides VM management capabilities including:
- VM lifecycle (create, start, stop)
- GPU passthrough via VFIO
- Cloud-init provisioning
- QMP control
"""

from kohakuriver.qemu.capability import (
    GPUInfo,
    VMCapability,
    check_vm_capability,
    detect_nvidia_driver_version,
    get_vm_capability,
)
from kohakuriver.qemu.client import (
    QEMUManager,
    VMCreateOptions,
    VMInstance,
    get_qemu_manager,
)
from kohakuriver.qemu.exceptions import (
    CloudInitError,
    QEMUConnectionError,
    QEMUError,
    VFIOBindError,
    VMCapabilityError,
    VMCreationError,
    VMNotFoundError,
)
from kohakuriver.qemu.naming import (
    VM_PREFIX,
    extract_task_id_from_name,
    vm_instance_dir,
    vm_name,
    vm_root_disk_path,
)
from kohakuriver.qemu import vfio

__all__ = [
    # Client
    "QEMUManager",
    "get_qemu_manager",
    "VMInstance",
    "VMCreateOptions",
    # Capability
    "VMCapability",
    "GPUInfo",
    "check_vm_capability",
    "get_vm_capability",
    "detect_nvidia_driver_version",
    # Exceptions
    "QEMUError",
    "QEMUConnectionError",
    "VMNotFoundError",
    "VMCreationError",
    "VFIOBindError",
    "CloudInitError",
    "VMCapabilityError",
    # Naming
    "VM_PREFIX",
    "vm_name",
    "vm_instance_dir",
    "vm_root_disk_path",
    "extract_task_id_from_name",
    # VFIO module
    "vfio",
]
