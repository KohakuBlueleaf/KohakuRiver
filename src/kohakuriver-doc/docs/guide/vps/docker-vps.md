---
title: Docker VPS
description: Creating and managing Docker-based VPS instances in KohakuRiver.
icon: i-carbon-container-software
---

# Docker VPS

Docker VPS instances run as long-lived Docker containers with SSH access, persistent storage, and optional GPU allocation. This is the default backend for VPS tasks.

## Creating a Docker VPS

### Basic Creation

```bash
kohakuriver vps create -t mynode --ssh
```

This creates a VPS with:

- No CPU core limit (the TUI prompt defaults to 0, meaning the container can use all available cores; CLI default is 1)
- Default memory limit
- SSH access enabled
- Default container environment

### With Resources

```bash
kohakuriver vps create -t mynode \
    -c 8 \
    -m 32G \
    --container my-pytorch \
    --ssh
```

### With GPUs

```bash
kohakuriver vps create -t mynode::0,1 \
    -c 8 \
    -m 32G \
    --ssh
```

GPUs are allocated via the `--gpus` flag. The container sees only the specified GPU indices.

## Container Environment

Docker VPS uses the same container environment system as command tasks. Environments can be Docker images distributed as tarballs via shared storage (recommended), or pulled directly from a Docker registry.

### Using a Named Environment

```bash
kohakuriver vps create -t mynode --container my-env --ssh
```

When using `--container`, the runner loads the environment tarball from `SHARED_DIR/environments/<name>.tar` and creates a container from it. This requires shared storage to be configured.

### Using a Registry Image

```bash
kohakuriver vps create -t mynode --image ubuntu:22.04 --ssh
```

The runner pulls the image directly from the Docker registry.

### Preparing Environments

See [Container Preparation](container-preparation.md) for creating custom environments with SSH servers, GPU drivers, and development tools.

## SSH Key Management

When creating a VPS with `--ssh`, you can manage SSH keys in several ways:

| Flag                      | Behavior                                            |
| ------------------------- | --------------------------------------------------- |
| `--ssh` (default)         | Uses `~/.ssh/id_*.pub` from your local machine      |
| `--gen-ssh-key`           | Generates a new key pair; private key saved locally |
| `--public-key-file PATH`  | Uploads a specific public key file                  |
| `--public-key-string KEY` | Passes a public key string directly                 |
| `--no-ssh-key`            | No SSH key injection (password auth only)           |
| `--key-out-file PATH`     | Where to save the generated private key             |

Example with key generation:

```bash
kohakuriver vps create -t mynode --ssh --gen-ssh-key \
    --key-out-file ~/.ssh/mynode_vps
```

## Container Configuration

The runner creates the Docker container with:

1. **CPU and memory limits** set via Docker resource constraints
2. **GPU allocation** via `--gpus` flag (NVIDIA Container Toolkit)
3. **Shared storage** mounted at `/shared` inside the container
4. **Working directory** set to `/shared`
5. **Additional mounts** if specified via `--mount`
6. **Network** connected to the configured Docker network
7. **SSH port** mapped if SSH is enabled

## Stop and Restart

### Stopping

```bash
kohakuriver vps stop <task_id>
```

When a Docker VPS is stopped:

1. The host sends a stop request to the runner
2. The runner stops the Docker container (but does not remove it)
3. If `AUTO_SNAPSHOT_ON_STOP` is enabled in runner config, a snapshot is taken automatically
4. The task status changes to `stopped`

### Restarting

```bash
kohakuriver vps restart <task_id>
```

When a Docker VPS is restarted:

1. The host sends a restart request to the runner
2. The runner starts the stopped container
3. The task status returns to `running`

Docker VPS restarts preserve the container filesystem state -- all files and installed packages persist.

## Pause and Resume

Docker VPS supports freezing execution without stopping:

```bash
# Freeze the container (all processes suspended)
kohakuriver vps pause <task_id>

# Unfreeze
kohakuriver vps resume <task_id>
```

This uses Docker's `pause` and `unpause` functionality, which sends `SIGSTOP` to all processes in the container. Memory state is preserved.

## Snapshots

Docker VPS supports snapshots to save the container's filesystem state:

```bash
# Create a snapshot
kohakuriver vps snapshot create <task_id>

# List snapshots
kohakuriver vps snapshot list <task_id>

# Restore from latest snapshot on restart
kohakuriver vps restart <task_id> --from-snapshot
```

See [Snapshots](snapshots.md) for details.

## Privileged Mode

For workloads that need extended capabilities:

```bash
kohakuriver vps create -t mynode --privileged --ssh
```

The `--privileged` flag runs the container with Docker's `--privileged` option, granting access to all host devices. Use with caution -- see [Security Hardening](../setup/security-hardening.md).

## Related Topics

- [VM VPS](vm-vps.md) -- Alternative VM-based VPS backend
- [SSH Access](ssh-access.md) -- Connecting to the VPS
- [Container Preparation](container-preparation.md) -- Building custom environments
- [Docker Environment](../setup/docker-environment.md) -- Docker setup and management
