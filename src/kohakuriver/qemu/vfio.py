"""
VFIO GPU binding/unbinding operations.

Handles driver binding for GPU passthrough.
Supports IOMMU group-aware binding: all non-bridge endpoints in a
group must be bound to vfio-pci together (VFIO kernel requirement).
"""

import asyncio
import subprocess
import threading
from pathlib import Path

from kohakuriver.qemu.capability import (
    get_iommu_group,
    get_iommu_group_devices,
    _is_pci_bridge,
)
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


def _write_sysfs_timeout(path: str, value: str, timeout: float = 5.0) -> bool:
    """Write to a sysfs file with a timeout.

    Consumer NVIDIA cards can hang on the unbind sysfs write even after
    the driver has actually released the device.  Returns True if the
    write completed within *timeout* seconds, False if it timed out
    (the daemon thread is left behind — it will finish eventually or be
    cleaned up at process exit).
    """
    error: OSError | None = None

    def _do_write():
        nonlocal error
        try:
            with open(path, "w") as f:
                f.write(value)
        except OSError as e:
            error = e

    t = threading.Thread(target=_do_write, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if error:
        raise VFIOBindError(f"Failed to write '{value}' to {path}: {error}", path)

    return not t.is_alive()


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
            completed = _write_sysfs_timeout(unbind_path, pci_address, timeout=5.0)

            if not completed:
                # Consumer NVIDIA cards: write hangs but unbind may have succeeded
                actual = get_current_driver(pci_address)
                if actual is None:
                    logger.info(
                        f"Unbind write timed out but {pci_address} is now unbound — continuing"
                    )
                else:
                    raise VFIOBindError(
                        f"Unbind timed out and {pci_address} still bound to {actual}",
                        pci_address,
                    )

        # Set driver override to vfio-pci
        override_path = f"/sys/bus/pci/devices/{pci_address}/driver_override"
        if not _write_sysfs_timeout(override_path, "vfio-pci", timeout=5.0):
            logger.warning(f"driver_override write timed out for {pci_address}")

        # Try drivers_probe first, then explicit bind as fallback.
        # Newer kernels may not honour drivers_probe alone after
        # driver_override — explicit vfio-pci/bind is more reliable.
        _write_sysfs_timeout("/sys/bus/pci/drivers_probe", pci_address, timeout=5.0)

        if get_current_driver(pci_address) != "vfio-pci":
            logger.info(
                f"drivers_probe did not bind {pci_address}, trying explicit vfio-pci/bind"
            )
            _write_sysfs_timeout(
                "/sys/bus/pci/drivers/vfio-pci/bind", pci_address, timeout=5.0
            )

        # Verify binding
        new_driver = get_current_driver(pci_address)
        if new_driver != "vfio-pci":
            raise VFIOBindError(
                f"Expected vfio-pci but got '{new_driver}'", pci_address
            )

        logger.info(f"Successfully bound {pci_address} to vfio-pci")

    await asyncio.to_thread(_bind_sync)


def _is_nvidia_device(pci_address: str) -> bool:
    """Check if a PCI device is from NVIDIA (vendor 0x10de)."""
    try:
        with open(f"/sys/bus/pci/devices/{pci_address}/vendor") as f:
            return f.read().strip() == "0x10de"
    except OSError:
        return False


async def unbind_from_vfio(pci_address: str) -> None:
    """
    Unbind device from vfio-pci and let kernel rebind its original driver.

    For NVIDIA devices: stops nvidia-persistenced, then tries nvidia/bind
    as fallback if drivers_probe doesn't restore it.
    For non-NVIDIA devices (PLX DMA, etc.): relies on drivers_probe to
    restore the original driver automatically.

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

        is_nvidia = _is_nvidia_device(pci_address)

        # Only stop nvidia-persistenced for NVIDIA devices — it holds fds
        # that block the nvidia driver from re-attaching.
        if is_nvidia:
            _stop_nvidia_persistenced()

        # Unbind from vfio-pci
        logger.info(f"Unbinding {pci_address} from vfio-pci")
        unbind_path = f"/sys/bus/pci/devices/{pci_address}/driver/unbind"
        completed = _write_sysfs_timeout(unbind_path, pci_address, timeout=5.0)

        if not completed:
            actual = get_current_driver(pci_address)
            if actual is None or actual != "vfio-pci":
                logger.info(
                    f"Unbind write timed out but {pci_address} is now unbound — continuing"
                )
            else:
                raise VFIOBindError(
                    f"Unbind timed out and {pci_address} still bound to {actual}",
                    pci_address,
                )

        # Clear driver override to allow default driver
        override_path = f"/sys/bus/pci/devices/{pci_address}/driver_override"
        try:
            if not _write_sysfs_timeout(override_path, "\n", timeout=5.0):
                logger.warning(f"driver_override write timed out for {pci_address}")
        except VFIOBindError:
            pass  # Some devices don't support clearing override

        # Let kernel re-probe the right driver
        _write_sysfs_timeout("/sys/bus/pci/drivers_probe", pci_address, timeout=5.0)

        new_driver = get_current_driver(pci_address)

        # Only try explicit nvidia/bind for NVIDIA devices
        if is_nvidia and new_driver != "nvidia":
            logger.info(
                f"drivers_probe did not restore nvidia for {pci_address} "
                f"(driver: {new_driver}), trying explicit nvidia/bind"
            )
            try:
                _write_sysfs_timeout(
                    "/sys/bus/pci/drivers/nvidia/bind", pci_address, timeout=5.0
                )
            except VFIOBindError as e:
                logger.warning(f"Explicit nvidia/bind failed for {pci_address}: {e}")
            new_driver = get_current_driver(pci_address)

        logger.info(f"{pci_address} rebound to: {new_driver or 'none'}")

    await asyncio.to_thread(_unbind_sync)


def get_iommu_group_non_bridge_devices(pci_address: str) -> list[str]:
    """All non-bridge devices in the same IOMMU group (including self).

    Bridge devices (PCI class 0x06xx) are kernel-managed and excluded.
    Everything else — GPUs, audio, PLX DMA endpoints — must be bound
    to vfio-pci together for the VFIO group to be viable.
    """
    group = get_iommu_group(pci_address)
    if group is None:
        return [pci_address]
    devices = get_iommu_group_devices(group)
    return [d for d in devices if not _is_pci_bridge(d)]


async def bind_iommu_group(pci_address: str) -> list[str]:
    """Bind ALL non-bridge endpoints in the IOMMU group to vfio-pci.

    VFIO kernel requires every non-bridge device in a group to be bound
    to vfio-pci for the group to be viable. This includes PLX DMA
    endpoints and other non-GPU devices sharing the group.

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
        if bound:
            await asyncio.to_thread(_start_nvidia_persistenced)
    logger.info(f"Bound IOMMU group for {pci_address}: {bound}")
    return bound


async def unbind_iommu_group(pci_address: str) -> list[str]:
    """Unbind all non-bridge endpoints in the group from vfio-pci.

    Each device is restored to its original driver via drivers_probe.
    NVIDIA devices get an explicit nvidia/bind fallback; non-NVIDIA
    devices (PLX DMA, etc.) rely on drivers_probe alone.

    Returns list of all PCI addresses that were unbound.
    """
    devices = get_iommu_group_non_bridge_devices(pci_address)
    unbound = []
    try:
        for dev in devices:
            try:
                await unbind_from_vfio(dev)
                unbound.append(dev)
            except Exception as e:
                logger.warning(f"Failed to unbind {dev} from vfio-pci: {e}")
    finally:
        # Restart nvidia-persistenced so restored GPUs get persistence mode.
        if unbound:
            await asyncio.to_thread(_start_nvidia_persistenced)
    logger.info(f"Unbound IOMMU group for {pci_address}: {unbound}")
    return unbound
