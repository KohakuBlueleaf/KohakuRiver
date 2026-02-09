---
title: QEMU/KVM Setup
description: Setting up QEMU/KVM for VM-based VPS instances with cloud-init and GPU passthrough.
icon: i-carbon-virtual-machine
---

# QEMU/KVM Setup

KohakuRiver supports QEMU/KVM virtual machines as an alternative to Docker containers for VPS instances. VMs provide full OS isolation and VFIO GPU passthrough.

## Installation

Install required packages:

```bash
sudo apt install qemu-system-x86_64 qemu-utils ovmf genisoimage
```

Verify the setup:

```bash
kohakuriver qemu check
```

## Creating Base Images

VM base images are Ubuntu cloud images with thin-provisioned qcow2 disks.

### Using the CLI

```bash
kohakuriver qemu image create \
    --name ubuntu-24.04 \
    --ubuntu-version 24.04 \
    --size 500G \
    --images-dir /var/lib/kohakuriver/vm-images
```

This:

1. Downloads the Ubuntu cloud image (cached in `/tmp/kohakuriver-vm-cache/`)
2. Copies and resizes to create a thin-provisioned qcow2 image
3. Stores at `/var/lib/kohakuriver/vm-images/ubuntu-24.04.qcow2`

### List Available Images

```bash
kohakuriver qemu image list
```

Shows images with virtual size, actual size (on disk), and modification date.

## Cloud-Init Provisioning

When a VM VPS is created, KohakuRiver generates a cloud-init ISO (`seed.iso`) containing:

- **meta-data**: Instance ID and hostname
- **user-data**: SSH key setup, package installation, embedded VM agent
- **network-config**: Static IP assignment (overlay or NAT bridge)

The cloud-init user-data automatically:

- Configures SSH access with the provided key
- Installs `qemu-guest-agent`
- Embeds and starts the KohakuRiver VM agent (status reporting)
- Optionally installs matching NVIDIA drivers for GPU passthrough

## VM Networking

VMs support two network modes:

### Overlay Mode (when `OVERLAY_ENABLED=True`)

- VM gets a TAP interface on the `kohaku-overlay` bridge
- Direct overlay IP communication with other containers/VMs
- Same network as Docker containers on the overlay

### NAT Bridge Mode (default)

- VM connects to `kohaku-br0` bridge
- NAT bridge with subnet `10.200.0.0/24`
- SSH access via port mapping

Configure in `runner_config.py`:

```python
VM_BRIDGE_NAME: str = "kohaku-br0"
VM_BRIDGE_SUBNET: str = "10.200.0.0/24"
VM_BRIDGE_GATEWAY: str = "10.200.0.1"
```

## Creating a VM VPS

```bash
# Basic VM VPS
kohakuriver vps create --backend qemu -t mynode --vm-memory 4096 -c 4

# VM with GPU passthrough
kohakuriver vps create --backend qemu -t mynode::0 --vm-memory 16384 -c 8

# VM with custom base image and disk size
kohakuriver vps create --backend qemu \
    -t mynode \
    --vm-image ubuntu-24.04 \
    --vm-disk 100G \
    --vm-memory 8192 \
    -c 4 \
    --ssh
```

## Runner VM Configuration

```python
# In runner_config.py

# Directories
VM_IMAGES_DIR: str = "/var/lib/kohakuriver/vm-images"
VM_INSTANCES_DIR: str = "/var/lib/kohakuriver/vm-instances"

# Defaults
VM_DEFAULT_MEMORY_MB: int = 4096
VM_DEFAULT_DISK_SIZE: str = "500G"

# Timeouts
VM_BOOT_TIMEOUT_SECONDS: int = 600
VM_SSH_READY_TIMEOUT_SECONDS: int = 600
VM_HEARTBEAT_TIMEOUT_SECONDS: int = 120

# ACS override for GPU passthrough
VM_ACS_OVERRIDE: bool = True
```

## VM Instance Management

### List Instances

```bash
kohakuriver qemu instances
```

Shows all VM instance directories across nodes with disk usage, QEMU status, and DB status.

### Cleanup Orphaned Instances

```bash
kohakuriver qemu cleanup <task-id> --hostname <node>
```

Deletes a VM instance directory to free disk space. Use `--force` to delete even if QEMU is running.

## VM Agent

Each VM runs an embedded Python agent that:

- Reports boot status to the runner (phone-home)
- Sends periodic heartbeats with GPU metrics
- Enables the runner to track VM health

The agent is embedded in the cloud-init user-data and starts automatically on boot.

## VM vs Docker Comparison

| Feature           | Docker VPS              | QEMU VM VPS                  |
| ----------------- | ----------------------- | ---------------------------- |
| Startup time      | Seconds                 | Minutes (cloud-init)         |
| GPU access        | Shared (NVIDIA runtime) | Dedicated (VFIO passthrough) |
| Isolation         | Namespace-based         | Full hardware virtualization |
| Disk              | Shared filesystem       | Thin-provisioned qcow2       |
| Snapshots         | Docker commit           | Planned                      |
| Networking        | Docker bridge/overlay   | TAP/bridge                   |
| Resource overhead | Minimal                 | VM overhead                  |
