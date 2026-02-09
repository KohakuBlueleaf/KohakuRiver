---
title: kohakuriver ssh
description: SSH commands for connecting to VPS instances.
icon: i-carbon-terminal
---

# kohakuriver ssh

The `kohakuriver ssh` command group provides SSH connectivity to VPS instances through the host's SSH proxy.

## Commands

### ssh (connect)

Connect to a VPS instance via SSH.

```bash
kohakuriver ssh <task_id> [options]
```

| Flag           | Default       | Description             |
| -------------- | ------------- | ----------------------- |
| `--key`        | Auto-detected | Path to SSH private key |
| `--user`       | `root`        | Remote username         |
| `--proxy-port` | `8002`        | Host SSH proxy port     |
| `--local-port` | None          | Use local port forward  |

Examples:

```bash
# Basic SSH connection
kohakuriver ssh 1234567890

# With specific key
kohakuriver ssh 1234567890 --key ~/.ssh/mynode_key

# As non-root user
kohakuriver ssh 1234567890 --user ubuntu

# Custom proxy port
kohakuriver ssh 1234567890 --proxy-port 9002
```

The command:

1. Queries the host API for the task's SSH port and assigned node
2. Finds the appropriate SSH private key
3. Invokes `ssh` with the correct proxy configuration
4. Connects through the host SSH proxy (port 8002) to the container/VM

### ssh config

Generate SSH configuration entries for all running VPS instances.

```bash
kohakuriver ssh config [options]
```

| Flag       | Default | Description          |
| ---------- | ------- | -------------------- |
| `--output` | stdout  | Write config to file |

Examples:

```bash
# Print to stdout
kohakuriver ssh config

# Save to file
kohakuriver ssh config --output ~/.ssh/kohakuriver_config
```

The generated config allows using standard SSH clients and IDEs:

```bash
# After generating config
ssh kohakuriver-<task_id>

# Or include in ~/.ssh/config
echo "Include ~/.ssh/kohakuriver_config" >> ~/.ssh/config
```

## How SSH Proxy Works

The host runs an SSH proxy on port 8002 (`HOST_SSH_PROXY_PORT`). Each VPS with SSH enabled gets a unique port number (starting from 9000). The proxy matches incoming connections to the correct VPS container.

```
User -> Host:8002 -> Runner:container_ssh_port -> Container:22
```

## Related Topics

- [SSH Access](../vps/ssh-access.md) -- Detailed SSH documentation
- [VPS](vps.md) -- VPS management commands
- [Port Forwarding](../vps/port-forwarding.md) -- Forwarding other ports
