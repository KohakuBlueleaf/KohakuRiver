---
title: Host Configuration
description: Complete reference for host_config.py settings and the HostConfig dataclass.
icon: i-carbon-settings
---

# Host Configuration

The host server is configured via a Python file at `~/.kohakuriver/host_config.py`. Generate a template with:

```bash
kohakuriver init config --host
```

Configuration uses module-level variables and a `config_gen()` function powered by KohakuEngine.

## Configuration Reference

### Network Configuration

| Setting                  | Type | Default       | Description                                                                       |
| ------------------------ | ---- | ------------- | --------------------------------------------------------------------------------- |
| `HOST_BIND_IP`           | str  | `"0.0.0.0"`   | IP address the host binds to                                                      |
| `HOST_PORT`              | int  | `8000`        | HTTP API port                                                                     |
| `HOST_SSH_PROXY_PORT`    | int  | `8002`        | SSH proxy port for VPS access                                                     |
| `HOST_REACHABLE_ADDRESS` | str  | `"127.0.0.1"` | Address runners/clients use to reach the host. **Must be changed in production.** |

```python
HOST_BIND_IP: str = "0.0.0.0"
HOST_PORT: int = 8000
HOST_SSH_PROXY_PORT: int = 8002
HOST_REACHABLE_ADDRESS: str = "192.168.1.100"  # IMPORTANT: set to real IP
```

### Path Configuration

| Setting         | Type | Default                                 | Description                                                                                                                                     |
| --------------- | ---- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `SHARED_DIR`    | str  | `"/mnt/cluster-share"`                  | Shared storage root (same on all nodes). Required for tarball-based container environments; not needed if using only registry-based containers. |
| `DB_FILE`       | str  | `"/var/lib/kohakuriver/kohakuriver.db"` | SQLite database path                                                                                                                            |
| `CONTAINER_DIR` | str  | `""`                                    | Container tarball directory (defaults to `SHARED_DIR/kohakuriver-containers`). Only used for tarball-based environments.                        |
| `HOST_LOG_FILE` | str  | `""`                                    | Log file path (empty = console only)                                                                                                            |

### Timing Configuration

| Setting                          | Type | Default | Description                                                            |
| -------------------------------- | ---- | ------- | ---------------------------------------------------------------------- |
| `HEARTBEAT_INTERVAL_SECONDS`     | int  | `5`     | How often runners send heartbeats                                      |
| `HEARTBEAT_TIMEOUT_FACTOR`       | int  | `6`     | Runner marked offline after `interval * factor` seconds (default: 30s) |
| `CLEANUP_CHECK_INTERVAL_SECONDS` | int  | `10`    | How often to check for dead runners                                    |

### Docker Configuration

| Setting                   | Type      | Default                | Description                                             |
| ------------------------- | --------- | ---------------------- | ------------------------------------------------------- |
| `DEFAULT_CONTAINER_NAME`  | str       | `"kohakuriver-base"`   | Default container environment for tasks                 |
| `INITIAL_BASE_IMAGE`      | str       | `"python:3.12-alpine"` | Docker image if default tarball does not exist          |
| `TASKS_PRIVILEGED`        | bool      | `False`                | Run tasks with `--privileged` flag                      |
| `ADDITIONAL_MOUNTS`       | list[str] | `[]`                   | Extra mounts for containers (`"host:container"` format) |
| `DEFAULT_WORKING_DIR`     | str       | `"/shared"`            | Working directory inside containers                     |
| `ENV_CONTAINER_CPU_LIMIT` | float     | `0.25`                 | CPU limit fraction for environment setup containers     |
| `ENV_CONTAINER_MEM_LIMIT` | float     | `0.25`                 | Memory limit fraction for environment setup containers  |

### Overlay Network Configuration

| Setting              | Type | Default                | Description                                                   |
| -------------------- | ---- | ---------------------- | ------------------------------------------------------------- |
| `OVERLAY_ENABLED`    | bool | `False`                | Enable VXLAN overlay network                                  |
| `OVERLAY_SUBNET`     | str  | `"10.128.0.0/12/6/14"` | Subnet config: `BASE_IP/NETWORK_PREFIX/NODE_BITS/SUBNET_BITS` |
| `OVERLAY_VXLAN_ID`   | int  | `100`                  | Base VXLAN ID (each runner gets `base + runner_id`)           |
| `OVERLAY_VXLAN_PORT` | int  | `4789`                 | VXLAN UDP port                                                |
| `OVERLAY_MTU`        | int  | `1450`                 | Overlay MTU (1500 minus VXLAN overhead)                       |

### Authentication Configuration

| Setting                   | Type | Default | Description                                                  |
| ------------------------- | ---- | ------- | ------------------------------------------------------------ |
| `AUTH_ENABLED`            | bool | `False` | Enable authentication (when false, all endpoints are public) |
| `ADMIN_SECRET`            | str  | `""`    | Admin secret for bootstrap operations                        |
| `ADMIN_REGISTER_SECRET`   | str  | `""`    | Secret for admin self-registration via web UI                |
| `SESSION_EXPIRE_HOURS`    | int  | `720`   | Session cookie expiration (default: 30 days)                 |
| `INVITATION_EXPIRE_HOURS` | int  | `24`    | Default invitation token expiration                          |

### Logging Configuration

| Setting     | Type     | Default         | Description                                           |
| ----------- | -------- | --------------- | ----------------------------------------------------- |
| `LOG_LEVEL` | LogLevel | `LogLevel.INFO` | Logging verbosity: `full`, `debug`, `info`, `warning` |

## Example Configuration

```python
"""KohakuRiver Host Configuration"""
from kohakuengine import Config
from kohakuriver.models.enums import LogLevel

HOST_BIND_IP: str = "0.0.0.0"
HOST_PORT: int = 8000
HOST_SSH_PROXY_PORT: int = 8002
HOST_REACHABLE_ADDRESS: str = "192.168.1.100"

SHARED_DIR: str = "/mnt/cluster-share"
DB_FILE: str = "/var/lib/kohakuriver/kohakuriver.db"

HEARTBEAT_INTERVAL_SECONDS: int = 5
HEARTBEAT_TIMEOUT_FACTOR: int = 6

DEFAULT_CONTAINER_NAME: str = "kohakuriver-base"
TASKS_PRIVILEGED: bool = False
ADDITIONAL_MOUNTS: list[str] = ["/data:/data"]

OVERLAY_ENABLED: bool = True
OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"

AUTH_ENABLED: bool = True
ADMIN_SECRET: str = "my-bootstrap-secret"

LOG_LEVEL: LogLevel = LogLevel.INFO

def config_gen():
    return Config.from_globals()
```

## Auto-Loading

If no `--config` flag is passed, the host server automatically loads from `~/.kohakuriver/host_config.py`.
