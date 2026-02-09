---
title: Runner Configuration
description: Complete reference for runner_config.py settings and the RunnerConfig dataclass.
icon: i-carbon-settings-adjust
---

# Runner Configuration

The runner agent is configured via a Python file at `~/.kohakuriver/runner_config.py`. Generate a template with:

```bash
kohakuriver init config --runner
```

## Configuration Reference

### Network Configuration

| Setting          | Type | Default       | Description                                       |
| ---------------- | ---- | ------------- | ------------------------------------------------- |
| `RUNNER_BIND_IP` | str  | `"0.0.0.0"`   | IP the runner binds to                            |
| `RUNNER_PORT`    | int  | `8001`        | Runner API port                                   |
| `HOST_ADDRESS`   | str  | `"127.0.0.1"` | Host server address (how runner reaches the host) |
| `HOST_PORT`      | int  | `8000`        | Host server port                                  |

### Path Configuration

| Setting             | Type | Default                | Description                                                                                                                                   |
| ------------------- | ---- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `SHARED_DIR`        | str  | `"/mnt/cluster-share"` | Shared storage path (must match host). Required for tarball-based container environments; not needed if using only registry-based containers. |
| `LOCAL_TEMP_DIR`    | str  | `"/tmp/kohakuriver"`   | Local fast temporary storage                                                                                                                  |
| `CONTAINER_TAR_DIR` | str  | `""`                   | Tarball directory (defaults to `SHARED_DIR/kohakuriver-containers`). Only used for tarball-based environments.                                |
| `NUMACTL_PATH`      | str  | `""`                   | Path to numactl (empty = use system PATH)                                                                                                     |
| `RUNNER_LOG_FILE`   | str  | `""`                   | Log file path (empty = console only)                                                                                                          |

### Timing Configuration

| Setting                           | Type | Default | Description                   |
| --------------------------------- | ---- | ------- | ----------------------------- |
| `HEARTBEAT_INTERVAL_SECONDS`      | int  | `5`     | Heartbeat frequency to host   |
| `RESOURCE_CHECK_INTERVAL_SECONDS` | int  | `1`     | Resource monitoring frequency |

### Execution Configuration

| Setting               | Type | Default     | Description                                 |
| --------------------- | ---- | ----------- | ------------------------------------------- |
| `RUNNER_USER`         | str  | `""`        | User to run tasks as (empty = current user) |
| `DEFAULT_WORKING_DIR` | str  | `"/shared"` | Default working directory inside containers |

### Docker Configuration

| Setting                     | Type      | Default | Description                                      |
| --------------------------- | --------- | ------- | ------------------------------------------------ |
| `TASKS_PRIVILEGED`          | bool      | `False` | Run containers with `--privileged`               |
| `ADDITIONAL_MOUNTS`         | list[str] | `[]`    | Extra host mounts (`"host_path:container_path"`) |
| `DOCKER_IMAGE_SYNC_TIMEOUT` | int       | `600`   | Timeout for Docker image sync (10 minutes)       |

### Docker Network Configuration

| Setting                  | Type | Default             | Description                                    |
| ------------------------ | ---- | ------------------- | ---------------------------------------------- |
| `DOCKER_NETWORK_NAME`    | str  | `"kohakuriver-net"` | Docker bridge network for containers           |
| `DOCKER_NETWORK_SUBNET`  | str  | `"172.30.0.0/16"`   | Subnet for the bridge network                  |
| `DOCKER_NETWORK_GATEWAY` | str  | `"172.30.0.1"`      | Gateway IP (tunnel client reaches runner here) |

### Tunnel Configuration

| Setting              | Type | Default | Description                                           |
| -------------------- | ---- | ------- | ----------------------------------------------------- |
| `TUNNEL_ENABLED`     | bool | `True`  | Enable tunnel client in containers                    |
| `TUNNEL_CLIENT_PATH` | str  | `""`    | Path to tunnel-client binary (auto-detected if empty) |

### Snapshot Configuration

| Setting                  | Type | Default | Description                                    |
| ------------------------ | ---- | ------- | ---------------------------------------------- |
| `AUTO_SNAPSHOT_ON_STOP`  | bool | `True`  | Auto-snapshot when stopping VPS                |
| `MAX_SNAPSHOTS_PER_VPS`  | int  | `3`     | Max snapshots per VPS (oldest pruned)          |
| `AUTO_RESTORE_ON_CREATE` | bool | `True`  | Restore from latest snapshot on VPS recreation |

### VM (QEMU/KVM) Configuration

| Setting                        | Type | Default                               | Description                                  |
| ------------------------------ | ---- | ------------------------------------- | -------------------------------------------- |
| `VM_IMAGES_DIR`                | str  | `"/var/lib/kohakuriver/vm-images"`    | Base VM image directory                      |
| `VM_INSTANCES_DIR`             | str  | `"/var/lib/kohakuriver/vm-instances"` | VM instance storage                          |
| `VM_DEFAULT_MEMORY_MB`         | int  | `4096`                                | Default VM memory (4 GB)                     |
| `VM_DEFAULT_DISK_SIZE`         | str  | `"500G"`                              | Default virtual disk size (thin-provisioned) |
| `VM_ACS_OVERRIDE`              | bool | `True`                                | Disable ACS on PCI bridges at startup        |
| `VM_BOOT_TIMEOUT_SECONDS`      | int  | `600`                                 | VM boot timeout                              |
| `VM_SSH_READY_TIMEOUT_SECONDS` | int  | `600`                                 | VM SSH readiness timeout                     |
| `VM_HEARTBEAT_TIMEOUT_SECONDS` | int  | `120`                                 | VM agent heartbeat timeout                   |
| `VM_BRIDGE_NAME`               | str  | `"kohaku-br0"`                        | NAT bridge for VMs (non-overlay mode)        |
| `VM_BRIDGE_SUBNET`             | str  | `"10.200.0.0/24"`                     | NAT bridge subnet                            |
| `VM_BRIDGE_GATEWAY`            | str  | `"10.200.0.1"`                        | NAT bridge gateway                           |

### Overlay Network Configuration

| Setting                | Type | Default                 | Description                            |
| ---------------------- | ---- | ----------------------- | -------------------------------------- |
| `OVERLAY_ENABLED`      | bool | `False`                 | Enable VXLAN overlay (must match host) |
| `OVERLAY_SUBNET`       | str  | `"10.128.0.0/12/6/14"`  | Subnet config (must match host)        |
| `OVERLAY_NETWORK_NAME` | str  | `"kohakuriver-overlay"` | Docker network name for overlay        |
| `OVERLAY_VXLAN_ID`     | int  | `100`                   | Base VXLAN ID (must match host)        |
| `OVERLAY_VXLAN_PORT`   | int  | `4789`                  | VXLAN UDP port (must match host)       |
| `OVERLAY_MTU`          | int  | `1450`                  | Overlay MTU (must match host)          |

### Logging Configuration

| Setting     | Type     | Default         | Description       |
| ----------- | -------- | --------------- | ----------------- |
| `LOG_LEVEL` | LogLevel | `LogLevel.INFO` | Logging verbosity |

## Example Configuration

```python
"""KohakuRiver Runner Configuration"""
from kohakuengine import Config
from kohakuriver.models.enums import LogLevel

RUNNER_BIND_IP: str = "0.0.0.0"
RUNNER_PORT: int = 8001
HOST_ADDRESS: str = "192.168.1.100"
HOST_PORT: int = 8000

SHARED_DIR: str = "/mnt/cluster-share"
LOCAL_TEMP_DIR: str = "/tmp/kohakuriver"

TASKS_PRIVILEGED: bool = False
ADDITIONAL_MOUNTS: list[str] = ["/data:/data"]

TUNNEL_ENABLED: bool = True

AUTO_SNAPSHOT_ON_STOP: bool = True
MAX_SNAPSHOTS_PER_VPS: int = 3

VM_IMAGES_DIR: str = "/var/lib/kohakuriver/vm-images"
VM_ACS_OVERRIDE: bool = True

LOG_LEVEL: LogLevel = LogLevel.INFO

def config_gen():
    return Config.from_globals()
```
