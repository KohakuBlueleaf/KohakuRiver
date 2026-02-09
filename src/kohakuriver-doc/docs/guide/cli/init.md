---
title: kohakuriver init
description: Initialization commands for generating configurations and systemd services.
icon: i-carbon-document-add
---

# kohakuriver init

The `kohakuriver init` command group generates configuration files and systemd service units.

## Commands

### init config

Generate configuration file templates.

```bash
kohakuriver init config [options]
```

| Flag           | Default           | Description                       |
| -------------- | ----------------- | --------------------------------- |
| `--generate`   | `False`           | Generate with interactive prompts |
| `--host`       | `False`           | Generate host configuration       |
| `--runner`     | `False`           | Generate runner configuration     |
| `--output-dir` | `~/.kohakuriver/` | Output directory                  |

Examples:

```bash
# Generate host config template
kohakuriver init config --host

# Generate runner config template
kohakuriver init config --runner

# Generate both to custom directory
kohakuriver init config --host --runner --output-dir /etc/kohakuriver/

# Interactive generation (prompts for values)
kohakuriver init config --host --generate
```

#### Host Config Template

The generated `host_config.py` includes:

```python
# Network
HOST_BIND_IP = "0.0.0.0"
HOST_PORT = 8000
HOST_SSH_PROXY_PORT = 8002
HOST_REACHABLE_ADDRESS = "192.168.1.100"

# Paths
SHARED_DIR = "/cluster-share"
DB_FILE = "kohakuriver.db"

# Overlay Network
OVERLAY_ENABLED = False
OVERLAY_SUBNET = "10.0.0.0/8"

# Authentication
AUTH_ENABLED = False
ADMIN_SECRET = ""
ADMIN_REGISTER_SECRET = ""
SESSION_EXPIRE_HOURS = 24
```

#### Runner Config Template

The generated `runner_config.py` includes:

```python
# Network
RUNNER_BIND_IP = "0.0.0.0"
RUNNER_PORT = 8001
HOST_ADDRESS = "http://192.168.1.100:8000"

# Paths
SHARED_DIR = "/cluster-share"
LOCAL_TEMP_DIR = "/tmp/kohakuriver"

# Docker
DOCKER_NETWORK_NAME = "kohakuriver"
DOCKER_NETWORK_SUBNET = "172.20.0.0/16"
DOCKER_NETWORK_GATEWAY = "172.20.0.1"

# Tunnel
TUNNEL_ENABLED = True

# VM (QEMU)
VM_IMAGES_DIR = "~/.kohakuriver/vm-images"
VM_INSTANCES_DIR = "~/.kohakuriver/vm-instances"
VM_DEFAULT_MEMORY_MB = 4096

# Overlay
OVERLAY_ENABLED = False
```

### init service

Generate systemd service unit files.

```bash
kohakuriver init service [options]
```

| Flag              | Default                           | Description                            |
| ----------------- | --------------------------------- | -------------------------------------- |
| `--host`          | `False`                           | Generate host service                  |
| `--runner`        | `False`                           | Generate runner service                |
| `--all`           | `False`                           | Generate both services                 |
| `--host-config`   | `~/.kohakuriver/host_config.py`   | Host config path                       |
| `--runner-config` | `~/.kohakuriver/runner_config.py` | Runner config path                     |
| `--working-dir`   | Current directory                 | Service working directory              |
| `--python-path`   | Auto-detected                     | Python interpreter path                |
| `--capture-env`   | `False`                           | Capture current environment variables  |
| `--no-install`    | `False`                           | Print service files without installing |

Examples:

```bash
# Generate and install host service
kohakuriver init service --host

# Generate both services with custom paths
kohakuriver init service --all \
    --host-config /etc/kohakuriver/host.py \
    --runner-config /etc/kohakuriver/runner.py

# Preview without installing
kohakuriver init service --runner --no-install

# Capture current environment (for GPU drivers, etc.)
kohakuriver init service --runner --capture-env
```

The `--capture-env` flag is useful for ensuring the service has access to CUDA libraries and other environment-specific paths.

## After Initialization

After generating configuration and service files:

```bash
# 1. Edit the configuration
vim ~/.kohakuriver/host_config.py

# 2. Enable and start the service
sudo systemctl enable kohakuriver-host
sudo systemctl start kohakuriver-host

# 3. Check status
sudo systemctl status kohakuriver-host
```

## Related Topics

- [Host Configuration](../setup/host-configuration.md) -- Host config reference
- [Runner Configuration](../setup/runner-configuration.md) -- Runner config reference
- [Systemd Services](../setup/systemd-services.md) -- Service management
- [First Cluster](../getting-started/first-cluster.md) -- Cluster setup walkthrough
