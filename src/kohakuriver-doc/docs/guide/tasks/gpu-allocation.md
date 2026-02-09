---
title: GPU Allocation
description: How KohakuRiver allocates GPUs to tasks and VPS instances.
icon: i-carbon-chip
---

# GPU Allocation

KohakuRiver provides GPU-aware scheduling for both Docker containers and QEMU VMs.

## Docker GPU Allocation

For Docker-based workloads, GPUs are allocated by index using NVIDIA Container Toolkit. The runner passes the `--gpus "device=..."` flag to Docker to restrict visible GPUs.

### Specifying GPUs

Use the `::gpu_ids` suffix in the target specification:

```bash
# Single GPU
kohakuriver task submit -t mynode::0 -- python train.py

# Multiple GPUs
kohakuriver task submit -t mynode::0,1,2,3 -- python multi_gpu_train.py

# GPU with NUMA affinity
kohakuriver task submit -t mynode:0::0,1 -- python train.py
```

### How It Works

1. The runner reports GPU information via heartbeats (index, name, memory, utilization)
2. The host tracks which GPUs are allocated to running tasks
3. When a task requests specific GPUs, the host validates they are available
4. The runner creates the container with `--gpus "device=..."` set to the requested GPU indices

### GPU Monitoring

GPUs are monitored via `nvidia-ml-py` (install with `pip install "kohakuriver[gpu]"`). Heartbeats report:

- GPU name and model
- Memory total and used
- GPU utilization percentage
- Temperature

View GPU status:

```bash
kohakuriver node status <hostname>
```

## VFIO GPU Passthrough (QEMU VMs)

For VM-based VPS, GPUs are passed through via VFIO for dedicated hardware access. This provides:

- Full GPU isolation (no sharing with host or other VMs)
- Direct hardware access (better performance for some workloads)
- Full driver stack inside the VM

### Requirements

- IOMMU enabled in BIOS and kernel
- VFIO modules loaded
- ACS override for individual GPU allocation on server hardware

See [GPU Passthrough](../setup/gpu-passthrough.md) for setup instructions.

### Creating VM VPS with GPU

```bash
kohakuriver vps create --backend qemu -t mynode::0 \
    --vm-memory 16384 -c 8 --ssh
```

The runner:

1. Unbinds the GPU from the host NVIDIA driver
2. Binds it to `vfio-pci`
3. Passes the GPU and its audio device to the QEMU VM
4. Cloud-init installs matching NVIDIA drivers inside the VM

### Discovering VFIO GPUs

```bash
kohakuriver qemu check
```

Shows discovered GPUs with their PCI address, IOMMU group, and any companion audio devices.

## GPU Availability Tracking

The host maintains GPU availability per node:

- When a task with GPUs starts, those GPU indices are marked as "in use"
- When a task completes, the GPUs are released
- The scheduler checks GPU availability before allowing task submission

If a requested GPU is already allocated, the submission is rejected with an error message.

## Best Practices

- Use specific GPU indices when GPU placement matters (e.g., NVLink topology)
- For distributed training, combine GPU allocation with IP reservation
- Monitor GPU utilization via `kohakuriver node status` or the web dashboard
- Use VFIO passthrough when you need full GPU isolation or when Docker GPU sharing causes conflicts
