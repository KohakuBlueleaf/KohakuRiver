---
title: VPS Management
description: Managing VPS instances through the KohakuRiver web dashboard.
icon: i-carbon-virtual-machine
---

# VPS Management

The web dashboard provides a dedicated VPS view for creating, managing, and connecting to VPS instances.

## VPS List View

VPS instances are displayed as cards showing:

- Task ID and status
- Backend type (Docker or QEMU)
- Assigned node
- Resource allocation (cores, memory, GPUs)
- SSH port (if enabled)
- IP address (overlay or VM IP)
- Uptime

### Status Indicators

| Status      | Indicator | Description                       |
| ----------- | --------- | --------------------------------- |
| `running`   | Green     | VPS is active and accessible      |
| `paused`    | Yellow    | VPS is frozen (Docker only)       |
| `stopped`   | Gray      | VPS is stopped, can be restarted  |
| `assigning` | Blue      | VPS is being set up on the runner |
| `failed`    | Red       | VPS failed to start               |
| `lost`      | Red       | Runner went offline               |

## Creating a VPS

Click "Create VPS" to open the creation dialog:

### Docker VPS

1. Select **Backend**: Docker (default)
2. **Target node**: Choose from the node dropdown
3. **CPU cores**: Set the number of cores
4. **Memory**: Set memory limit
5. **GPU IDs**: Enter comma-separated GPU indices (optional)
6. **Container**: Select environment name or enter registry image
7. **SSH**: Toggle SSH access on/off
8. **SSH Key Mode**: Choose from upload, generate, or custom key
9. Click "Create"

### QEMU VM VPS

1. Select **Backend**: QEMU
2. **Target node**: Choose a VM-capable node
3. **VM Memory**: Set VM RAM in MB
4. **VM Disk**: Set disk size in GB
5. **VM Image**: Select base image
6. **CPU cores**: Set vCPU count
7. **GPU IDs**: Select GPUs for VFIO passthrough
8. **SSH**: Toggle SSH access
9. Click "Create"

The backend toggle switches between Docker-specific and QEMU-specific options.

## VPS Actions

### Stop

Stops the VPS. For Docker VPS, the container is stopped (not removed). For QEMU VM, an ACPI shutdown signal is sent. If auto-snapshot is enabled, a snapshot is taken before stopping.

### Restart

Restarts a stopped VPS. The container or VM resumes with its previous filesystem state.

### Pause / Resume (Docker Only)

Freezes all processes in the Docker container. Useful for temporarily freeing CPU resources without losing state.

### Kill

Forcefully terminates the VPS. For Docker, the container is killed. For QEMU, the VM process is terminated. Use this when stop fails or the VPS is unresponsive.

## Web Terminal

The dashboard includes a web-based terminal powered by xterm.js:

1. Click the "Terminal" button on a running VPS card
2. A terminal panel opens in the browser
3. The terminal connects via WebSocket to the container/VM
4. Full interactive shell access with support for colors, cursor movement, and resize

The terminal connection flows through:

```
Browser (xterm.js) -> WebSocket -> Host Proxy -> Runner -> Container/VM
```

## Snapshot Management

For Docker VPS instances, the dashboard provides snapshot controls:

- **Create Snapshot**: Take a snapshot of the current filesystem state
- **Snapshot List**: View all snapshots with timestamps and sizes
- **Delete Snapshot**: Remove unwanted snapshots

Snapshots are displayed in the VPS detail panel with creation timestamps.

## SSH Connection Info

When SSH is enabled on a VPS, the dashboard displays connection details:

```
ssh root@<host_address> -p 8002
```

Or the specific SSH port assigned to the VPS. This information can be copied with a single click.

## Monitoring

Each VPS card shows real-time resource usage when available:

- CPU utilization
- Memory usage
- GPU utilization (if GPUs are allocated)

Click a VPS card for detailed monitoring with historical charts.

## Related Topics

- [Task Management](task-management.md) -- Managing command tasks
- [Node Monitoring](node-monitoring.md) -- Checking node resources
- [Docker VPS](../vps/docker-vps.md) -- Docker VPS details
- [VM VPS](../vps/vm-vps.md) -- QEMU VM VPS details
- [SSH Access](../vps/ssh-access.md) -- SSH connection details
