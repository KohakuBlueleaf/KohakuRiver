# KohakuRiver Documentation

Welcome to the KohakuRiver documentation!

KohakuRiver is a lightweight, self-hosted cluster manager designed for distributing command-line tasks and launching persistent interactive sessions (VPS Tasks) across compute nodes. It leverages Docker containers as portable virtual environments for reproducible execution.

## Key Features

- **Container as Portable Environment** - Docker containers auto-sync across nodes as versioned tarballs
- **Task/VPS System** - Batch tasks and persistent interactive sessions for R&D workflows
- **TTY Forwarding** - WebSocket terminal access without Docker port mapping
- **Port Forwarding** - Dynamic TCP/UDP tunneling to container services
- **Web UI & Terminal TUI** - Visual dashboard and VSCode-like terminal interface

This documentation is organized into several sections to help you get started, administer your cluster, use its features, and find reference information.

## Documentation Structure

```
docs/
├── README.md                     # This file - Documentation Index
├── 1. getting-started/           # Guides for new users
│   ├── 1. overview.md            # What KohakuRiver is, purpose, and key features
│   ├── 2. installation.md        # Step-by-step installation guide
│   ├── 3. quick-start.md         # Hands-on guide to submit your first tasks
│   ├── 4. concepts.md            # Core concepts (Host-Runner, Docker, Tasks/VPS, SSH Proxy)
│   └── 5. alternatives.md        # Comparison with other tools
├── 2. admin-guides/              # Cluster administration
│   ├── 1. host-setup.md          # Host server setup
│   ├── 2. runner-setup.md        # Runner node setup
│   ├── 3. shared-storage.md      # Shared storage configuration
│   ├── 4. systemd-integration.md # Running as systemd services
│   └── 5. security.md            # Security considerations
├── 3. user-guides/               # Task and environment management
│   ├── 1. container-workflow.md  # Docker environment workflow
│   ├── 2. command-tasks/         # Command task guides
│   │   ├── 1. submission.md      # Submitting command tasks
│   │   └── 2. best-practices.md  # Best practices
│   ├── 3. vps-tasks/             # VPS task guides
│   │   ├── 1. management.md      # VPS management
│   │   ├── 2. ssh-access.md      # SSH access via proxy
│   │   ├── 3. container-prep.md  # Preparing VPS containers
│   │   └── 4. common-use-cases.md# VPS use cases
│   ├── 4. gpu-allocation/        # GPU task guides
│   │   ├── 1. allocation.md      # GPU allocation
│   │   └── 2. container-prep.md  # GPU container setup
│   ├── 5. web-dashboard/         # Web UI guides
│   │   └── 1. overview.md        # Dashboard overview (consolidated)
│   └── 6. monitoring/            # Monitoring guides
│       └── 1. monitoring.md      # Monitoring overview (consolidated)
├── 4. reference/                 # Technical reference
│   ├── 1. configuration.md       # Configuration options
│   └── 2. cli-reference.md       # CLI command reference (consolidated)
├── 5. troubleshooting/           # Problem solving
│   └── 1. troubleshooting.md     # Troubleshooting guide (consolidated)
└── 6. integration-guides/        # External integrations
    └── 1. integration.md         # Integration guide (consolidated)
```

## Quick Links

### Getting Started
- [Overview](1.%20getting-started/1.%20overview.md) - What is KohakuRiver?
- [Installation](1.%20getting-started/2.%20installation.md) - How to install
- [Quick Start](1.%20getting-started/3.%20quick-start.md) - First steps

### Key CLI Commands

```bash
# Initialize configuration
kohakuriver init config --all

# Start services
kohakuriver.host              # Start Host server
kohakuriver.runner            # Start Runner agent

# Or register as systemd services
kohakuriver init service --all

# Task management
kohakuriver task submit 'echo "Hello"' -t node1
kohakuriver task list
kohakuriver task status <task_id>

# VPS management
kohakuriver vps create -t node1 -c 4 -m 8G
kohakuriver vps connect <task_id>

# Terminal access (without Docker port mapping)
kohakuriver connect <task_id>           # WebSocket terminal
kohakuriver connect <task_id> --ide     # TUI IDE mode

# Port forwarding (without Docker port mapping)
kohakuriver forward <task_id> 8888      # Forward port 8888
kohakuriver forward <task_id> 80 -l 3000  # Forward 80 to local 3000

# Terminal TUI dashboard
kohakuriver terminal

# Docker management
kohakuriver docker container create ubuntu:22.04 my-env
kohakuriver docker container shell my-env
kohakuriver docker tar create my-env
```

### Configuration

Default config paths:
- Host: `~/.kohakuriver/host_config.py`
- Runner: `~/.kohakuriver/runner_config.py`

Key settings to configure:
- `HOST_REACHABLE_ADDRESS` - Host IP accessible by runners/clients
- `SHARED_DIR` - Shared storage path (must be same on all nodes)
- `HOST_ADDRESS` (Runner) - How runner reaches the host

### Environment Variables

| Variable | Description |
|----------|-------------|
| `KOHAKURIVER_HOST` | Host server address |
| `KOHAKURIVER_PORT` | Host server port |
| `KOHAKURIVER_SHARED_DIR` | Shared storage path |

## Section Overviews

- **[1. Getting Started](1.%20getting-started/1.%20overview.md)**: New to KohakuRiver? Start here to learn what it is, how to install it, and get your first cluster running.

- **[2. Admin Guides](2.%20admin-guides/1.%20host-setup.md)**: For administrators setting up and maintaining the cluster infrastructure, including Host/Runner setup, shared storage, and systemd integration.

- **[3. User Guides](3.%20user-guides/1.%20container-workflow.md)**: For users submitting and managing tasks. Covers Docker workflow, command tasks, VPS tasks, GPU allocation, and the Web Dashboard.

- **[4. Reference](4.%20reference/1.%20configuration.md)**: Technical reference for configuration, CLI commands, API endpoints, and architecture.

- **[5. Troubleshooting](5.%20troubleshooting/1.%20troubleshooting.md)**: Diagnosing and resolving common problems with startup, tasks, networking, and permissions.

- **[6. Integration Guides](6.%20integration-guides/1.%20integration.md)**: Integrating KohakuRiver with external monitoring systems, workflow managers, and notification services.

---

*Note: This documentation is for KohakuRiver v0.5.0 with the refactored CLI and Python-based configuration system.*
