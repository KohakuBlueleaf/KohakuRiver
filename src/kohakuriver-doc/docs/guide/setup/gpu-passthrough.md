---
title: GPU Passthrough
description: Setting up IOMMU, VFIO, NVIDIA drivers, and ACS override for GPU passthrough.
icon: i-carbon-chip
---

# GPU Passthrough

KohakuRiver supports two GPU access modes:

1. **Docker GPU sharing** -- Multiple containers share GPUs via `--gpus` flag (NVIDIA Container Toolkit) (default for Docker VPS/tasks)
2. **VFIO GPU passthrough** -- Dedicated GPU access for QEMU/KVM VMs via VFIO

## Docker GPU Allocation

For Docker-based workloads, GPUs are allocated by index. The runner uses `--gpus "device=..."` to restrict which GPUs a container can see.

```bash
# Allocate GPU 0 and 1
kohakuriver task submit -t mynode::0,1 -- python train.py

# Create VPS with GPU 2
kohakuriver vps create -t mynode::2
```

This requires:

- NVIDIA drivers on the host
- NVIDIA Container Toolkit installed
- `nvidia-ml-py` optional dependency for GPU monitoring (`pip install "kohakuriver[gpu]"`)

## VFIO GPU Passthrough (QEMU VMs)

For full GPU isolation, QEMU VMs use VFIO to pass PCI devices directly to the VM.

### Prerequisites

1. **CPU with virtualization support** (Intel VT-x/VT-d or AMD-V/AMD-Vi)
2. **IOMMU enabled** in BIOS/UEFI
3. **Kernel parameters** for IOMMU and optionally ACS override

### Step 1: Enable IOMMU

Add to `/etc/default/grub`:

```
# For Intel:
GRUB_CMDLINE_LINUX_DEFAULT="intel_iommu=on iommu=pt"

# For AMD:
GRUB_CMDLINE_LINUX_DEFAULT="amd_iommu=on iommu=pt"
```

Update and reboot:

```bash
sudo update-grub
sudo reboot
```

### Step 2: Load VFIO Modules

```bash
sudo modprobe vfio
sudo modprobe vfio_pci
sudo modprobe vfio_iommu_type1
```

To load at boot, add to `/etc/modules`:

```
vfio
vfio_pci
vfio_iommu_type1
```

### Step 3: Check Setup

```bash
kohakuriver qemu check
```

This validates:

- KVM access (`/dev/kvm`)
- CPU virtualization (vmx/svm)
- QEMU binary availability
- OVMF firmware
- ISO tool (genisoimage)
- IOMMU groups
- VFIO modules
- ACS override status
- Discoverable VFIO GPUs
- Host NVIDIA driver version

### Step 4: ACS Override (Optional)

On server hardware, multiple GPUs often share IOMMU groups due to PCIe switches. ACS override splits these groups for individual GPU allocation.

Add kernel parameter:

```
GRUB_CMDLINE_LINUX_DEFAULT="... pcie_acs_override=downstream,multifunction"
```

Then apply at runtime:

```bash
kohakuriver qemu acs-override
```

Or enable automatic application on runner startup:

```python
# In runner_config.py
VM_ACS_OVERRIDE: bool = True
```

The `setpci` changes are volatile and reset on reboot. The runner config option re-applies them automatically.

### Step 5: Create VM with GPU Passthrough

```bash
kohakuriver vps create --backend qemu -t mynode::0 --vm-memory 16384 -c 8
```

This passes GPU 0 to the VM via VFIO, along with any associated audio devices in the same IOMMU group.

## GPU Discovery

The runner reports VFIO-capable GPUs via heartbeat. View them with:

```bash
kohakuriver node status <hostname>
```

The host tracks both Docker GPU availability and VFIO GPU capability per node.

## Troubleshooting

### GPU Not Detected

Ensure IOMMU is enabled:

```bash
dmesg | grep -i iommu
```

### IOMMU Groups Not Split

If multiple GPUs are in the same IOMMU group, enable ACS override:

```bash
kohakuriver qemu check  # Check current IOMMU groups
kohakuriver qemu acs-override  # Apply ACS override
kohakuriver qemu check  # Verify groups are split
```

### VFIO Bind Failures

Test binding a GPU to VFIO manually:

```bash
scripts/test-vfio-bind.sh
```

Recover after failed VFIO operations:

```bash
scripts/recover-vfio.sh
```
