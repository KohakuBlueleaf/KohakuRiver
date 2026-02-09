---
title: First Cluster
description: Walkthrough for setting up a KohakuRiver host and your first runner node.
icon: i-carbon-connect
---

# First Cluster

This guide walks you through setting up a minimal KohakuRiver cluster with one host and one runner.

## Step 1: Prepare Shared Storage (Recommended)

If you plan to use tarball-based container environments (the default and simplest approach), all nodes should share a common directory. For a quick single-machine setup:

```bash
sudo mkdir -p /mnt/cluster-share
sudo chown $USER:$USER /mnt/cluster-share
```

For multi-machine clusters, set up NFS or another shared filesystem. See [Shared Storage](../setup/shared-storage.md).

> **Note:** Shared storage is recommended but not required. If you only use containers from Docker registries (via `registry_image`), you can skip this step. VMs also use local disk images and do not require shared storage.

## Step 2: Generate Configuration Files

Use the init command to generate configuration templates:

```bash
# Generate both host and runner configs
kohakuriver init config --generate
```

This creates:

- `~/.kohakuriver/host_config.py`
- `~/.kohakuriver/runner_config.py`

## Step 3: Configure the Host

Edit `~/.kohakuriver/host_config.py`:

```python
# The address runners and clients use to reach this host
# IMPORTANT: Change this to the actual IP or hostname of this machine!
HOST_REACHABLE_ADDRESS: str = "192.168.1.100"  # <-- Your host IP

# Shared storage path (must be the same on all nodes)
SHARED_DIR: str = "/mnt/cluster-share"

# Database location
DB_FILE: str = "/var/lib/kohakuriver/kohakuriver.db"
```

Create the database directory:

```bash
sudo mkdir -p /var/lib/kohakuriver
sudo chown $USER:$USER /var/lib/kohakuriver
```

## Step 4: Start the Host

```bash
kohakuriver.host --config ~/.kohakuriver/host_config.py
```

You should see output indicating the FastAPI server is running on port 8000.

## Step 5: Configure the Runner

Edit `~/.kohakuriver/runner_config.py` on the runner machine:

```python
# Address of the host server
HOST_ADDRESS: str = "192.168.1.100"  # <-- Must match HOST_REACHABLE_ADDRESS
HOST_PORT: int = 8000

# Shared storage path (same as host)
SHARED_DIR: str = "/mnt/cluster-share"
```

## Step 6: Start the Runner

```bash
kohakuriver.runner --config ~/.kohakuriver/runner_config.py
```

The runner will:

1. Detect system resources (CPU cores, NUMA topology, GPUs)
2. Register with the host
3. Start sending heartbeats

## Step 7: Verify the Cluster

Configure the CLI to point at your host:

```bash
export HAKURIVER_HOST=192.168.1.100
export HAKURIVER_PORT=8000
```

Check that the node is registered:

```bash
kohakuriver node list
```

You should see your runner node listed with status "online".

Check cluster health:

```bash
kohakuriver node health
```

This shows a summary of cluster resources and node status.

## Step 8: Set Up as Services (Optional)

For production use, set up systemd services:

```bash
# Generate and install service files
kohakuriver init service --all
```

This creates `kohakuriver-host.service` and `kohakuriver-runner.service`, copies them to `/etc/systemd/system/`, and reloads the daemon.

Start and enable:

```bash
sudo systemctl start kohakuriver-host
sudo systemctl enable kohakuriver-host

sudo systemctl start kohakuriver-runner
sudo systemctl enable kohakuriver-runner
```

View logs:

```bash
journalctl -u kohakuriver-host -f
journalctl -u kohakuriver-runner -f
```

## Single-Machine Setup

For testing, you can run both host and runner on the same machine. Set `HOST_REACHABLE_ADDRESS` to `127.0.0.1` in the host config and `HOST_ADDRESS` to `127.0.0.1` in the runner config.

## Next Steps

- [First Task](./first-task.md) -- Submit your first command task
- [Host Configuration](../setup/host-configuration.md) -- Detailed host configuration reference
- [Runner Configuration](../setup/runner-configuration.md) -- Detailed runner configuration reference
