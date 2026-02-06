"""VM naming conventions and utilities."""

import os

# Prefixes
VM_PREFIX = "kohaku-vm"
VM_DISK_PREFIX = "kohaku-vm-disk"

# Labels (for tracking)
LABEL_MANAGED = "kohakuriver.managed"
LABEL_TASK_ID = "kohakuriver.task_id"
LABEL_VM_TYPE = "kohakuriver.vm_type"


def vm_name(task_id: int) -> str:
    """Generate VM name from task ID."""
    return f"{VM_PREFIX}-{task_id}"


def vm_instance_dir(base_dir: str, task_id: int) -> str:
    """Get VM instance directory path."""
    return os.path.join(base_dir, str(task_id))


def vm_root_disk_path(instance_dir: str) -> str:
    """Get root disk path within instance directory."""
    return os.path.join(instance_dir, "root.qcow2")


def vm_cloud_init_path(instance_dir: str) -> str:
    """Get cloud-init ISO path."""
    return os.path.join(instance_dir, "seed.iso")


def vm_qmp_socket_path(task_id: int) -> str:
    """Get QMP socket path."""
    return f"/run/kohakuriver/vm/{task_id}.qmp"


def vm_serial_log_path(instance_dir: str) -> str:
    """Get serial console log path."""
    return os.path.join(instance_dir, "serial.log")


def vm_pidfile_path(instance_dir: str) -> str:
    """Get QEMU PID file path."""
    return os.path.join(instance_dir, "qemu.pid")


def extract_task_id_from_name(name: str) -> int | None:
    """Extract task ID from VM name."""
    if name.startswith(f"{VM_PREFIX}-"):
        try:
            return int(name[len(VM_PREFIX) + 1 :])
        except ValueError:
            return None
    return None
