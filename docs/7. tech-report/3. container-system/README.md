# KohakuRiver Container System

Docker container management for KohakuRiver clusters. This section covers how containers are created, how images are distributed across nodes via shared storage, and how resource isolation is enforced.

## Documents

| Document | Description |
|----------|-------------|
| [overview.md](overview.md) | Container architecture: image sync, subprocess execution model, resource constraints, networking, and tunnel integration |

## Quick Reference

### Container Types

| Type | Naming Pattern | Lifecycle | Use Case |
|------|---------------|-----------|----------|
| **COMMAND task** | `kohakuriver-task-{id}` | Ephemeral (`--rm`) | One-shot execution with stdout/stderr capture |
| **VPS session** | `kohakuriver-vps-{id}` | Persistent (`--restart unless-stopped`) | Long-running interactive session |
| **Environment build** | `kohakuriver-env-{name}` | Temporary | Building new container images |

### Image Distribution

```
┌──────────────────┐     Shared Storage      ┌──────────────────┐
│    Runner A       │    (NFS / cluster-fs)   │    Runner B       │
│                   │                         │                   │
│  docker images    │    ┌───────────────┐    │  docker images    │
│  ┌─────────────┐  │    │  myenv-       │    │  ┌─────────────┐  │
│  │kohakuriver/ │◄─┼────┤  1706000000   │────┼─►│kohakuriver/ │  │
│  │myenv:base   │  │    │  .tar         │    │  │myenv:base   │  │
│  └─────────────┘  │    └───────────────┘    │  └─────────────┘  │
└──────────────────┘                         └──────────────────┘
```

Images are stored as timestamped tarballs in shared storage. Runners compare local image timestamps against the latest tarball and load newer versions on demand, protected by a per-runner sync lock to prevent concurrent loads.

### Resource Constraints

| Resource | Docker Flag | Source Field |
|----------|------------|--------------|
| CPU cores | `--cpus N` | `required_cores` |
| Memory | `--memory Nm` | `required_memory_bytes` |
| GPU | `--gpus "device=0,1"` | `required_gpus` |
| NUMA | `numactl --cpunodebind=N --membind=N` | `target_numa_node_id` |

### Key Source Files

| File | Purpose |
|------|---------|
| `runner/services/task_executor.py` | Task container creation and execution |
| `runner/services/vps_manager.py` | VPS container creation and lifecycle |
| `docker/utils.py` | Image sync and tarball management |
| `docker/naming.py` | Container and image naming conventions |
| `runner/services/tunnel_helper.py` | Tunnel client injection into containers |
