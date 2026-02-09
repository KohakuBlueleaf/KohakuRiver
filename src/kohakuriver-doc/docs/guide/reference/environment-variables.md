---
title: Environment Variables
description: All environment variables recognized by KohakuRiver components.
icon: i-carbon-catalog
---

# Environment Variables

KohakuRiver reads environment variables at multiple levels: CLI configuration, container runtime injection, and VM guest agent configuration. This page documents all recognized variables.

## CLI Environment Variables

These variables configure the `kohakuriver` CLI tool. They override the defaults in `cli/config.py` and can themselves be overridden by command-line flags.

| Variable                     | Default              | Description                                                                                                                        |
| ---------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `KOHAKURIVER_HOST`           | `localhost`          | Host server address for CLI connections                                                                                            |
| `KOHAKURIVER_PORT`           | `8000`               | Host server port                                                                                                                   |
| `KOHAKURIVER_SSH_PROXY_PORT` | `8002`               | SSH proxy port for VPS SSH access                                                                                                  |
| `KOHAKURIVER_SHARED_DIR`     | `/mnt/cluster-share` | Path to shared cluster storage. Used for tarball-based environments and shared log access; optional if using only registry images. |

### Usage Example

```bash
# Set host address for all CLI commands
export KOHAKURIVER_HOST=192.168.1.100
export KOHAKURIVER_PORT=8000

# Or pass as flags
kohakuriver --host 192.168.1.100 --port 8000 tasks list
```

The CLI also accepts `--host` / `-H` and `--port` / `-P` flags which take precedence over environment variables.

## Container Runtime Variables

These variables are injected into Docker containers by the runner when executing tasks. They are available to user scripts running inside containers.

| Variable                       | Example              | Description                                                                    |
| ------------------------------ | -------------------- | ------------------------------------------------------------------------------ |
| `KOHAKURIVER_TASK_ID`          | `1893247561234`      | Snowflake ID of the running task                                               |
| `KOHAKURIVER_LOCAL_TEMP_DIR`   | `/tmp/kohakuriver`   | Local temp directory path on the runner                                        |
| `KOHAKURIVER_SHARED_DIR`       | `/mnt/cluster-share` | Shared storage path on the runner (only set when shared storage is configured) |
| `KOHAKURIVER_TARGET_NUMA_NODE` | `0`                  | Target NUMA node ID (only set if NUMA pinning is used)                         |

### Tunnel Client Variables

These are set inside containers when the tunnel client is enabled, used by the tunnel binary to establish its WebSocket connection back to the runner:

| Variable                   | Example                | Description                                  |
| -------------------------- | ---------------------- | -------------------------------------------- |
| `KOHAKURIVER_TUNNEL_URL`   | `ws://172.30.0.1:8001` | Runner WebSocket URL for tunnel connection   |
| `KOHAKURIVER_CONTAINER_ID` | `kohakuriver-task-123` | Container identifier for tunnel registration |

The tunnel client binary reads these variables on startup and connects to the runner's WebSocket tunnel endpoint.

## VM Guest Agent Variables

These variables are used by the KohakuRiver agent running inside QEMU VMs. They are embedded in the cloud-init user-data during VM provisioning.

| Variable                    | Example                  | Description                                 |
| --------------------------- | ------------------------ | ------------------------------------------- |
| `KOHAKU_RUNNER_URL`         | `http://10.200.0.1:8001` | Runner API URL for phone-home and heartbeat |
| `KOHAKU_TASK_ID`            | `1893247561234`          | Task ID of the VM VPS                       |
| `KOHAKU_HEARTBEAT_INTERVAL` | `10`                     | Heartbeat interval in seconds (default: 10) |

The VM agent is a Python script installed via cloud-init as a systemd service. It:

1. Sends a phone-home callback to `{KOHAKU_RUNNER_URL}/api/vps/{task_id}/vm-phone-home` when cloud-init completes
2. Sends periodic heartbeats to `{KOHAKU_RUNNER_URL}/api/vps/{task_id}/vm-heartbeat` with GPU and system metrics

## Host and Runner Configuration

The host and runner do not use environment variables directly for their own configuration. Instead, they use Python configuration files at:

| Component | Config Path                       |
| --------- | --------------------------------- |
| Host      | `~/.kohakuriver/host_config.py`   |
| Runner    | `~/.kohakuriver/runner_config.py` |

However, you can reference environment variables inside these Python config files:

```python
# ~/.kohakuriver/host_config.py
import os

HOST_REACHABLE_ADDRESS = os.environ.get("KR_HOST_IP", "192.168.1.100")
SHARED_DIR = os.environ.get("KR_SHARED_DIR", "/mnt/cluster-share")
AUTH_ENABLED = True
ADMIN_SECRET = os.environ["KR_ADMIN_SECRET"]  # Required
```

## System Environment

The runner uses the `HOME` environment variable in two places:

| Usage                | Description                                            |
| -------------------- | ------------------------------------------------------ |
| Tunnel client search | Looks for `$HOME/.kohakuriver/tunnel-client` binary    |
| VM SSH key           | Uses `$HOME/.ssh/kohakuriver_vm_key` for VM SSH access |

## Completions

The CLI uses internal environment variables for shell completion. These are not meant to be set manually:

| Variable                              | Shell           |
| ------------------------------------- | --------------- |
| `_KOHAKURIVER_COMPLETE=complete_bash` | Bash completion |
| `_KOHAKURIVER_COMPLETE=complete_zsh`  | Zsh completion  |
| `_KOHAKURIVER_COMPLETE=complete_fish` | Fish completion |

Generate shell completions with:

```bash
kohakuriver config completions --bash   # Bash
kohakuriver config completions --zsh    # Zsh
kohakuriver config completions --fish   # Fish
```

## Related Topics

- [Configuration Reference](configuration.md) -- Full config file options
- [Ports Reference](ports.md) -- Network port assignments
