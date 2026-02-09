---
title: Project Structure
description: Full repository layout with descriptions of every major directory and file
icon: i-carbon-folder
---

# Project Structure

KohakuRiver is organized as a monorepo with Python backend, Vue.js frontends, and a Rust tunnel client.

## Top-Level Layout

```
KohakuRiver/
├── pyproject.toml              # Python package definition and dependencies
├── CLAUDE.md                   # AI assistant context
├── configs/
│   ├── host/                   # Example host configuration
│   └── runner/                 # Example runner configuration
├── scripts/
│   └── create-vm-base-image.sh # Script to build QEMU base images
└── src/
    ├── kohakuriver/            # Python backend package
    ├── kohakuriver-manager/    # Vue.js web dashboard
    ├── kohakuriver-doc/        # Vue.js documentation site
    └── kohakuriver-tunnel/     # Rust tunnel client
```

## Python Backend (`src/kohakuriver/`)

```
kohakuriver/
├── __init__.py
├── version.py                    # Package version string
│
├── host/                         # ── Host server (FastAPI, port 8000) ──
│   ├── __init__.py               # FastAPI app creation, lifespan
│   ├── config.py                 # HostConfig dataclass + global instance
│   ├── state.py                  # Shared state accessors (overlay, IP reservation)
│   ├── endpoints/                # API route handlers
│   │   ├── health.py             #   /health, /cluster-health
│   │   ├── nodes.py              #   Node registration, heartbeat
│   │   ├── tasks.py              #   Task submission dispatch
│   │   ├── task_submission.py    #   Task submit logic
│   │   ├── task_querying.py      #   Task list, detail, filtering
│   │   ├── task_control.py       #   Task kill, pause, resume
│   │   ├── task_approval.py      #   Task approval workflow
│   │   ├── task_terminal.py      #   WebSocket terminal for tasks
│   │   ├── vps.py                #   VPS dispatch
│   │   ├── vps_lifecycle.py      #   VPS create, stop, restart
│   │   ├── vps_querying.py       #   VPS list, detail
│   │   ├── vps_snapshots.py      #   VPS snapshot management
│   │   ├── vps_assignments.py    #   VPS access grants
│   │   ├── vm_instances.py       #   VM instance admin ops
│   │   ├── docker.py             #   Docker image/container CRUD
│   │   ├── docker_terminal.py    #   WebSocket terminal for Docker
│   │   ├── filesystem.py         #   Remote filesystem operations
│   │   └── container_filesystem.py  In-container filesystem
│   ├── services/                 # Business logic layer
│   │   ├── task_scheduler.py     #   Task dispatch to runners
│   │   ├── node_manager.py       #   Node selection, resource math
│   │   ├── ip_reservation.py     #   IP reservation with signed tokens
│   │   ├── overlay_manager.py    #   Shim -> overlay subpackage
│   │   ├── overlay/              #   VXLAN hub overlay network
│   │   │   ├── manager.py        #     OverlayNetworkManager
│   │   │   ├── models.py         #     OverlayAllocation dataclass
│   │   │   ├── vxlan.py          #     VXLAN interface management
│   │   │   ├── routing.py        #     IP routing rules
│   │   │   └── recovery.py       #     State recovery on restart
│   │   └── tunnel_proxy.py       #   WebSocket tunnel proxying
│   ├── background/               # Background tasks
│   │   ├── health.py             #   Heartbeat timeout checker
│   │   └── runner_monitor.py     #   Runner monitoring
│   ├── websocket/                # WebSocket proxy handlers
│   └── auth/                     # Authentication system
│       ├── dependencies.py       #   FastAPI dependency injection
│       ├── routes.py             #   Auth API endpoints
│       └── utils.py              #   Password hashing, token generation
│
├── runner/                       # ── Runner agent (FastAPI, port 8001) ──
│   ├── __init__.py               # FastAPI app creation
│   ├── config.py                 # RunnerConfig dataclass + global instance
│   ├── endpoints/                # API route handlers
│   │   ├── tasks.py              #   Task execute/kill/pause/resume
│   │   ├── vps.py                #   VPS create/stop/restart
│   │   ├── terminal.py           #   WebSocket terminal
│   │   ├── docker.py             #   Docker image operations
│   │   ├── filesystem.py         #   File system operations
│   │   ├── filesystem_ops.py     #   File CRUD operations
│   │   ├── filesystem_shared.py  #   Shared filesystem access
│   │   └── filesystem_watcher.py #   File change watching
│   ├── services/                 # Business logic layer
│   │   ├── task_executor.py      #   Command task execution
│   │   ├── vps_manager.py        #   Docker VPS lifecycle
│   │   ├── vps_creation.py       #   VPS container creation logic
│   │   ├── vm_vps_manager.py     #   QEMU VM VPS lifecycle
│   │   ├── vm_network_manager.py #   VM network (overlay TAP / NAT bridge)
│   │   ├── vm_ssh.py             #   SSH key management for VMs
│   │   ├── resource_monitor.py   #   CPU/GPU/memory monitoring
│   │   ├── tunnel_server.py      #   Port forwarding via WebSocket
│   │   ├── tunnel_helper.py      #   Tunnel client launch helper
│   │   └── overlay_manager.py    #   Runner-side VXLAN setup
│   ├── background/               # Background tasks
│   │   ├── heartbeat.py          #   Heartbeat to host
│   │   └── startup_check.py      #   Container recovery on restart
│   └── numa/                     # NUMA topology detection
│       └── detector.py           #   Parse /sys/devices/system/node
│
├── cli/                          # ── Typer CLI ──
│   ├── main.py                   # Entry point, command registration
│   ├── host.py                   # `kohakuriver.host` entry
│   ├── runner.py                 # `kohakuriver.runner` entry
│   ├── config.py                 # CLI configuration (host address, etc.)
│   ├── client.py                 # HTTP client for host API calls
│   ├── output.py                 # Rich console + output helpers
│   ├── api/                      # API client modules
│   ├── commands/                 # Typer command groups
│   │   ├── task.py               #   task submit/list/kill/log
│   │   ├── vps.py                #   vps create/list/stop
│   │   ├── node.py               #   node list/status
│   │   ├── docker.py             #   Docker image/container mgmt
│   │   ├── ssh.py                #   SSH to VPS
│   │   ├── terminal.py           #   TUI terminal
│   │   ├── connect.py            #   Connect to container TTY
│   │   ├── forward.py            #   Port forwarding
│   │   ├── config_cmd.py         #   Show/edit configuration
│   │   ├── auth.py               #   Login/register/token management
│   │   ├── qemu.py               #   QEMU image management
│   │   └── init.py               #   Project initialization
│   ├── formatters/               # Rich table formatters
│   │   ├── task.py
│   │   ├── vps.py
│   │   ├── node.py
│   │   └── docker.py
│   ├── interactive/              # Interactive monitoring
│   │   ├── dashboard.py
│   │   └── monitor.py
│   └── tui/                      # Textual TUI apps
│       ├── dashboard/            #   Full cluster dashboard
│       ├── terminal.py           #   Terminal emulator
│       ├── editor.py             #   Text editor
│       ├── file_tree.py          #   File browser
│       └── ide.py                #   IDE layout
│
├── db/                           # ── Database layer (Peewee ORM + SQLite) ──
│   ├── base.py                   # BaseModel, db instance, initialize_database
│   ├── task.py                   # Task model with JSON accessors
│   ├── node.py                   # Node model with JSON accessors
│   ├── auth.py                   # User, Session, Token, Invitation, Group, etc.
│   └── models.py                 # Re-export shim
│
├── models/                       # ── Pydantic models and enums ──
│   ├── requests.py               # All API request/response DTOs
│   ├── enums.py                  # TaskStatus, TaskType, NodeStatus, LogLevel, SSHKeyMode
│   └── overlay_subnet.py         # OverlaySubnetConfig parser
│
├── docker/                       # ── Docker utilities ──
│   ├── naming.py                 # Container/image naming conventions
│   ├── client.py                 # Docker client wrapper
│   ├── container_manager.py      # Container create/start/stop
│   ├── image_manager.py          # Image management
│   ├── sync_manager.py           # Tarball sync from shared storage
│   ├── utils.py                  # Tarball utility helpers
│   └── exceptions.py             # Docker exception hierarchy
│
├── qemu/                         # ── QEMU/KVM integration ──
│   ├── __init__.py               # Re-exports
│   ├── capability.py             # VM capability detection (KVM, IOMMU, VFIO)
│   ├── client.py                 # QEMUManager, VMInstance, VMCreateOptions
│   ├── vfio.py                   # GPU VFIO bind/unbind (IOMMU-group-aware)
│   ├── cloud_init.py             # Cloud-init ISO generation + VM agent
│   ├── naming.py                 # VM naming conventions
│   └── exceptions.py             # QEMU exception hierarchy
│
├── tunnel/                       # ── Tunnel protocol (Python side) ──
│   └── protocol.py               # Binary protocol parser/builder
│
├── ssh_proxy/                    # ── SSH proxy for VPS access ──
├── storage/                      # ── KohakuVault state persistence ──
│   └── vault.py
├── exceptions/                   # ── Shared exceptions ──
└── utils/                        # ── Shared utilities ──
    ├── snowflake.py              # Snowflake ID generator
    ├── logger.py                 # Loguru configuration
    ├── gpu.py                    # GPU detection utilities
    ├── cli.py                    # CLI helpers
    ├── ssh_key.py                # SSH key generation
    └── default_config.toml       # Default configuration values
```

## Web Dashboard (`src/kohakuriver-manager/`)

See [Manager Architecture](./frontend/manager-architecture.md) for details.

## Documentation Site (`src/kohakuriver-doc/`)

See [Doc Site Architecture](./frontend/doc-site-architecture.md) for details.

## Tunnel Client (`src/kohakuriver-tunnel/`)

See [Rust Client](./tunnel/rust-client.md) for details.
