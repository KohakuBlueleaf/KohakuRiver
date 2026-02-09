---
title: Installation
description: How to install KohakuRiver from source, including entry points and console scripts.
icon: i-carbon-download
---

# Installation

KohakuRiver is distributed as a Python package. Install it on every machine in your cluster (host and all runners).

## Install from Source

Clone the repository and install:

```bash
git clone https://github.com/KohakuBlueleaf/HakuRiver.git
cd HakuRiver
pip install .
```

For GPU monitoring support (NVIDIA GPU metrics via `nvidia-ml-py`):

```bash
pip install ".[gpu]"
```

## Console Entry Points

After installation, three console commands are available:

| Command              | Module                        | Purpose                       |
| -------------------- | ----------------------------- | ----------------------------- |
| `kohakuriver`        | `kohakuriver.cli.main:run`    | Unified CLI (all subcommands) |
| `kohakuriver.host`   | `kohakuriver.cli.host:main`   | Start host server directly    |
| `kohakuriver.runner` | `kohakuriver.cli.runner:main` | Start runner agent directly   |

### The Unified CLI

The primary interface is the `kohakuriver` command with subcommands:

```bash
kohakuriver --help
```

Available subcommand groups:

- `kohakuriver host` -- Start the host server
- `kohakuriver runner` -- Start a runner agent
- `kohakuriver task` -- Task management (submit, list, kill, logs, watch)
- `kohakuriver vps` -- VPS management (create, list, stop, connect)
- `kohakuriver node` -- Node management (list, status, health, overlay)
- `kohakuriver docker` -- Docker/container management (images, containers, tarballs)
- `kohakuriver ssh` -- SSH commands (connect via proxy, config generation)
- `kohakuriver forward` -- Port forwarding to containers
- `kohakuriver connect` -- Terminal attach to containers
- `kohakuriver terminal` -- TUI dashboard
- `kohakuriver auth` -- Authentication (login, logout, tokens)
- `kohakuriver config` -- Configuration management
- `kohakuriver init` -- Bootstrap configuration and services
- `kohakuriver qemu` -- QEMU/KVM management

### Direct Server Commands

For running servers directly (useful in systemd services):

```bash
# Start host server
kohakuriver.host --config ~/.kohakuriver/host_config.py

# Start runner agent
kohakuriver.runner --config ~/.kohakuriver/runner_config.py
```

## Tunnel Client (Optional)

The tunnel client is a Rust binary that runs inside containers for port forwarding. To build it:

```bash
cd src/kohakuriver-tunnel/
cargo build --release
```

The compiled binary (`target/release/tunnel-client`) should be placed where the runner can find it. The runner auto-detects it in these locations:

1. `./tunnel-client` (current working directory)
2. `~/.kohakuriver/tunnel-client`
3. `/usr/local/bin/tunnel-client`
4. `/usr/bin/tunnel-client`
5. `<SHARED_DIR>/bin/tunnel-client`

Or set the path explicitly in runner configuration with `TUNNEL_CLIENT_PATH`.

## Web Dashboard (Optional)

The Vue.js web dashboard is a separate frontend application:

```bash
cd src/kohakuriver-manager/
npm install
npm run dev     # Development server
npm run build   # Production build
```

The dashboard connects to the host API at port 8000.

## Verifying Installation

```bash
# Check the CLI is installed
kohakuriver --help

# Check version (shown in --help output)
kohakuriver host --help
kohakuriver runner --help
```

## Next Steps

- [First Cluster](./first-cluster.md) -- Set up your host and first runner
- [First Task](./first-task.md) -- Submit your first task to the cluster
