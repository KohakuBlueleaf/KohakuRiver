---
title: Prerequisites
description: System requirements and dependencies needed before installing KohakuRiver.
icon: i-carbon-task-tools
---

# Prerequisites

Before installing KohakuRiver, ensure your environment meets the following requirements.

## Host Machine

The host server runs the central orchestration service. Requirements:

- **Python 3.10+** -- KohakuRiver uses modern Python features (match statements, `X | Y` union types)
- **Linux** -- The host requires Linux for network management (VXLAN, bridges via pyroute2)
- **SQLite** -- Included with Python; used for the cluster database
- **ssh-keygen** -- Required for SSH keypair generation (VPS with generate mode)

## Runner Machines

Each compute node needs:

- **Python 3.10+** -- Same version requirements as the host
- **Docker Engine** -- For running containerized workloads
  - Docker must be accessible by the user running the runner agent
  - The user should be in the `docker` group or the runner should run as root
- **Linux** -- Required for Docker, VXLAN agent, and resource monitoring

### Optional Runner Dependencies

- **NVIDIA Container Toolkit** -- For GPU passthrough to Docker containers
  - Install `nvidia-container-toolkit` and configure Docker to use the `nvidia` runtime
- **numactl** -- For NUMA-aware task placement
- **QEMU/KVM** -- For VM-based VPS (see [QEMU/KVM Setup](../setup/qemu-kvm.md))
  - `qemu-system-x86_64`, OVMF firmware, `genisoimage` or `mkisofs`
  - IOMMU and VFIO modules for GPU passthrough

## Shared Storage (Recommended)

For tarball-based container environments, all cluster nodes (host and runners) should have access to the same shared filesystem. The mount path does not need to be identical on every node -- each node configures its own `SHARED_DIR`. Supported options:

- **NFS** -- Most common; works well for Linux clusters
- **Samba/CIFS** -- Cross-platform compatibility
- **SSHFS** -- Simple setup for small clusters
- **Bind mounts** -- For single-machine setups or testing

The default shared directory is `/mnt/cluster-share`. See [Shared Storage](../setup/shared-storage.md) for setup instructions.

Shared storage is not strictly required. Containers can alternatively be pulled from Docker registries (using the `registry_image` field), and VMs use local disk images. If you only use registry-based containers, you can skip shared storage setup.

## Network Requirements

### Required Ports

| Port  | Protocol | Component | Purpose                    |
| ----- | -------- | --------- | -------------------------- |
| 8000  | TCP      | Host      | API server                 |
| 8001  | TCP      | Runner    | Runner API                 |
| 8002  | TCP      | Host      | SSH proxy                  |
| 4789  | UDP      | Both      | VXLAN overlay (if enabled) |
| 2222+ | TCP      | Runner    | SSH to VPS containers      |

### Firewall Rules

At minimum, runners must be able to reach the host on port 8000, and the host must be able to reach runners on port 8001. If using the overlay network, UDP port 4789 must be open between host and all runners.

## Python Package Dependencies

Core dependencies are installed automatically via pip:

```
kohaku-engine        # Configuration engine
kohakuvault          # Local state storage
peewee               # ORM for SQLite
fastapi              # Web framework
uvicorn[standard]    # ASGI server
httpx                # HTTP client
docker               # Docker SDK
websockets           # WebSocket support
psutil               # System metrics
typer                # CLI framework
rich                 # Terminal formatting
textual              # TUI framework
loguru               # Logging
pyroute2             # Network management
bcrypt               # Password hashing
asyncssh             # Async SSH
pydantic             # Data validation
pyyaml               # YAML parsing
snowflake-id         # ID generation
pyte                 # Terminal emulation
```

Optional:

```
nvidia-ml-py         # GPU monitoring (install with pip install "kohakuriver[gpu]")
```

## Verifying Prerequisites

Check Python version:

```bash
python3 --version  # Must be 3.10 or higher
```

Check Docker:

```bash
docker --version
docker run hello-world  # Verify Docker works
```

Check shared storage:

```bash
# On all nodes, verify the same path exists and is writable
ls /mnt/cluster-share
touch /mnt/cluster-share/test-file
```

Check NVIDIA (if using GPUs):

```bash
nvidia-smi                         # NVIDIA driver
docker run --gpus all nvidia/cuda:12.0-base nvidia-smi  # GPU in Docker
```
