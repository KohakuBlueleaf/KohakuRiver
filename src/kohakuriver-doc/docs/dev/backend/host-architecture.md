---
title: Host Architecture
description: Host server services, endpoints, middleware, and database access patterns
icon: i-carbon-bare-metal-server
---

# Host Architecture

The Host is the central orchestrator of the KohakuRiver cluster. It runs a FastAPI server on port 8000 and manages task scheduling, node registration, health monitoring, overlay networking, and SSH proxying.

## High-Level Architecture

```
                    ┌──────────────┐   ┌───────────────┐
                    │  CLI Client  │   │ Web Dashboard │
                    └──────┬───────┘   └───────┬───────┘
                           │                   │
                           ▼                   ▼
                 ┌──────────────────────────────────────────┐
                 │         Host API  :8000                  │
                 │                                          │
                 │  ┌───────────┐  ┌─────────────────────┐  │
                 │  │ Endpoints │  │  Background Tasks   │  │
                 │  │ (routers) │  │                     │  │
                 │  └─────┬─────┘  └───────┬─────────────┘  │
                 │        │                │                │
                 │  ┌─────▼────────────────▼──────────────┐ │
                 │  │         Service Layer                │ │
                 │  │  TaskScheduler  NodeManager          │ │
                 │  │  OverlayMgr    IPReservation         │ │
                 │  └─────┬──────────────┬────────────────┘ │
                 │        │              │                  │
                 │  ┌─────▼─────┐  ┌─────▼──────────────┐  │
                 │  │ SQLite DB │  │ SSH Proxy :8002     │  │
                 │  │ (Peewee)  │  │                     │  │
                 │  └───────────┘  └─────────────────────┘  │
                 └──────────┬──────────────┬────────────────┘
                            │              │
               ┌────────────▼──┐    ┌──────▼──────────────┐
               │ Runner 1 :8001│    │  Runner 2 :8001     │
               └───────────────┘    └─────────────────────┘
```

## Application Lifecycle

The FastAPI app is created in `host/__init__.py` with a lifespan context manager that:

1. Loads configuration from `~/.kohakuriver/host_config.py` via KohakuEngine.
2. Initializes the SQLite database (`db.base.initialize_database`).
3. Starts the overlay network manager (if `OVERLAY_ENABLED`).
4. Starts background health monitoring.
5. On shutdown: closes DB connections and tears down overlay.

## Endpoint Groups

Endpoints are organized as FastAPI routers under the `/api` prefix:

| Router       | Path Prefix     | Source File(s)                                                                  | Purpose                                            |
| ------------ | --------------- | ------------------------------------------------------------------------------- | -------------------------------------------------- |
| Tasks        | `/api/tasks`    | `task_submission.py`, `task_querying.py`, `task_control.py`, `task_approval.py` | Submit, list, kill, pause, resume, approve tasks   |
| VPS          | `/api/vps`      | `vps_lifecycle.py`, `vps_querying.py`, `vps_snapshots.py`, `vps_assignments.py` | Create, list, stop, restart, snapshot VPS sessions |
| Nodes        | `/api/nodes`    | `nodes.py`                                                                      | List nodes, register, heartbeat                    |
| Docker       | `/api/docker`   | `docker.py`                                                                     | Image/container management                         |
| Health       | `/api/health`   | `health.py`                                                                     | Health checks and cluster status                   |
| Filesystem   | `/api/fs`       | `filesystem.py`, `container_filesystem.py`                                      | Remote file operations                             |
| Auth         | `/api/auth`     | `auth/routes.py`                                                                | Login, register, tokens, invitations               |
| Overlay      | `/api/overlay`  | (via state.py)                                                                  | IP reservation and overlay status                  |
| VM Instances | `/api/admin/vm` | `vm_instances.py`                                                               | VM instance admin operations                       |

WebSocket endpoints for terminal access and tunnel proxying are mounted separately.

## Service Layer

### TaskScheduler (`services/task_scheduler.py`)

Handles communication with runners for task lifecycle:

- `send_task_to_runner()` -- POST to `/api/execute` on the runner with task details, container name, working dir, optional reserved IP
- `send_vps_task_to_runner()` -- POST to `/api/vps/create` on the runner
- `send_kill_to_runner()`, `send_pause_to_runner()`, `send_resume_to_runner()` -- control commands
- `update_task_status()` -- processes status callbacks from runners with state validation

State transitions are validated in `_validate_status_transition()`. VPS tasks can recover from `lost` back to `running` when a runner restarts and finds the container still alive.

### NodeManager (`services/node_manager.py`)

Provides resource calculation and node selection:

- `get_node_available_cores(node)` -- total cores minus running task cores
- `get_node_available_gpus(node)` -- all GPU IDs minus GPUs used by running tasks
- `get_node_available_memory(node)` -- total minus max(reserved, currently_used)
- `find_suitable_node()` -- selects the best node by available cores
- `find_suitable_node_for_vm()` -- filters for `vm_capable=True` nodes with VFIO GPUs

Node selection sorts candidates by available cores (most-free-first strategy).

### Overlay Network (`services/overlay/`)

The overlay subpackage is split into five modules:

```
host/services/overlay/
├── manager.py      OverlayNetworkManager (main coordinator)
├── models.py       OverlayAllocation dataclass
├── vxlan.py        VXLAN interface creation/deletion
├── routing.py      IP forwarding and route management
└── recovery.py     State recovery from existing interfaces on restart
```

See [Networking Internals](./networking-internals.md) for the full overlay architecture.

### IP Reservation (`services/ip_reservation.py`)

Allows pre-reserving container IPs before task submission. Uses HMAC-signed tokens:

```
Token = base64(json{ip, runner, exp}.sha256_signature)
```

Reservations are in-memory with periodic cleanup of expired entries. Useful for distributed training where the master address must be known before launching workers.

## Background Tasks

### Health Monitor (`background/health.py`)

Runs periodically (configured by `CLEANUP_CHECK_INTERVAL_SECONDS`, default 10 seconds) to:

1. Check heartbeat timestamps against `HEARTBEAT_TIMEOUT_FACTOR * HEARTBEAT_INTERVAL_SECONDS` (default: 6 \* 5 = 30 seconds).
2. Mark nodes as `offline` if heartbeat is stale.
3. Mark tasks on offline nodes as `lost`.

### Runner Monitor (`background/runner_monitor.py`)

Additional monitoring for runner health and resource tracking.

## Shared State

`host/state.py` provides global accessors to avoid circular imports:

```python
from kohakuriver.host.state import get_overlay_manager, get_ip_reservation_manager
```

These are set during app initialization and read by endpoint handlers. This pattern avoids passing managers through every function call.

## Authentication

When `AUTH_ENABLED=True`, the auth system provides:

- Cookie-based sessions for browser clients (30-day default expiry)
- API tokens (SHA3-512 hashed) for programmatic access
- Role hierarchy: `anony < viewer < user < operator < admin`
- Invitation-only registration (with configurable expiry)
- Task approval workflow for `user` role (tasks enter `pending_approval` state)
- Admin bootstrap via `ADMIN_SECRET` header or `ADMIN_REGISTER_SECRET` for first registration

Auth is implemented in `host/auth/`:

```
host/auth/
├── dependencies.py    FastAPI Depends() for role checking
├── routes.py          /api/auth/* endpoints
└── utils.py           Password hashing (bcrypt), token generation
```
