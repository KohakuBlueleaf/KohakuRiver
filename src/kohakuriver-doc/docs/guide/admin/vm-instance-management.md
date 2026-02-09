---
title: VM Instance Management
description: Managing QEMU/KVM virtual machine instances across the cluster.
icon: i-carbon-virtual-machine
---

# VM Instance Management

VM instances require additional management compared to Docker containers due to VFIO GPU passthrough, disk images, and QEMU processes.

## Viewing VM Instances

### CLI

```bash
# List all running VM instances
kohakuriver qemu instances
```

Shows:

- Task ID
- QEMU process PID
- Allocated CPUs and memory
- GPU assignments (PCI addresses)
- Disk image path
- VM IP address

### VPS List

```bash
kohakuriver vps list
```

VPS instances with `backend=qemu` are VM-based. The list shows the backend type.

## VM Lifecycle

### Creation

```bash
kohakuriver vps create --backend qemu -t node1::0 \
    --vm-memory 16384 -c 8 --ssh
```

The runner:

1. Clones the base qcow2 image to `VM_INSTANCES_DIR`
2. Generates a cloud-init ISO with user-data and meta-data
3. Unbinds requested GPUs from NVIDIA driver
4. Binds GPUs to `vfio-pci`
5. Launches QEMU with the disk image, cloud-init ISO, and GPU passthrough

### Stopping

```bash
kohakuriver vps stop <task_id>
```

The runner:

1. Sends ACPI shutdown signal to the VM
2. Waits for VM agent confirmation (or timeout)
3. Terminates QEMU process if still running
4. Unbinds GPUs from `vfio-pci`
5. Rebinds GPUs to NVIDIA driver
6. Preserves the qcow2 disk image

### Restarting

```bash
kohakuriver vps restart <task_id>
```

The runner:

1. Rebinds GPUs to `vfio-pci`
2. Relaunches QEMU with the existing disk image
3. VM boots with previous filesystem state

### Cleanup

```bash
kohakuriver qemu cleanup
```

Cleans up:

- Orphaned QEMU processes (no matching task)
- Stale VFIO bindings from crashed VMs
- Temporary files from failed VM creation

## GPU Passthrough State

When VMs are running, their GPUs are bound to `vfio-pci` and unavailable to the host. Track GPU state:

```bash
# Check which GPUs are VFIO-bound
kohakuriver qemu check

# Check GPU allocation via node status
kohakuriver node status <hostname>
```

### Recovering Stuck GPUs

If a VM crashes without proper shutdown, GPUs may remain bound to `vfio-pci`:

```bash
# Cleanup stale bindings
kohakuriver qemu cleanup

# Or manually rebind (requires root on the runner node)
echo "0000:41:00.0" > /sys/bus/pci/drivers/vfio-pci/unbind
echo "0000:41:00.0" > /sys/bus/pci/drivers/nvidia/bind
```

## Disk Image Management

### Base Images

Base images are stored in `VM_IMAGES_DIR`:

```bash
kohakuriver qemu image list
```

### Instance Disks

Each VM instance has its own qcow2 disk cloned from the base image. Instance disks are stored in `VM_INSTANCES_DIR` and named by task ID.

Instance disks persist across stop/restart cycles. They are deleted when the VM instance is permanently removed.

### Disk Space

Monitor disk usage on runner nodes. VM disks can grow large:

- Base image: Typically 2-5 GB
- Instance disk: Base size + user data (grows with use)
- Default disk allocation: 20 GB (`--vm-disk`)

## VM Networking

VMs connect to the network via one of two modes:

### Overlay Mode (Recommended)

When `OVERLAY_ENABLED = True`, VMs get an IP on the cluster overlay network via a TAP device connected to `kohaku-overlay`.

### NAT Mode

When overlay is disabled, VMs use a local bridge (`kohaku-br0`) with NAT:

| Setting             | Default            | Description    |
| ------------------- | ------------------ | -------------- |
| `VM_BRIDGE_NAME`    | `kohaku-br0`       | Bridge name    |
| `VM_BRIDGE_SUBNET`  | `192.168.100.0/24` | Bridge subnet  |
| `VM_BRIDGE_GATEWAY` | `192.168.100.1`    | Bridge gateway |

## VM Agent

Each VM runs a lightweight Python agent installed via cloud-init. The agent:

- Sends a phone-home signal on boot
- Reports the VM's IP address via periodic heartbeats
- Listens for shutdown commands from the runner

If the VM agent is unresponsive, the runner falls back to QEMU monitor commands for shutdown.

## Troubleshooting VM Issues

### VM Fails to Boot

- Check QEMU logs: look in `VM_INSTANCES_DIR/<task_id>/`
- Verify base image exists: `kohakuriver qemu image list`
- Check KVM availability: `kohakuriver qemu check`

### GPU Not Visible in VM

- Verify IOMMU is enabled: check `kohakuriver qemu check`
- Check IOMMU groups: GPUs in shared groups must all be passed through
- Enable ACS override if needed: `kohakuriver qemu acs-override`

### VM Network Issues

- Check VM agent phone-home: the runner logs the VM's IP on boot
- Verify overlay or bridge configuration
- Check firewall rules on the runner

## Related Topics

- [VM VPS](../vps/vm-vps.md) -- VM VPS creation and usage
- [GPU Passthrough](../setup/gpu-passthrough.md) -- VFIO setup
- [QEMU/KVM Setup](../setup/qemu-kvm.md) -- Installation
- [QEMU CLI](../cli/qemu.md) -- QEMU CLI commands
