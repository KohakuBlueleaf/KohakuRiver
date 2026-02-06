# VFIO GPU Passthrough

## What is VFIO

VFIO (Virtual Function I/O) is a Linux kernel framework that provides safe, non-privileged access to physical hardware devices from userspace. In the context of KohakuRiver, VFIO is used to pass entire NVIDIA GPUs through to QEMU virtual machines, giving the guest OS direct, exclusive access to the physical GPU hardware.

Unlike the NVIDIA Container Toolkit (used for Docker containers), VFIO passthrough provides:

- **Exclusive hardware access**: The GPU is fully owned by the VM, not shared
- **Full driver support**: The guest installs its own NVIDIA driver, independent of the host
- **Hardware isolation**: The GPU's MMIO regions and interrupts are isolated by the IOMMU
- **Near-native performance**: No virtualization overhead on GPU operations

The tradeoff is that a GPU passed through via VFIO is unavailable to the host and other VMs until it is unbound.

---

## IOMMU Groups

### Concept

An IOMMU (Input-Output Memory Management Unit) groups PCI devices that share the same address translation and isolation domain. VFIO operates at the IOMMU group level: to safely pass through a device, **all devices in its IOMMU group** must either be:

1. Passed through to the same VM, or
2. Unbound from their host driver (not in use by the host)

### IOMMU Group Cleanness

KohakuRiver checks whether a GPU's IOMMU group is "clean" before allowing passthrough. A clean group contains **only** devices on the same PCI slot -- typically the GPU itself and its associated HD Audio controller:

```
Clean IOMMU Group (safe for passthrough):
┌──────────────────────────────────────────────┐
│ IOMMU Group 14                               │
│                                              │
│  0000:01:00.0  NVIDIA GPU (class 0x030000)   │  ← Same PCI slot
│  0000:01:00.1  HD Audio   (class 0x040300)   │  ← Same PCI slot
│                                              │
│  Both devices share slot 0000:01:00          │
└──────────────────────────────────────────────┘

Dirty IOMMU Group (NOT safe for passthrough):
┌──────────────────────────────────────────────┐
│ IOMMU Group 1                                │
│                                              │
│  0000:01:00.0  NVIDIA GPU                    │  ← Slot 01:00
│  0000:01:00.1  HD Audio                      │  ← Slot 01:00
│  0000:00:01.0  PCI Bridge                    │  ← DIFFERENT slot!
│                                              │
│  Passing through would affect the bridge     │
└──────────────────────────────────────────────┘
```

The cleanness check is implemented in `capability.py`:

```python
def is_iommu_group_clean(pci_address: str) -> bool:
    base_slot = pci_address.rsplit(".", 1)[0]   # "0000:01:00"
    for dev in group_devices:
        dev_slot = dev.name.rsplit(".", 1)[0]
        if dev_slot != base_slot:
            return False  # Foreign device in the group
    return True
```

---

## GPU Discovery

GPU discovery (`capability.py: discover_vfio_gpus()`) scans `/sys/bus/pci/devices/` to find GPUs suitable for VFIO passthrough.

### Discovery Flow

```
/sys/bus/pci/devices/
        │
        ▼  Iterate all PCI devices
┌───────────────────────────────────┐
│ Read /class                       │
│ Filter: 0x03xxxx (VGA/3D)        │──── Skip non-GPU devices
└───────────────┬───────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│ Read /vendor                      │
│ Filter: 0x10de (NVIDIA)          │──── Skip non-NVIDIA (for now)
└───────────────┬───────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│ Resolve /iommu_group symlink      │
│ Extract group number              │──── Skip if no IOMMU group
└───────────────┬───────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│ Check IOMMU group cleanness       │
│ All devices on same PCI slot?     │──── Skip if dirty group
└───────────────┬───────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│ Find audio device in same slot    │
│ Scan functions 1-7, class 0x0403 │
└───────────────┬───────────────────┘
                │
                ▼
┌───────────────────────────────────┐
│ Get GPU name via lspci -s -mm     │
│ Fallback: sysfs /label            │
└───────────────┬───────────────────┘
                │
                ▼
        GPUInfo dataclass
```

### GPUInfo Fields

| Field | Example | Source |
|-------|---------|--------|
| `gpu_id` | `0` | Sequential index |
| `pci_address` | `0000:01:00.0` | sysfs directory name |
| `vendor_id` | `10de` | `/sys/bus/pci/devices/.../vendor` |
| `device_id` | `2684` | `/sys/bus/pci/devices/.../device` |
| `iommu_group` | `14` | `/sys/bus/pci/devices/.../iommu_group` symlink |
| `name` | `NVIDIA GeForce RTX 4090` | `lspci -s <addr> -mm` |
| `audio_pci` | `0000:01:00.1` | Scan same-slot functions for class `0x0403` |

---

## Bind / Unbind Flow

### Binding to VFIO

The `bind_to_vfio()` function (`vfio.py`) transfers a GPU from its current driver (typically `nvidia` or `nouveau`) to the `vfio-pci` driver:

```
GPU bound to nvidia driver
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. Check current driver                                         │
│    Read: /sys/bus/pci/devices/{addr}/driver → symlink           │
│    If already vfio-pci → return early                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Unbind from current driver                                   │
│    Write "{addr}" → /sys/bus/pci/devices/{addr}/driver/unbind   │
│                                                                 │
│    sysfs effect: driver releases the device                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Set driver override                                          │
│    Write "vfio-pci" → /sys/bus/pci/devices/{addr}/driver_override│
│                                                                 │
│    sysfs effect: kernel will only probe vfio-pci for this device│
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Trigger driver probe                                         │
│    Write "{addr}" → /sys/bus/pci/drivers_probe                  │
│                                                                 │
│    sysfs effect: kernel probes device, vfio-pci binds it        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Verify binding                                               │
│    Read: /sys/bus/pci/devices/{addr}/driver → should be vfio-pci│
│    If not → raise VFIOBindError                                 │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                   GPU bound to vfio-pci
                   Ready for VM passthrough
```

### Unbinding from VFIO

When a VM is stopped or cleaned up, GPUs are returned to the host via `unbind_from_vfio()`:

```
GPU bound to vfio-pci
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. Check current driver                                         │
│    If not vfio-pci → return early (nothing to do)               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Unbind from vfio-pci                                         │
│    Write "{addr}" → /sys/bus/pci/devices/{addr}/driver/unbind   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Clear driver override                                        │
│    Write "\n" → /sys/bus/pci/devices/{addr}/driver_override     │
│    (Allows kernel to choose default driver again)               │
│    Note: failure here is tolerated — some devices don't support │
│    clearing the override                                        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Trigger driver probe                                         │
│    Write "{addr}" → /sys/bus/pci/drivers_probe                  │
│    Kernel re-probes → nvidia driver binds automatically         │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                   GPU rebound to nvidia driver
                   Available to host again
```

### Audio Device Handling

NVIDIA GPUs often have an associated HD Audio controller on the same PCI slot (different function number). For example:

```
0000:01:00.0  → GPU          (function 0)
0000:01:00.1  → HD Audio     (function 1)
```

Both devices share the same IOMMU group. When a GPU is passed through to a VM, the audio device must be passed through as well. The QEMU command builder handles this automatically:

```python
# In _build_qemu_command():
for pci_addr in options.gpu_pci_addresses:
    cmd.extend(["-device", f"vfio-pci,host={pci_addr}"])
    # Also pass through the audio device if present
    for gpu in discover_vfio_gpus():
        if gpu.pci_address == pci_addr and gpu.audio_pci:
            cmd.extend(["-device", f"vfio-pci,host={gpu.audio_pci}"])
```

The audio device is bound to VFIO as part of the GPU's IOMMU group handling by the kernel -- no separate bind call is needed because `vfio-pci` claims the entire group.

---

## Error Scenarios and Recovery

### Bind Failures

| Scenario | Cause | Recovery |
|----------|-------|----------|
| Device busy | GPU in use by another process (X11, compute job) | Stop workload using the GPU first |
| Permission denied | Process lacks write access to sysfs | Run Runner as root |
| Driver not loaded | `vfio-pci` module not available | `modprobe vfio-pci` |
| Verification failed | `driver_override` set but probe did not bind | Check dmesg; IOMMU may not be enabled |

All bind operations run in a thread (`asyncio.to_thread`) because sysfs writes can block. Failures raise `VFIOBindError` with the PCI address attached.

### Cleanup on VM Failure

If VM creation fails after GPUs have been bound, `_cleanup_vm_on_error()` unbinds each GPU from VFIO. Unbind failures during cleanup are logged as warnings but do not raise exceptions -- the priority is to avoid leaving GPUs stuck in vfio-pci state.

### Manual Recovery

If a GPU is left bound to `vfio-pci` due to a crash:

```bash
# Check current driver
ls -l /sys/bus/pci/devices/0000:01:00.0/driver

# Unbind from vfio-pci
echo "0000:01:00.0" > /sys/bus/pci/devices/0000:01:00.0/driver/unbind

# Clear override
echo "" > /sys/bus/pci/devices/0000:01:00.0/driver_override

# Trigger re-probe (nvidia driver will bind)
echo "0000:01:00.0" > /sys/bus/pci/drivers_probe
```

---

## Capability Detection

The full capability check (`capability.py: check_vm_capability()`) runs a sequence of independent checks and produces a `VMCapability` result:

```
┌──────────────────────────────────────────────────────────────────┐
│                    check_vm_capability()                          │
│                                                                  │
│  Required (errors if missing):                                   │
│  ┌──────────────────────────────────────────────────────┐        │
│  │ check_kvm()           → /dev/kvm exists + accessible │        │
│  │ check_cpu_virt()      → VMX or SVM in /proc/cpuinfo  │        │
│  │ check_qemu()          → qemu-system-x86_64, qemu-img,│        │
│  │                         OVMF firmware, genisoimage   │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                  │
│  Optional (warnings if missing):                                 │
│  ┌──────────────────────────────────────────────────────┐        │
│  │ check_iommu()         → /sys/kernel/iommu_groups     │        │
│  │ check_vfio_modules()  → vfio, vfio_pci,              │        │
│  │                         vfio_iommu_type1 in          │        │
│  │                         /proc/modules or /sys/module  │        │
│  │ discover_vfio_gpus()  → NVIDIA GPUs with clean groups │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                  │
│  Result: VMCapability                                            │
│    vm_capable = kvm_ok AND cpu_ok AND qemu_ok                    │
│    vfio_gpus  = [...discovered GPUs...]                          │
│    errors     = [...critical failures...]                        │
│    warnings   = [...non-critical issues...]                      │
└──────────────────────────────────────────────────────────────────┘
```

**Key design decision**: IOMMU and VFIO are warnings, not errors. A Runner can host VMs without GPU passthrough -- only KVM and QEMU binaries are strictly required. The `vm_capable` flag reflects this: a system with KVM + QEMU is VM-capable even without VFIO support.

### Caching

The capability result is cached globally (`get_vm_capability()`). Pass `refresh=True` to force a re-check, for example after loading VFIO kernel modules.
