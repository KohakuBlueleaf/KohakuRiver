---
title: QEMU Package
description: QEMU module architecture covering capability detection, VFIO, cloud-init, and VM management
icon: i-carbon-virtual-machine
---

# QEMU Package

The `src/kohakuriver/qemu/` package provides QEMU/KVM integration for running VPS sessions as full virtual machines with GPU passthrough.

## Module Overview

```
qemu/
├── capability.py    VMCapability detection (KVM, IOMMU, VFIO, tools)
├── client.py        QEMUManager: VM lifecycle (create, stop, recover)
├── vfio.py          VFIO GPU bind/unbind (IOMMU-group-aware)
├── cloud_init.py    Cloud-init seed.iso generation + embedded VM agent
├── naming.py        VM naming, paths, QMP socket conventions
├── exceptions.py    Exception hierarchy
└── __init__.py      Re-exports

    ┌──────────────────────────────────────────────────┐
    │                  QEMUManager                     │
    │               (client.py)                        │
    │                                                  │
    │  create_vm()  stop_vm()  recover_vm()            │
    │  qmp_shutdown()  qmp_reset()  qmp_command()      │
    └──────┬─────────┬─────────┬───────────────────────┘
           │         │                                 │
    ┌──────▼──┐ ┌────▼────┐ ┌─▼──────────┐ ┌───────────┐
    │ vfio.py │ │cloud_   │ │ naming.py  │ │capability │
    │         │ │init.py  │ │            │ │  .py      │
    │ bind    │ │ ISO     │ │ paths      │ │ detect    │
    │ unbind  │ │ agent   │ │ names      │ │ checks    │
    └────┬────┘ └─────────┘ └────────────┘ └───────────┘
                                                       │
    ┌────▼─────────────────────────────────────────────┐
    │ capability.py                                    │
    │ IOMMU group                                      │
    │ GPU discovery                                    │
    └──────────────────────────────────────────────────┘
```

## Capability Detection (`capability.py`)

`check_vm_capability()` runs a series of checks and returns a `VMCapability` result:

```python
@dataclass
class VMCapability:
    vm_capable: bool        # KVM + CPU virt + QEMU tools
    vfio_gpus: list[GPUInfo]  # GPUs suitable for passthrough
    errors: list[str]       # Blocking errors
    warnings: list[str]     # Non-blocking warnings
```

Individual checks:

| Check                        | What it verifies                                                       |
| ---------------------------- | ---------------------------------------------------------------------- |
| `check_kvm()`                | `/dev/kvm` exists and is accessible                                    |
| `check_cpu_virtualization()` | VMX/SVM flags in `/proc/cpuinfo`                                       |
| `check_iommu()`              | IOMMU groups present in `/sys/kernel/iommu_groups`                     |
| `check_vfio_modules()`       | `vfio`, `vfio_pci`, `vfio_iommu_type1` kernel modules loaded           |
| `check_qemu()`               | `qemu-system-x86_64`, `qemu-img`, OVMF firmware, `genisoimage` present |

GPU discovery (`discover_vfio_gpus()`) scans `/sys/bus/pci/devices` for NVIDIA VGA/3D controllers (PCI class `0x03xx`, vendor `10de`) and evaluates IOMMU group viability.

### GPUInfo

```python
@dataclass
class GPUInfo:
    gpu_id: int
    pci_address: str          # e.g., "0000:01:00.0"
    vendor_id: str
    device_id: str
    iommu_group: int
    name: str
    audio_pci: str | None     # Companion audio device (same IOMMU group)
    iommu_group_peers: list[str]  # Co-grouped PCI devices
```

### ACS Override

`apply_acs_override()` disables Access Control Services on PCI bridges via `setpci` to split IOMMU groups for individual GPU allocation. This is called when `VM_ACS_OVERRIDE=True` in runner config. Required on consumer motherboards where all GPUs share a single IOMMU group.

## VFIO GPU Binding (`vfio.py`)

VFIO requires all non-bridge endpoints in an IOMMU group to be bound to `vfio-pci` together.

### Key Functions

- `bind_iommu_group(pci_address)` -- Binds all non-bridge devices in the group to `vfio-pci`. Stops `nvidia-persistenced` first (holds file descriptors that block unbind). Returns list of bound addresses.
- `unbind_iommu_group(pci_address)` -- Restores all devices to their original drivers. Uses `drivers_probe` with explicit `nvidia/bind` fallback.
- `bind_to_vfio(pci_address)` -- Single-device bind with timeout handling for consumer NVIDIA cards.
- `unbind_from_vfio(pci_address)` -- Single-device unbind.

Sysfs writes use `_write_sysfs_timeout()` which runs in a daemon thread with a 5-second timeout -- consumer NVIDIA cards can hang on the unbind write.

## Cloud-Init (`cloud_init.py`)

Generates a `seed.iso` with three files:

1. **meta-data**: instance ID and hostname
2. **user-data**: user setup, SSH keys, VM agent, packages, NVIDIA driver install
3. **network-config**: static IP via MAC address matching

### VM Agent

An embedded Python script (`VM_AGENT_SCRIPT`) runs inside the VM as a systemd service:

1. **Phone-home**: POST to `/api/vps/{task_id}/vm-phone-home` on first boot to notify the runner
2. **Heartbeat loop**: POST GPU info and system stats to `/api/vps/{task_id}/vm-heartbeat` every 10 seconds

The agent collects GPU metrics via `pynvml` and system metrics from `/proc`.

### CloudInitConfig

```python
@dataclass
class CloudInitConfig:
    task_id: int
    hostname: str
    mac_address: str
    vm_ip: str
    gateway: str
    prefix_len: int
    dns_servers: list[str]
    ssh_public_key: str
    runner_url: str
    nvidia_driver_version: str | None  # Triggers NVIDIA driver install
```

## QEMUManager (`client.py`)

The main VM lifecycle manager. Global instance via `get_qemu_manager()`.

### VMInstance

```python
@dataclass
class VMInstance:
    task_id: int
    pid: int                      # QEMU daemon PID
    vm_ip: str
    tap_device: str
    gpu_pci_addresses: list[str]
    instance_dir: str
    qmp_socket: str               # QMP Unix socket path
    ssh_ready: bool = False
    last_heartbeat: float | None = None
    vm_gpu_info: list[dict] = []
```

### VM Creation Flow

`create_vm(options)` executes these steps:

```
 1. Create instance directory under VM_INSTANCES_DIR
 2. Create qcow2 overlay disk backed by base image
 3. Detect host NVIDIA driver version (before VFIO bind)
 4. Bind GPUs to VFIO (group-aware)
 5. Generate cloud-init seed ISO
 6. Build QEMU command line:
    - KVM acceleration
    - Q35 machine type
    - UEFI firmware (OVMF)
    - virtio disk + NIC
    - 9p filesystem mounts
    - VFIO GPU device passthrough
 7. Start QEMU with -daemonize, read PID from pidfile
 8. Track VMInstance in memory
```

### QMP Control

VMs are controlled via QMP (QEMU Machine Protocol) over Unix sockets:

- `qmp_shutdown(task_id)` -- graceful `system_powerdown`
- `qmp_reset(task_id)` -- hard `system_reset`
- `qmp_command(task_id, command)` -- arbitrary QMP commands

### Recovery

`recover_vm(task_id, vm_data)` re-adopts a running VM by reading the PID from the pidfile and verifying the process is alive. Called during runner startup to recover VMs that survived a runner restart.

## Naming Conventions (`naming.py`)

| Function                       | Example Output                  |
| ------------------------------ | ------------------------------- |
| `vm_name(12345)`               | `kohaku-vm-12345`               |
| `vm_instance_dir(base, 12345)` | `/var/lib/.../12345`            |
| `vm_root_disk_path(dir)`       | `.../root.qcow2`                |
| `vm_cloud_init_path(dir)`      | `.../seed.iso`                  |
| `vm_qmp_socket_path(12345)`    | `/run/kohakuriver/vm/12345.qmp` |

## Exception Hierarchy

```
QEMUError (base)
├── QEMUConnectionError    QMP socket connection failed
├── VMNotFoundError        VM not tracked (includes task_id)
├── VMCreationError        VM creation failed (includes task_id)
├── VFIOBindError          VFIO GPU binding failed (includes pci_address)
├── CloudInitError         Cloud-init ISO creation failed
└── VMCapabilityError      Capability check failed
```
