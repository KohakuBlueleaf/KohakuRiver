---
title: kohakuriver qemu
description: QEMU/KVM management commands for VM capabilities and images.
icon: i-carbon-virtual-machine
---

# kohakuriver qemu

The `kohakuriver qemu` command group manages QEMU/KVM capabilities, GPU passthrough configuration, and VM base images.

## Commands

### qemu check

Check QEMU capabilities on the current runner node.

```bash
kohakuriver qemu check
```

Reports:

- QEMU installation status and version
- KVM availability
- IOMMU status
- Discovered VFIO-capable GPUs with:
  - PCI address (e.g., `0000:41:00.0`)
  - IOMMU group
  - GPU model name
  - Companion audio devices
- ACS override status

### qemu acs-override

Configure ACS (Access Control Services) override for IOMMU group splitting.

```bash
kohakuriver qemu acs-override
```

On server hardware, multiple GPUs may share the same IOMMU group. ACS override patches allow individual GPU passthrough by splitting IOMMU groups. This command configures the necessary kernel parameters.

**Warning**: ACS override reduces IOMMU isolation guarantees. Only use this on trusted environments where all PCIe devices are controlled.

### qemu image

VM base image management:

#### image create

```bash
kohakuriver qemu image create --name <image_name>
```

Creates a new base VM image using the `scripts/create-vm-base-image.sh` script. The image is stored in `VM_IMAGES_DIR` (default: `~/.kohakuriver/vm-images/`).

#### image list

```bash
kohakuriver qemu image list
```

Lists all available base VM images with their size and creation date.

### qemu instances

List running QEMU VM instances.

```bash
kohakuriver qemu instances
```

Shows all active VM processes with their task ID, PID, allocated resources, and GPU assignments.

### qemu cleanup

Clean up stale QEMU resources.

```bash
kohakuriver qemu cleanup
```

Removes:

- Orphaned QEMU processes
- Stale VFIO bindings
- Temporary disk images from failed VMs

## Related Topics

- [QEMU/KVM Setup](../setup/qemu-kvm.md) -- Installation and configuration
- [GPU Passthrough](../setup/gpu-passthrough.md) -- VFIO setup
- [VM VPS](../vps/vm-vps.md) -- Creating VM VPS instances
