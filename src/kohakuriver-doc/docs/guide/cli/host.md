---
title: kohakuriver host
description: Starting and configuring the KohakuRiver host server.
icon: i-carbon-server-dns
---

# kohakuriver host

The `kohakuriver host` command starts the central orchestration server.

## Usage

```bash
kohakuriver host [options]
```

## Options

| Flag       | Default                         | Description                     |
| ---------- | ------------------------------- | ------------------------------- |
| `--config` | `~/.kohakuriver/host_config.py` | Path to host configuration file |
| `--bind`   | From config (`0.0.0.0`)         | IP address to bind to           |
| `--port`   | From config (`8000`)            | Port to listen on               |

## What It Starts

The host server runs as a FastAPI application under Uvicorn with these components:

1. **REST API** on port 8000 -- Task submission, node management, VPS lifecycle
2. **SSH Proxy** on port 8002 -- Proxies SSH connections to VPS containers
3. **WebSocket Proxy** -- Terminal attach and tunnel connections
4. **Static Files** -- Serves the Vue.js web dashboard
5. **Background Services**:
   - Overlay network manager (if `OVERLAY_ENABLED`)
   - Node heartbeat timeout monitoring
   - Task state reconciliation

## Configuration

The host reads its config from a Python file (`host_config.py`). Generate a template:

```bash
kohakuriver init config --host
```

Key configuration options are documented in [Host Configuration](../setup/host-configuration.md).

## Example

```bash
# Start with default config
kohakuriver host

# Start with custom config and port
kohakuriver host --config /etc/kohakuriver/host.py --port 9000
```

## Systemd Service

For production deployments, run the host as a systemd service:

```bash
kohakuriver init service --host
sudo systemctl enable kohakuriver-host
sudo systemctl start kohakuriver-host
```

See [Systemd Services](../setup/systemd-services.md) for details.

## Direct Entry Point

The host can also be started directly:

```bash
kohakuriver.host
```

This uses the `kohakuriver.cli.host:main` entry point.

## Related Topics

- [Host Configuration](../setup/host-configuration.md) -- Full configuration reference
- [Runner](runner.md) -- Starting the runner agent
- [First Cluster](../getting-started/first-cluster.md) -- Setting up a cluster
