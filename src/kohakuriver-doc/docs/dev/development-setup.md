---
title: Development Setup
description: How to set up a local development environment for KohakuRiver
icon: i-carbon-terminal
---

# Development Setup

This guide walks through setting up a local development environment for all KohakuRiver components.

## Prerequisites

- **Python 3.10+** (for backend and CLI)
- **Node.js 18+** and **npm** (for frontend)
- **Rust toolchain** (for tunnel client, install via [rustup](https://rustup.rs/))
- **Docker** (for container management features)
- **SQLite** (bundled with Python)

## Python Backend

### Install in development mode

From the repository root:

```bash
pip install -e .
# With GPU monitoring support (requires NVIDIA drivers):
pip install -e ".[gpu]"
```

### Key dependencies

Defined in `pyproject.toml`:

| Package                      | Purpose                                               |
| ---------------------------- | ----------------------------------------------------- |
| `fastapi` + `uvicorn`        | HTTP server for host and runner                       |
| `peewee`                     | SQLite ORM                                            |
| `httpx`                      | Async HTTP client (host -> runner communication)      |
| `docker`                     | Docker SDK for Python                                 |
| `typer` + `rich` + `textual` | CLI framework and TUI                                 |
| `pyroute2`                   | Linux network management (VXLAN, bridges, routes)     |
| `loguru`                     | Structured logging                                    |
| `pydantic`                   | Request/response validation                           |
| `kohaku-engine`              | Configuration engine (external)                       |
| `kohakuvault`                | Runner-side state persistence (SQLite-based)          |
| `snowflake-id`               | Distributed ID generation                             |
| `psutil`                     | System resource monitoring (CPU, memory, temperature) |

### Running services locally

```bash
# Start the host server (port 8000)
kohakuriver host

# Start a runner agent (port 8001)
kohakuriver runner
```

Both commands read configuration from `~/.kohakuriver/host_config.py` and `~/.kohakuriver/runner_config.py` respectively. Example configs are in `configs/host/` and `configs/runner/`.

### Configuration

Create configuration files by copying examples:

```bash
mkdir -p ~/.kohakuriver
cp configs/host/host_config.py ~/.kohakuriver/host_config.py
cp configs/runner/runner_config.py ~/.kohakuriver/runner_config.py
```

The critical setting is `HOST_REACHABLE_ADDRESS` in the host config -- this must be the address runners use to reach the host.

See [Config System](./backend/config-system.md) for details on how configuration works.

### Minimal local cluster

To run a single-node cluster for development:

```
┌───────────────────────────────────────────────────────┐
│  Developer Machine                                    │
│                                                       │
│  ┌─────────────┐         ┌──────────────┐             │
│  │ Host :8000  │◄───────►│ Runner :8001 │             │
│  │             │         │              │             │
│  │ SQLite DB   │         │ Docker Daemon│             │
│  └─────────────┘         └──────────────┘             │
│        ▲                        ▲                     │
│        │                        │                     │
│  ┌─────┴─────┐         ┌───────┴────────┐             │
│  │ CLI       │         │ Containers     │             │
│  │ Dashboard │         │ (tasks, VPS)   │             │
│  └───────────┘         └────────────────┘             │
└───────────────────────────────────────────────────────┘
```

Set `HOST_REACHABLE_ADDRESS = "127.0.0.1"` for same-machine operation.

## Frontend (Manager Dashboard)

```bash
cd src/kohakuriver-manager
npm install
npm run dev        # Start dev server (port 5173)
npm run build      # Production build
npm run format     # Prettier formatting
```

The dashboard connects to the host API at the address configured in its environment. See [Manager Architecture](./frontend/manager-architecture.md).

## Frontend (Documentation Site)

```bash
cd src/kohakuriver-doc
npm install
npm run dev        # Start dev server (port 5174)
npm run build      # Production build
```

The doc site reads markdown files from `docs/` and serves them as rendered pages. See [Doc Site Architecture](./frontend/doc-site-architecture.md).

## Tunnel Client (Rust)

```bash
cd src/kohakuriver-tunnel
cargo build --release
```

The compiled binary is at `target/release/tunnel-client`. The runner auto-detects the binary in several search paths (see [Rust Client](./tunnel/rust-client.md)).

## Console Entry Points

After `pip install`, three console scripts are available:

| Command              | Entry Point                   | Purpose                                                              |
| -------------------- | ----------------------------- | -------------------------------------------------------------------- |
| `kohakuriver`        | `kohakuriver.cli.main:run`    | Unified CLI (host, runner, task, vps, node, docker, ssh, forward...) |
| `kohakuriver.host`   | `kohakuriver.cli.host:main`   | Start host server directly                                           |
| `kohakuriver.runner` | `kohakuriver.cli.runner:main` | Start runner agent directly                                          |

## Directory Layout for Development

```
~/.kohakuriver/
├── host_config.py         # Host configuration (Python)
├── runner_config.py       # Runner configuration (Python)
└── tunnel-client          # Optional: tunnel binary

/var/lib/kohakuriver/
├── kohakuriver.db         # SQLite database (host)
├── vm-images/             # QEMU base images (qcow2)
└── vm-instances/          # QEMU instance directories
    └── {task_id}/
        ├── root.qcow2    # Instance disk (overlay on base)
        ├── seed.iso       # Cloud-init ISO
        └── vm.pid         # QEMU daemon PID file

/mnt/cluster-share/                  # Shared storage (NFS/CIFS) -- optional
├── kohakuriver-containers/          # Container tarballs (for tarball-based image distribution)
│   └── myenv-1706000000.tar
└── bin/
    └── tunnel-client                # Optional shared tunnel binary
```

## Verifying the Setup

After starting host and runner:

```bash
# Check host is running
kohakuriver node list

# Submit a test task
kohakuriver task submit --command "echo hello" --container kohakuriver-base

# Check task status
kohakuriver task list
```
