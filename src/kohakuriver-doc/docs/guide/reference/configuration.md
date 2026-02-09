---
title: Configuration Reference
description: Complete reference of all KohakuRiver configuration options.
icon: i-carbon-settings-adjust
---

# Configuration Reference

KohakuRiver uses Python configuration files for both host and runner. Configuration files are loaded as Python modules, allowing computed values and environment variable references.

## Configuration System

Configuration files are Python scripts where module-level variables define settings. An optional `config_gen()` function can return computed values.

```python
# Example: runner_config.py
import os

HOST_ADDRESS = os.environ.get("KR_HOST", "http://192.168.1.100:8000")
SHARED_DIR = "/cluster-share"
TUNNEL_ENABLED = True
```

### File Locations

| Config | Default Path                      | Generate                           |
| ------ | --------------------------------- | ---------------------------------- |
| Host   | `~/.kohakuriver/host_config.py`   | `kohakuriver init config --host`   |
| Runner | `~/.kohakuriver/runner_config.py` | `kohakuriver init config --runner` |

### Default Values

Default values are defined in `src/kohakuriver/utils/default_config.toml`:

```toml
[network]
host_port = 8000
runner_port = 8001
ssh_proxy_port = 8002

[paths]
shared_dir = "/cluster-share"
db_file = "kohakuriver.db"

[database]
pragmas_journal_mode = "wal"
pragmas_cache_size = -1024

[timing]
heartbeat_interval = 5
heartbeat_timeout = 30

[environment]
container_cpu_limit = 4
container_mem_limit = "8G"

[docker]
network_name = "kohakuriver"
network_subnet = "172.20.0.0/16"
network_gateway = "172.20.0.1"

[snapshots]
auto_snapshot_on_stop = true
max_snapshots_per_vps = 5
```

## Host Configuration

Complete reference of `HostConfig` fields:

### Network

| Setting                  | Type | Default     | Description                                      |
| ------------------------ | ---- | ----------- | ------------------------------------------------ |
| `HOST_BIND_IP`           | str  | `"0.0.0.0"` | IP address to bind the HTTP server               |
| `HOST_PORT`              | int  | `8000`      | HTTP server port                                 |
| `HOST_SSH_PROXY_PORT`    | int  | `8002`      | SSH proxy listening port                         |
| `HOST_REACHABLE_ADDRESS` | str  | `""`        | Address runners use to reach the host (required) |

### Paths

| Setting      | Type | Default            | Description                                                                                                                    |
| ------------ | ---- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `SHARED_DIR` | str  | `"/cluster-share"` | Path to shared storage. Required for tarball-based environments and shared log access. Optional if using only registry images. |
| `DB_FILE`    | str  | `"kohakuriver.db"` | Database filename (relative to SHARED_DIR or absolute)                                                                         |

### Overlay Network

| Setting           | Type | Default        | Description                   |
| ----------------- | ---- | -------------- | ----------------------------- |
| `OVERLAY_ENABLED` | bool | `False`        | Enable VXLAN overlay network  |
| `OVERLAY_SUBNET`  | str  | `"10.0.0.0/8"` | Overlay network address range |

### Authentication

| Setting                 | Type | Default | Description                         |
| ----------------------- | ---- | ------- | ----------------------------------- |
| `AUTH_ENABLED`          | bool | `False` | Enable authentication               |
| `ADMIN_SECRET`          | str  | `""`    | Master admin key (bypasses auth)    |
| `ADMIN_REGISTER_SECRET` | str  | `""`    | Secret for first admin registration |
| `SESSION_EXPIRE_HOURS`  | int  | `24`    | Session token lifetime in hours     |

### Environment Containers

| Setting                   | Type | Default | Description                                   |
| ------------------------- | ---- | ------- | --------------------------------------------- |
| `ENV_CONTAINER_CPU_LIMIT` | int  | `4`     | CPU limit for environment build containers    |
| `ENV_CONTAINER_MEM_LIMIT` | str  | `"8G"`  | Memory limit for environment build containers |

## Runner Configuration

Complete reference of `RunnerConfig` fields:

### Network

| Setting          | Type | Default     | Description                                |
| ---------------- | ---- | ----------- | ------------------------------------------ |
| `RUNNER_BIND_IP` | str  | `"0.0.0.0"` | IP address to bind the runner server       |
| `RUNNER_PORT`    | int  | `8001`      | Runner HTTP server port                    |
| `HOST_ADDRESS`   | str  | `""`        | Host server URL (e.g., `http://host:8000`) |

### Paths

| Setting          | Type | Default              | Description                                                                                                                                      |
| ---------------- | ---- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SHARED_DIR`     | str  | `"/cluster-share"`   | Path to shared storage (must match host). Required for tarball-based environments and shared log access. Optional if using only registry images. |
| `LOCAL_TEMP_DIR` | str  | `"/tmp/kohakuriver"` | Local temporary directory                                                                                                                        |

### Tunnel

| Setting          | Type | Default | Description                    |
| ---------------- | ---- | ------- | ------------------------------ |
| `TUNNEL_ENABLED` | bool | `True`  | Enable WebSocket tunnel server |

### Docker

| Setting                  | Type | Default           | Description            |
| ------------------------ | ---- | ----------------- | ---------------------- |
| `DOCKER_NETWORK_NAME`    | str  | `"kohakuriver"`   | Docker network name    |
| `DOCKER_NETWORK_SUBNET`  | str  | `"172.20.0.0/16"` | Docker network subnet  |
| `DOCKER_NETWORK_GATEWAY` | str  | `"172.20.0.1"`    | Docker network gateway |

### Snapshots

| Setting                 | Type | Default | Description                   |
| ----------------------- | ---- | ------- | ----------------------------- |
| `AUTO_SNAPSHOT_ON_STOP` | bool | `True`  | Auto-snapshot on VPS stop     |
| `MAX_SNAPSHOTS_PER_VPS` | int  | `5`     | Max snapshots before rotation |

### QEMU/VM

| Setting                | Type | Default                         | Description                   |
| ---------------------- | ---- | ------------------------------- | ----------------------------- |
| `VM_IMAGES_DIR`        | str  | `"~/.kohakuriver/vm-images"`    | Base VM image directory       |
| `VM_INSTANCES_DIR`     | str  | `"~/.kohakuriver/vm-instances"` | Running VM disk directory     |
| `VM_DEFAULT_MEMORY_MB` | int  | `4096`                          | Default VM RAM in MB          |
| `VM_ACS_OVERRIDE`      | bool | `False`                         | Enable ACS override for IOMMU |
| `VM_BRIDGE_NAME`       | str  | `"kohaku-br0"`                  | NAT bridge name               |
| `VM_BRIDGE_SUBNET`     | str  | `"192.168.100.0/24"`            | NAT bridge subnet             |
| `VM_BRIDGE_GATEWAY`    | str  | `"192.168.100.1"`               | NAT bridge gateway            |

### Overlay (Runner)

| Setting                | Type | Default            | Description                      |
| ---------------------- | ---- | ------------------ | -------------------------------- |
| `OVERLAY_ENABLED`      | bool | `False`            | Enable overlay agent             |
| `OVERLAY_SUBNET`       | str  | `""`               | Assigned by host on registration |
| `OVERLAY_NETWORK_NAME` | str  | `"kohaku-overlay"` | VXLAN interface name             |
| `OVERLAY_VXLAN_ID`     | int  | `42`               | VXLAN Network Identifier         |
| `OVERLAY_PORT`         | int  | `4789`             | VXLAN UDP port                   |
| `OVERLAY_MTU`          | int  | `1450`             | Overlay interface MTU            |

## Related Topics

- [Host Configuration](../setup/host-configuration.md) -- Setup guide
- [Runner Configuration](../setup/runner-configuration.md) -- Setup guide
- [Environment Variables](environment-variables.md) -- Env var reference
- [Ports](ports.md) -- Port reference
