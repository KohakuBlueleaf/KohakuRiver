---
title: kohakuriver vps
description: VPS management commands for creating and managing interactive sessions.
icon: i-carbon-virtual-machine
---

# kohakuriver vps

The `kohakuriver vps` command group manages VPS instances -- creating, controlling, and connecting to long-running interactive sessions.

## Commands

### vps create

Create a new VPS instance.

```bash
kohakuriver vps create [options]
```

| Flag                  | Short | Default        | Description                             |
| --------------------- | ----- | -------------- | --------------------------------------- |
| `--target`            | `-t`  | Required       | Target node (`hostname[:numa][::gpus]`) |
| `--cores`             | `-c`  | `1`            | Number of CPU cores                     |
| `--memory`            | `-m`  | None           | Memory limit (e.g., `8G`)               |
| `--container`         |       | None           | Container environment name              |
| `--image`             |       | None           | Docker registry image                   |
| `--ssh`               |       | `False`        | Enable SSH access                       |
| `--no-ssh-key`        |       | `False`        | No SSH key injection                    |
| `--gen-ssh-key`       |       | `False`        | Generate a new SSH key pair             |
| `--public-key-file`   |       | None           | Path to public key file                 |
| `--public-key-string` |       | None           | Public key as string                    |
| `--key-out-file`      |       | Auto           | Where to save generated private key     |
| `--backend`           |       | `docker`       | VPS backend: `docker` or `qemu`         |
| `--vm-image`          |       | `ubuntu-22.04` | Base VM image (QEMU only)               |
| `--vm-disk`           |       | `20`           | VM disk size in GB (QEMU only)          |
| `--vm-memory`         |       | `4096`         | VM memory in MB (QEMU only)             |

Examples:

```bash
# Docker VPS with SSH
kohakuriver vps create -t node1 --ssh -c 4 -m 16G

# Docker VPS with custom environment and GPU
kohakuriver vps create -t node1::0 --container my-pytorch --ssh

# Docker VPS with generated SSH key
kohakuriver vps create -t node1 --ssh --gen-ssh-key

# QEMU VM VPS with GPU passthrough
kohakuriver vps create --backend qemu -t node1::0 \
    --vm-memory 16384 -c 8 --ssh

# QEMU VM VPS with custom disk and image
kohakuriver vps create --backend qemu -t node1 \
    --vm-image ubuntu-22.04 --vm-disk 100 --ssh
```

### vps list

List all VPS instances.

```bash
kohakuriver vps list
```

Displays all VPS tasks with their status, backend type, assigned node, resources, and SSH port.

### vps status

Show detailed VPS status.

```bash
kohakuriver vps status <task_id>
```

Displays:

- VPS backend (Docker or QEMU)
- Current status
- Assigned node
- Resource allocation
- SSH port and connection info
- IP address (overlay or VM)
- Timestamps

### vps stop

Stop a running VPS.

```bash
kohakuriver vps stop <task_id>
```

For Docker VPS, stops the container. For QEMU VM, sends an ACPI shutdown signal. If auto-snapshot is enabled, a snapshot is taken.

### vps restart

Restart a stopped VPS.

```bash
kohakuriver vps restart <task_id>
```

Restarts the VPS with its previous filesystem state.

### vps pause

Pause a running Docker VPS.

```bash
kohakuriver vps pause <task_id>
```

Freezes all processes in the container. Not available for QEMU VM VPS.

### vps resume

Resume a paused Docker VPS.

```bash
kohakuriver vps resume <task_id>
```

### vps connect

Connect to a VPS via WebSocket terminal.

```bash
kohakuriver vps connect <task_id>
```

Opens an interactive terminal session in the container. Equivalent to `kohakuriver connect <task_id>`.

## Related Topics

- [VPS Overview](../vps/overview.md) -- VPS system documentation
- [Docker VPS](../vps/docker-vps.md) -- Docker backend details
- [VM VPS](../vps/vm-vps.md) -- QEMU backend details
- [SSH Access](../vps/ssh-access.md) -- SSH connection
- [Task](task.md) -- Task management commands
