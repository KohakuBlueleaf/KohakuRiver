# KohakuRiver QEMU/KVM Virtualization

QEMU/KVM virtual machine backend for KohakuRiver. Provides full hardware-isolated VPS sessions as an alternative to Docker containers, with support for GPU passthrough via VFIO.

## Documents

| Document | Description |
|----------|-------------|
| [overview.md](overview.md) | VM architecture, lifecycle, QEMUManager design, disk management, and QMP control |
| [vfio-passthrough.md](vfio-passthrough.md) | VFIO GPU passthrough: IOMMU groups, driver binding, and capability detection |
| [cloud-init.md](cloud-init.md) | Cloud-init provisioning, embedded VM agent, network configuration, and phone-home |

## Quick Summary

KohakuRiver can run VPS workloads inside QEMU/KVM virtual machines instead of Docker containers. VMs provide stronger isolation boundaries, support nested virtualization, and enable direct GPU passthrough via VFIO -- capabilities that are difficult or impossible to achieve with containers.

### Package Structure

```
src/kohakuriver/qemu/
├── __init__.py          # Public API re-exports
├── capability.py        # KVM/IOMMU/VFIO detection, GPU discovery
├── vfio.py              # GPU driver bind/unbind via sysfs
├── cloud_init.py        # Cloud-init ISO generation with embedded VM agent
├── client.py            # QEMUManager class (VM lifecycle, QMP control)
├── naming.py            # VM naming conventions (paths, sockets)
└── exceptions.py        # Exception hierarchy
```

### VM Creation at a Glance

```
Runner receives VPS task (engine=qemu)
         │
         ▼
┌─────────────────────────────┐
│  1. Capability check        │  KVM, QEMU binary, OVMF firmware
│  2. Network setup           │  TAP device + bridge attachment
│  3. Create overlay disk     │  qcow2 backed by base image
│  4. Bind GPUs to VFIO       │  Unbind nvidia → bind vfio-pci
│  5. Generate cloud-init ISO │  meta-data, user-data, network-config
│  6. Build QEMU command      │  q35 machine, KVM, virtio devices
│  7. Start QEMU subprocess   │  Daemonized with PID file
│  8. Wait for phone-home     │  Guest OS booted, agent running
│  9. Wait for SSH ready      │  Port 22 accepting connections
└─────────────────────────────┘
         │
         ▼
   VM is RUNNING
```

### Key Differences from Docker VPS

| Aspect | Docker VPS | QEMU VPS |
|--------|-----------|----------|
| Isolation | Namespace/cgroup | Full hardware virtualization |
| Kernel | Shared host kernel | Independent guest kernel |
| GPU access | NVIDIA Container Toolkit | VFIO passthrough (exclusive) |
| Nested Docker | Not supported | Supported |
| Boot time | Seconds | 30-60 seconds |
| Overhead | Minimal | ~5-10% CPU, fixed RAM allocation |
| Disk format | Bind mounts / volumes | qcow2 overlay images |

### Exception Hierarchy

```
QEMUError
├── QEMUConnectionError    # QMP socket unreachable
├── VMNotFoundError        # Task ID not in VM registry
├── VMCreationError        # VM failed to start
├── VFIOBindError          # GPU driver binding failed
├── CloudInitError         # ISO generation failed
└── VMCapabilityError      # System lacks VM prerequisites
```
