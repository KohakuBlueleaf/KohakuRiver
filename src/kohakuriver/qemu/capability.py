"""
VM capability detection.

Checks if QEMU/KVM + VFIO GPU passthrough is available.
All checks are pure functions with no side effects.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GPUInfo:
    """Information about a GPU available for VFIO passthrough."""

    gpu_id: int
    pci_address: str
    vendor_id: str
    device_id: str
    iommu_group: int
    name: str
    audio_pci: str | None = None
    iommu_group_peers: list[str] = field(default_factory=list)


@dataclass
class VMCapability:
    """VM capability check result."""

    vm_capable: bool
    vfio_gpus: list[GPUInfo]
    errors: list[str]
    warnings: list[str]


# --- Individual Check Functions ---


def check_kvm() -> tuple[bool, str | None]:
    """Check /dev/kvm availability."""
    if os.path.exists("/dev/kvm"):
        if os.access("/dev/kvm", os.R_OK | os.W_OK):
            return True, None
        return False, "/dev/kvm exists but not accessible (check permissions)"
    return False, "/dev/kvm not found (KVM not enabled or kernel module not loaded)"


def check_cpu_virtualization() -> tuple[bool, str | None]:
    """Check VMX/SVM CPU flags."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read()
        if "vmx" in cpuinfo or "svm" in cpuinfo:
            return True, None
        return False, "CPU virtualization (VMX/SVM) not found in /proc/cpuinfo"
    except OSError as e:
        return False, f"Cannot read /proc/cpuinfo: {e}"


def check_iommu() -> tuple[bool, str | None]:
    """Check IOMMU enabled."""
    iommu_groups = Path("/sys/kernel/iommu_groups")
    if iommu_groups.exists() and any(iommu_groups.iterdir()):
        return True, None
    return (
        False,
        "IOMMU not enabled (add intel_iommu=on or amd_iommu=on to kernel params)",
    )


def check_vfio_modules() -> tuple[bool, str | None]:
    """Check VFIO kernel modules."""
    try:
        with open("/proc/modules", "r") as f:
            modules = f.read()
        required = ["vfio", "vfio_pci", "vfio_iommu_type1"]
        missing = [m for m in required if m not in modules]
        if not missing:
            return True, None

        # Try to check if they're built-in
        builtin_missing = []
        for m in missing:
            builtin_path = Path(f"/sys/module/{m}")
            if not builtin_path.exists():
                builtin_missing.append(m)

        if not builtin_missing:
            return True, None
        return (
            False,
            f"VFIO modules not loaded: {', '.join(builtin_missing)} (modprobe vfio-pci)",
        )
    except OSError:
        return False, "Cannot check kernel modules"


def check_qemu() -> tuple[bool, str | None]:
    """Check QEMU and OVMF availability."""
    errors = []

    # Check qemu-system-x86_64
    if not shutil.which("qemu-system-x86_64"):
        errors.append("qemu-system-x86_64 not found (apt install qemu-system-x86)")

    # Check qemu-img
    if not shutil.which("qemu-img"):
        errors.append("qemu-img not found (apt install qemu-utils)")

    # Check OVMF firmware
    ovmf_paths = [
        "/usr/share/OVMF/OVMF_CODE.fd",
        "/usr/share/OVMF/OVMF_CODE_4M.fd",
        "/usr/share/edk2/ovmf/OVMF_CODE.fd",
        "/usr/share/qemu/OVMF_CODE.fd",
    ]
    if not any(os.path.exists(p) for p in ovmf_paths):
        errors.append("OVMF firmware not found (apt install ovmf)")

    # Check genisoimage for cloud-init
    if not shutil.which("genisoimage") and not shutil.which("mkisofs"):
        errors.append("genisoimage/mkisofs not found (apt install genisoimage)")

    if errors:
        return False, "; ".join(errors)
    return True, None


def _check_nvidia_drm_modeset() -> bool:
    """Check if nvidia_drm.modeset=1 (blocks GPU unbinding on consumer cards)."""
    try:
        with open("/sys/module/nvidia_drm/parameters/modeset") as f:
            return f.read().strip() == "Y"
    except OSError:
        return False  # Module not loaded — no issue


# --- ACS Override ---


def check_acs_override_kernel() -> bool:
    """Check if pcie_acs_override is active in kernel cmdline."""
    try:
        with open("/proc/cmdline") as f:
            cmdline = f.read()
        return "pcie_acs_override" in cmdline
    except OSError:
        return False


def apply_acs_override() -> dict:
    """
    Disable ACS on PCI bridges/switches via setpci so IOMMU groups
    get split (requires pcie_acs_override kernel parameter to take effect).

    Returns dict with counts of what was modified.
    """
    results = {"root_ports": 0, "plx_switches": 0, "pci_bridges": 0, "errors": []}

    # Disable ACS on Root Ports
    try:
        lspci = subprocess.run(
            ["lspci"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if lspci.returncode == 0:
            for line in lspci.stdout.splitlines():
                if "Root Port" in line:
                    addr = line.split()[0]
                    r = subprocess.run(
                        ["setpci", "-s", addr, "ECAP_ACS+6.w=0000"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        results["root_ports"] += 1
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        results["errors"].append(f"Root ports: {e}")

    # Disable ACS on PLX/Broadcom switches (vendor 10b5)
    try:
        lspci = subprocess.run(
            ["lspci", "-d", "10b5:"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if lspci.returncode == 0:
            for line in lspci.stdout.splitlines():
                if not line.strip():
                    continue
                addr = line.split()[0]
                for offset in ["ECAP_ACS+6.w=0000", "0x154.w=0000", "0xf2a.w=0000"]:
                    subprocess.run(
                        ["setpci", "-s", addr, offset],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                results["plx_switches"] += 1
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        results["errors"].append(f"PLX switches: {e}")

    # Disable ACS on all PCI bridges
    try:
        lspci = subprocess.run(
            ["lspci"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if lspci.returncode == 0:
            for line in lspci.stdout.splitlines():
                if "PCI bridge" in line:
                    addr = line.split()[0]
                    r = subprocess.run(
                        ["setpci", "-s", addr, "ECAP_ACS+6.w=0000"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        results["pci_bridges"] += 1
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        results["errors"].append(f"PCI bridges: {e}")

    return results


# --- GPU Discovery ---


def get_iommu_group(pci_address: str) -> int | None:
    """Get IOMMU group for PCI device."""
    iommu_link = Path(f"/sys/bus/pci/devices/{pci_address}/iommu_group")
    if iommu_link.exists():
        try:
            group_path = iommu_link.resolve()
            return int(group_path.name)
        except (ValueError, OSError):
            return None
    return None


def _get_pci_device_class(pci_address: str) -> str | None:
    """Read PCI class from sysfs (e.g., '0x060400' for PCI bridge)."""
    try:
        with open(f"/sys/bus/pci/devices/{pci_address}/class") as f:
            return f.read().strip()
    except OSError:
        return None


def _is_pci_bridge(pci_address: str) -> bool:
    """PCI bridge = class 0x06xx (host bridge, PCI-PCI bridge, etc.)."""
    device_class = _get_pci_device_class(pci_address)
    if device_class is None:
        return False
    return device_class.startswith("0x06")


def get_iommu_group_devices(group: int) -> list[str]:
    """All PCI addresses in an IOMMU group."""
    group_path = Path(f"/sys/kernel/iommu_groups/{group}/devices")
    if not group_path.exists():
        return []
    return sorted(dev.name for dev in group_path.iterdir())


def get_iommu_group_endpoints(pci_address: str) -> list[str]:
    """Non-bridge devices in the same IOMMU group (excluding self)."""
    group = get_iommu_group(pci_address)
    if group is None:
        return []
    devices = get_iommu_group_devices(group)
    endpoints = []
    for dev in devices:
        if dev == pci_address:
            continue
        if not _is_pci_bridge(dev):
            endpoints.append(dev)
    return endpoints


def is_iommu_group_viable(pci_address: str) -> tuple[bool, list[str]]:
    """
    Check if IOMMU group is viable for passthrough.

    Returns (viable, list_of_non_bridge_peers).
    Bridges are ignored. Other endpoints are flagged with warnings but
    still considered viable — VFIO requires all non-bridge endpoints in
    the group to be bound to vfio-pci, so they will be co-bound.
    """
    group = get_iommu_group(pci_address)
    if group is None:
        return False, []

    group_path = Path(f"/sys/kernel/iommu_groups/{group}/devices")
    if not group_path.exists():
        return False, []

    peers = []
    for dev_path in group_path.iterdir():
        dev = dev_path.name
        if dev == pci_address:
            continue
        if _is_pci_bridge(dev):
            continue  # Bridges are kernel-managed, safe to ignore
        peers.append(dev)

    return True, peers


def is_iommu_group_clean(pci_address: str) -> bool:
    """
    Legacy check — kept for backward compatibility.
    Prefer is_iommu_group_viable() which handles PCIe switches correctly.
    """
    viable, peers = is_iommu_group_viable(pci_address)
    if not viable:
        return False
    # "Clean" in the old sense: only same-slot peers (audio functions)
    base_slot = pci_address.rsplit(".", 1)[0]
    return all(p.rsplit(".", 1)[0] == base_slot for p in peers)


def _get_gpu_name(pci_address: str) -> str:
    """Get GPU name from lspci or sysfs."""
    try:
        result = subprocess.run(
            ["lspci", "-s", pci_address, "-mm"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse lspci -mm output
            parts = result.stdout.strip().split('"')
            if len(parts) >= 6:
                return parts[5]  # Device name
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback: read from sysfs
    try:
        with open(f"/sys/bus/pci/devices/{pci_address}/label") as f:
            return f.read().strip()
    except OSError:
        return f"GPU at {pci_address}"


def discover_vfio_gpus() -> list[GPUInfo]:
    """Discover GPUs suitable for VFIO passthrough."""
    gpus = []

    # NVIDIA vendor ID
    nvidia_vendor = "10de"

    pci_devices = Path("/sys/bus/pci/devices")
    if not pci_devices.exists():
        return gpus

    gpu_id = 0
    for device_path in sorted(pci_devices.iterdir()):
        pci_address = device_path.name

        # Check if it's a VGA/3D controller (class 0x03xxxx)
        try:
            with open(device_path / "class") as f:
                device_class = f.read().strip()
            if not device_class.startswith("0x03"):
                continue
        except OSError:
            continue

        # Check vendor
        try:
            with open(device_path / "vendor") as f:
                vendor_id = f.read().strip().replace("0x", "")
            with open(device_path / "device") as f:
                device_id = f.read().strip().replace("0x", "")
        except OSError:
            continue

        # Only consider NVIDIA GPUs for now
        if vendor_id != nvidia_vendor:
            continue

        # Check IOMMU group
        iommu = get_iommu_group(pci_address)
        if iommu is None:
            logger.debug(f"GPU {pci_address}: no IOMMU group, skipping")
            continue

        # Check if IOMMU group is viable for passthrough
        viable, group_peers = is_iommu_group_viable(pci_address)
        if not viable:
            logger.debug(f"GPU {pci_address}: IOMMU group {iommu} not viable, skipping")
            continue

        # Classify peers: audio (0x0403), other GPUs (0x03xx), other endpoints
        audio_pci = None
        non_gpu_non_audio_peers = []
        for peer in group_peers:
            peer_class = _get_pci_device_class(peer)
            if peer_class and peer_class.startswith("0x0403"):
                # Audio device — prefer same-slot audio
                base_slot = pci_address.rsplit(".", 1)[0]
                if peer.rsplit(".", 1)[0] == base_slot:
                    audio_pci = peer
            elif peer_class and peer_class.startswith("0x03"):
                pass  # Another GPU — will be discovered separately
            else:
                non_gpu_non_audio_peers.append(peer)

        if non_gpu_non_audio_peers:
            logger.warning(
                f"GPU {pci_address}: IOMMU group {iommu} has non-GPU/audio "
                f"endpoints that will be co-bound to vfio-pci: "
                f"{non_gpu_non_audio_peers}"
            )

        # Build list of peers that must be co-bound (non-bridge, non-self,
        # non-audio endpoints — i.e. other GPUs and unknown endpoints)
        iommu_group_peers = [
            p
            for p in group_peers
            if p != audio_pci
            and _get_pci_device_class(p) not in (None,)
            and not _get_pci_device_class(p).startswith("0x0403")
        ]

        name = _get_gpu_name(pci_address)

        gpus.append(
            GPUInfo(
                gpu_id=gpu_id,
                pci_address=pci_address,
                vendor_id=vendor_id,
                device_id=device_id,
                iommu_group=iommu,
                name=name,
                audio_pci=audio_pci,
                iommu_group_peers=iommu_group_peers,
            )
        )
        gpu_id += 1

    # Log co-allocation warnings for GPUs sharing IOMMU groups
    gpu_by_addr = {g.pci_address: g for g in gpus}
    for gpu in gpus:
        shared_gpus = [p for p in gpu.iommu_group_peers if p in gpu_by_addr]
        if shared_gpus:
            logger.info(
                f"GPU {gpu.pci_address} (group {gpu.iommu_group}) shares "
                f"IOMMU group with GPUs: {shared_gpus} — "
                f"they must be co-allocated for VFIO passthrough"
            )

    return gpus


# --- Main API ---


def check_vm_capability() -> VMCapability:
    """
    Comprehensive VM capability check.

    Returns VMCapability with all check results.
    """
    errors = []
    warnings = []

    # Check basic KVM support
    kvm_ok, kvm_err = check_kvm()
    if not kvm_ok:
        errors.append(kvm_err)

    cpu_ok, cpu_err = check_cpu_virtualization()
    if not cpu_ok:
        errors.append(cpu_err)

    # Check QEMU tools
    qemu_ok, qemu_err = check_qemu()
    if not qemu_ok:
        errors.append(qemu_err)

    # Check IOMMU (warning only - VMs can work without GPU passthrough)
    iommu_ok, iommu_err = check_iommu()
    if not iommu_ok:
        warnings.append(f"IOMMU: {iommu_err}")

    # Check VFIO modules (warning only)
    vfio_ok, vfio_err = check_vfio_modules()
    if not vfio_ok:
        warnings.append(f"VFIO: {vfio_err}")

    # Check nvidia_drm.modeset — blocks GPU unbinding on consumer cards
    drm_modeset = _check_nvidia_drm_modeset()
    if drm_modeset:
        warnings.append(
            "nvidia_drm.modeset=Y: GPU unbinding will hang on consumer cards. "
            "Set nvidia_drm.modeset=0 in kernel params for headless compute nodes"
        )

    # Discover VFIO-capable GPUs
    vfio_gpus = []
    if iommu_ok and vfio_ok:
        vfio_gpus = discover_vfio_gpus()
        if not vfio_gpus:
            warnings.append("No GPUs suitable for VFIO passthrough found")

    # VM-capable if KVM, CPU virtualization, and QEMU tools are available
    vm_capable = kvm_ok and cpu_ok and qemu_ok

    return VMCapability(
        vm_capable=vm_capable,
        vfio_gpus=vfio_gpus,
        errors=errors,
        warnings=warnings,
    )


def detect_nvidia_driver_version() -> str | None:
    """Detect installed NVIDIA driver version on the host.

    Tries (in order):
    1. /sys/module/nvidia/version (fastest, no deps)
    2. nvidia-smi --query-gpu=driver_version (subprocess)
    3. pynvml if available
    """
    # Method 1: sysfs
    version_path = Path("/sys/module/nvidia/version")
    if version_path.exists():
        try:
            return version_path.read_text().strip()
        except OSError:
            pass

    # Method 2: nvidia-smi
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Take first line (first GPU)
            return result.stdout.strip().split("\n")[0].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Method 3: pynvml
    try:
        import pynvml

        pynvml.nvmlInit()
        version = pynvml.nvmlSystemGetDriverVersion()
        pynvml.nvmlShutdown()
        if isinstance(version, bytes):
            version = version.decode()
        return version
    except Exception:
        pass

    return None


# Cached result
_cached: VMCapability | None = None


def get_vm_capability(refresh: bool = False) -> VMCapability:
    """Get cached VM capability."""
    global _cached
    if _cached is None or refresh:
        _cached = check_vm_capability()
    return _cached
