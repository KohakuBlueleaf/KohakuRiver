"""
VFIO GPU binding/unbinding operations.

Handles driver binding for GPU passthrough.
Supports IOMMU group-aware binding: all non-bridge endpoints in a
group must be bound to vfio-pci together (VFIO kernel requirement).
"""

import asyncio
import subprocess
from pathlib import Path

from kohakuriver.qemu.exceptions import VFIOBindError
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


def _write_sysfs(path: str, value: str) -> None:
    """Write to a sysfs file."""
    try:
        with open(path, "w") as f:
            f.write(value)
    except OSError as e:
        raise VFIOBindError(f"Failed to write '{value}' to {path}: {e}", path)


def get_current_driver(pci_address: str) -> str | None:
    """Get current driver bound to PCI device."""
    driver_link = Path(f"/sys/bus/pci/devices/{pci_address}/driver")
    if driver_link.exists():
        try:
            resolved = driver_link.resolve()
            return resolved.name
        except OSError:
            return None
    return None


def is_bound_to_vfio(pci_address: str) -> bool:
    """Check if device is bound to vfio-pci."""
    return get_current_driver(pci_address) == "vfio-pci"


def _get_device_ids(pci_address: str) -> tuple[str, str]:
    """Get vendor and device IDs for a PCI device."""
    try:
        with open(f"/sys/bus/pci/devices/{pci_address}/vendor") as f:
            vendor = f.read().strip()
        with open(f"/sys/bus/pci/devices/{pci_address}/device") as f:
            device = f.read().strip()
        return vendor, device
    except OSError as e:
        raise VFIOBindError(f"Cannot read device IDs: {e}", pci_address)


def _stop_nvidia_persistenced() -> bool:
    """Stop nvidia-persistenced if running. Returns True if it was stopped."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "nvidia-persistenced"],
            capture_output=True,
        )
        if result.returncode != 0:
            return False

        logger.info("Stopping nvidia-persistenced to release GPU fds")
        subprocess.run(
            ["systemctl", "stop", "nvidia-persistenced"],
            capture_output=True,
            timeout=10,
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to stop nvidia-persistenced: {e}")
        return False


def _start_nvidia_persistenced() -> None:
    """Start nvidia-persistenced (will only grab GPUs still bound to nvidia)."""
    try:
        subprocess.run(
            ["systemctl", "start", "nvidia-persistenced"],
            capture_output=True,
            timeout=10,
        )
        logger.info("Restarted nvidia-persistenced")
    except Exception as e:
        logger.warning(f"Failed to restart nvidia-persistenced: {e}")


async def bind_to_vfio(pci_address: str) -> None:
    """
    Unbind GPU from nvidia and bind to vfio-pci.

    Args:
        pci_address: PCI address (e.g., "0000:01:00.0")

    Raises:
        VFIOBindError: If binding fails
    """

    def _bind_sync():
        current = get_current_driver(pci_address)

        if current == "vfio-pci":
            logger.info(f"{pci_address} already bound to vfio-pci")
            return

        vendor, device = _get_device_ids(pci_address)

        # Unbind from current driver
        if current:
            # nvidia-persistenced holds /dev/nvidia* fds open, which blocks
            # the sysfs unbind write indefinitely. Stop it first.
            if current == "nvidia":
                _stop_nvidia_persistenced()

            logger.info(f"Unbinding {pci_address} from {current}")
            unbind_path = f"/sys/bus/pci/devices/{pci_address}/driver/unbind"
            _write_sysfs(unbind_path, pci_address)

        # Set driver override to vfio-pci
        override_path = f"/sys/bus/pci/devices/{pci_address}/driver_override"
        _write_sysfs(override_path, "vfio-pci")

        # Probe to bind the new driver
        _write_sysfs("/sys/bus/pci/drivers_probe", pci_address)

        # Verify binding
        new_driver = get_current_driver(pci_address)
        if new_driver != "vfio-pci":
            raise VFIOBindError(
                f"Expected vfio-pci but got '{new_driver}'", pci_address
            )

        logger.info(f"Successfully bound {pci_address} to vfio-pci")

    await asyncio.to_thread(_bind_sync)


async def unbind_from_vfio(pci_address: str) -> None:
    """
    Unbind GPU from vfio-pci and let kernel rebind default driver.

    Args:
        pci_address: PCI address

    Raises:
        VFIOBindError: If unbinding fails
    """

    def _unbind_sync():
        current = get_current_driver(pci_address)

        if current != "vfio-pci":
            logger.info(f"{pci_address} not bound to vfio-pci (current: {current})")
            return

        # Unbind from vfio-pci
        logger.info(f"Unbinding {pci_address} from vfio-pci")
        unbind_path = f"/sys/bus/pci/devices/{pci_address}/driver/unbind"
        _write_sysfs(unbind_path, pci_address)

        # Clear driver override to allow default driver
        override_path = f"/sys/bus/pci/devices/{pci_address}/driver_override"
        try:
            _write_sysfs(override_path, "\n")
        except VFIOBindError:
            pass  # Some devices don't support clearing override

        # Probe to rebind default driver
        _write_sysfs("/sys/bus/pci/drivers_probe", pci_address)

        new_driver = get_current_driver(pci_address)
        logger.info(f"{pci_address} rebound to: {new_driver or 'none'}")

    await asyncio.to_thread(_unbind_sync)


def get_iommu_group_non_bridge_devices(pci_address: str) -> list[str]:
    """All non-bridge devices in the same IOMMU group (including self)."""
    from kohakuriver.qemu.capability import (
        get_iommu_group,
        get_iommu_group_devices,
        _is_pci_bridge,
    )

    group = get_iommu_group(pci_address)
    if group is None:
        return [pci_address]
    devices = get_iommu_group_devices(group)
    return [d for d in devices if not _is_pci_bridge(d)]


async def bind_iommu_group(pci_address: str) -> list[str]:
    """Bind ALL non-bridge endpoints in the IOMMU group to vfio-pci.

    Required by VFIO kernel — partial group binding fails.
    Returns list of all PCI addresses that were bound.
    """
    devices = get_iommu_group_non_bridge_devices(pci_address)
    bound = []
    try:
        for dev in devices:
            await bind_to_vfio(dev)
            bound.append(dev)
    finally:
        # Restart nvidia-persistenced so remaining GPUs keep persistence mode.
        # bind_to_vfio stops it when unbinding from nvidia; we restart after
        # the group is done so it only grabs GPUs still bound to nvidia.
        if bound:
            await asyncio.to_thread(_start_nvidia_persistenced)
    logger.info(f"Bound IOMMU group for {pci_address}: {bound}")
    return bound


async def unbind_iommu_group(pci_address: str) -> list[str]:
    """Unbind all non-bridge endpoints in the group from vfio-pci.

    Returns list of all PCI addresses that were unbound.
    """
    devices = get_iommu_group_non_bridge_devices(pci_address)
    unbound = []
    for dev in devices:
        try:
            await unbind_from_vfio(dev)
            unbound.append(dev)
        except Exception as e:
            logger.warning(f"Failed to unbind {dev} from vfio-pci: {e}")
    logger.info(f"Unbound IOMMU group for {pci_address}: {unbound}")
    return unbound
