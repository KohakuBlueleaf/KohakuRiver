"""QEMU-related exception classes."""


class QEMUError(Exception):
    """Base exception for QEMU operations."""

    pass


class QEMUConnectionError(QEMUError):
    """Failed to connect to QEMU (QMP socket)."""

    pass


class VMNotFoundError(QEMUError):
    """VM not found."""

    def __init__(self, task_id: int):
        self.task_id = task_id
        super().__init__(f"VM not found: {task_id}")


class VMCreationError(QEMUError):
    """VM creation failed."""

    def __init__(self, message: str, task_id: int):
        self.task_id = task_id
        super().__init__(f"VM {task_id} creation failed: {message}")


class VFIOBindError(QEMUError):
    """VFIO GPU binding failed."""

    def __init__(self, message: str, pci_address: str):
        self.pci_address = pci_address
        super().__init__(f"VFIO bind failed for {pci_address}: {message}")


class CloudInitError(QEMUError):
    """Cloud-init ISO creation failed."""

    pass


class VMCapabilityError(QEMUError):
    """VM capability check failed."""

    pass
