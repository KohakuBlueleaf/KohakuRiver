# Architecture Overview

This document describes KohakuRiver's system architecture in detail, covering the three-tier component model, inter-component communication, data model, configuration system, service startup sequences, and the reasoning behind key design decisions.

---

## Three-Tier Model

KohakuRiver follows a centralized orchestrator pattern with three tiers:

```
┌─────────────────────────────────────────────────────────────────────────┐
|                            Tier 1: HOST                                 |
|                                                                         |
|  Central orchestrator. Single instance per cluster.                     |
|  FastAPI server on port 8000. SSH proxy on port 8002.                   |
|  SQLite database via Peewee ORM.                                        |
|                                                                         |
|  Responsibilities:                                                      |
|    - Accept and schedule tasks                                          |
|    - Register and monitor runner nodes                                  |
|    - Manage overlay network topology                                    |
|    - Reserve container/VM IP addresses                                  |
|    - Proxy WebSocket terminals, tunnels, and SSH connections            |
|    - Authenticate users and enforce RBAC                                |
└────────────────────────────────┬────────────────────────────────────────┘
                                 |
                    HTTP REST + VXLAN (UDP 4789)
                                 |
┌────────────────────────────────┴────────────────────────────────────────┐
|                          Tier 2: RUNNERS                                |
|                                                                         |
|  Task executors. One instance per compute node.                         |
|  FastAPI server on port 8001.                                           |
|                                                                         |
|  Responsibilities:                                                      |
|    - Execute command tasks in Docker containers (subprocess)            |
|    - Manage VPS sessions (Docker containers or QEMU/KVM VMs)           |
|    - Monitor local resources (CPU, memory, GPU, temperature)            |
|    - Run tunnel server for container port forwarding                    |
|    - Manage local VXLAN overlay agent                                   |
|    - Send periodic heartbeats to Host                                   |
└────────────────────────────────┬────────────────────────────────────────┘
                                 |
                     Docker API / QEMU / Tunnel
                                 |
┌────────────────────────────────┴────────────────────────────────────────┐
|                     Tier 3: CONTAINERS / VMs                            |
|                                                                         |
|  Isolated workload environments. Managed by Runners.                    |
|                                                                         |
|  Types:                                                                 |
|    - Docker containers: command tasks and VPS sessions                  |
|    - QEMU/KVM VMs: full virtual machines with GPU passthrough           |
|                                                                         |
|  Features:                                                              |
|    - Shared storage mounted at /shared                                  |
|    - Overlay networking for cross-node communication                    |
|    - Tunnel client binary for port forwarding                           |
|    - SSH access for VPS sessions                                        |
└─────────────────────────────────────────────────────────────────────────┘
```

### Tier Summary

| Tier | Component | Count | Port | Process |
|------|-----------|-------|------|---------|
| 1 | Host | 1 per cluster | 8000 (API), 8002 (SSH) | `kohakuriver host` |
| 2 | Runner | 1 per compute node | 8001 | `kohakuriver runner` |
| 3 | Container | Many per Runner | N/A (overlay IPs) | Docker / QEMU |

---

## Host Services

The Host server is composed of several service modules, background tasks, and endpoint routers.

### Service Modules

| Service | Source File | Purpose |
|---------|------------|---------|
| Task Scheduler | `host/services/task_scheduler.py` | Sends task execution and VPS creation requests to Runners. Handles kill, pause, resume commands. Processes status update callbacks from Runners. |
| Node Manager | `host/services/node_manager.py` | Registers Runner nodes, updates node metadata on heartbeat, tracks online/offline status. |
| Overlay Manager | `host/services/overlay_manager.py` | Creates and manages VXLAN tunnel interfaces (`vxkr{N}`) to each Runner. Maintains host-side routing tables. Recovers state from existing interfaces on restart. |
| IP Reservation | `host/services/ip_reservation.py` | Allocates overlay IP addresses from each Runner's /16 subnet. Ensures no IP conflicts across the cluster. |
| Tunnel Proxy | `host/services/tunnel_proxy.py` | Proxies WebSocket-based port forwarding requests from clients to the appropriate Runner's tunnel server. |
| Auth System | `host/auth/` | User registration (invitation-only), session management, API token authentication, RBAC with five-tier role hierarchy. |

### Background Tasks

| Task | Source File | Interval | Purpose |
|------|------------|----------|---------|
| Runner Monitor | `host/background/runner_monitor.py` | Configurable | Detects dead Runners by checking heartbeat timestamps. Marks unresponsive nodes as offline and their tasks as `lost`. |
| Health Collator | `host/background/health.py` | Continuous | Aggregates cluster-wide health metrics from Runner heartbeats for the monitoring dashboard. |
| SSH Proxy | `ssh_proxy/server.py` | Continuous | Listens on port 8002. Proxies SSH connections to VPS containers via overlay network or Runner forwarding. |

### Endpoint Routers

All HTTP endpoints are registered under the `/api` prefix:

| Router | Prefix | Key Endpoints |
|--------|--------|---------------|
| `tasks` | `/api` | `POST /submit`, `POST /kill/{id}`, `POST /pause/{id}`, `POST /resume/{id}`, `GET /tasks`, `POST /update` |
| `nodes` | `/api` | `POST /register`, `PUT /heartbeat/{hostname}`, `GET /nodes` |
| `vps` | `/api` | `POST /vps/submit`, VPS-specific lifecycle endpoints |
| `docker` | `/api/docker` | Container environment management, image operations |
| `health` | `/api` | Cluster health metrics |
| `filesystem` | `/api` | Shared storage file browsing and management |
| `auth` | `/api` | Login, logout, register, token management, invitations |

### WebSocket Endpoints

| Path | Purpose |
|------|---------|
| `/ws/task/{task_id}/terminal` | Interactive terminal access to a task container (proxied to Runner) |
| `/ws/docker/host/containers/{name}/terminal` | Direct terminal to Host-local containers |
| `/ws/forward/{task_id}/{port}` | Port forwarding to a container via tunnel protocol |
| `/ws/fs/{task_id}/watch` | Real-time filesystem change notifications |

---

## Runner Services

Each Runner manages the local execution environment on a single compute node.

### Service Modules

| Service | Source File | Purpose |
|---------|------------|---------|
| Task Executor | `runner/services/task_executor.py` | Builds `docker run` commands and executes them via `asyncio.create_subprocess_exec`. Manages task lifecycle (start, monitor, report completion). |
| VPS Manager | `runner/services/vps_manager.py` | Creates long-running Docker containers for VPS sessions. Handles SSH key injection, snapshot/restore, pause/resume. |
| VM VPS Manager | `runner/services/vm_vps_manager.py` | QEMU/KVM virtual machine lifecycle: create disk images (qcow2), launch VMs with cloud-init, manage snapshots, GPU passthrough via VFIO. |
| VM Network Manager | `runner/services/vm_network_manager.py` | Configures bridge networking and TAP interfaces for QEMU VMs. Integrates with the overlay network when enabled. |
| Tunnel Server | `runner/services/tunnel_server.py` | WebSocket server that accepts tunnel-client connections from containers and multiplexes TCP/UDP port forwarding using an 8-byte binary header protocol. |
| Resource Monitor | `runner/services/resource_monitor.py` | Gathers CPU, memory, temperature, and GPU statistics. GPU monitoring uses `nvidia-ml-py` when available. |
| Overlay Manager | `runner/services/overlay_manager.py` | Sets up the runner-side VXLAN interface (`vxlan0`), overlay bridge (`kohaku-overlay`), and associated Docker network. Configures routing and NAT rules. |

### Background Tasks

| Task | Source File | Interval | Purpose |
|------|------------|----------|---------|
| Heartbeat | `runner/background/heartbeat.py` | Every 5s (configurable) | Sends resource metrics and running task list to Host via `PUT /api/heartbeat/{hostname}`. Reports any locally-detected killed tasks. Re-registers if Host returns 404. |
| Startup Check | `runner/background/startup_check.py` | Once at boot | Reconciles local container state with the Host. Detects orphaned containers from previous runs. Recovers VPS sessions that survived a Runner restart. |

### NUMA Support

The Runner detects NUMA topology at startup via `runner/numa/detector.py` and reports it during registration. When a task specifies `target_numa_node_id`, the executor prepends `numactl --cpunodebind=N --membind=N` to the command inside the container.

---

## Communication Patterns

### Runner to Host

```
Runner ──[PUT /api/heartbeat/{hostname}]──> Host     (every 5 seconds)
Runner ──[POST /api/update]──────────────> Host      (task status changes)
Runner ──[POST /api/register]────────────> Host      (on startup, with retry)
Runner ──[POST /api/ip/reserve]──────────> Host      (before container creation, if overlay)
```

**Heartbeat payload** includes: running task IDs, killed task reports, CPU/memory/temperature metrics, GPU stats, and VM capability flags.

**Status update payload** includes: task ID, new status, exit code, error message, timestamps, and SSH port (for VPS tasks).

### Host to Runner

```
Host ──[POST /api/execute]────────> Runner    (command task dispatch)
Host ──[POST /api/vps/create]─────> Runner    (VPS creation)
Host ──[POST /api/kill]───────────> Runner    (kill task)
Host ──[POST /api/pause]──────────> Runner    (pause container)
Host ──[POST /api/resume]─────────> Runner    (resume container)
```

All Host-to-Runner communication uses `httpx.AsyncClient` with timeouts (10-60 seconds depending on operation).

### Container to Runner

```
Container ──[WebSocket /ws/tunnel/{container_id}]──> Runner
```

The tunnel client binary (Rust, compiled for Linux) runs inside the container and establishes a WebSocket connection to the Runner. It uses an 8-byte binary header protocol to multiplex TCP and UDP port forwarding over a single connection.

### VM to Runner

```
VM ──[cloud-init phone-home]──> Runner    (on first boot)
VM ──[heartbeat agent]────────> Runner    (periodic, for liveness)
```

QEMU VMs use cloud-init for initial configuration and a lightweight agent for ongoing heartbeat.

### Client to Host

```
Client ──[REST API]────────────────> Host :8000    (task submission, management)
Client ──[WebSocket]───────────────> Host :8000    (terminal, tunnel, filesystem)
Client ──[SSH]─────────────────────> Host :8002    (VPS SSH access)
```

The SSH proxy on port 8002 accepts SSH connections and routes them to the appropriate VPS container based on the target username or task ID.

---

## Data Model

KohakuRiver uses SQLite via Peewee ORM. All tables are created and migrated automatically on Host startup via `initialize_database()`. The database file defaults to `/var/lib/kohakuriver/kohakuriver.db`.

### Core Tables

#### Task

The `tasks` table stores all submitted workloads:

| Column | Type | Description |
|--------|------|-------------|
| `task_id` | BigInteger (PK) | Snowflake ID, globally unique |
| `task_type` | CharField | `command` or `vps` |
| `batch_id` | BigInteger | Links tasks submitted together |
| `command` | TextField | Command to execute (or SSH pubkey for VPS) |
| `arguments` | TextField (JSON) | Command arguments as JSON array |
| `env_vars` | TextField (JSON) | Environment variables as JSON object |
| `required_cores` | Integer | CPU core allocation |
| `required_gpus` | TextField (JSON) | GPU indices as JSON array |
| `required_memory_bytes` | BigInteger | Memory limit |
| `target_numa_node_id` | Integer | NUMA node affinity |
| `name` | CharField | Optional user-friendly name |
| `owner_id` | Integer | References `users.id` |
| `approval_status` | CharField | `null` (auto-approved), `pending`, `approved`, `rejected` |
| `status` | CharField | Current task state (see state machine below) |
| `assigned_node` | CharField | Runner hostname |
| `container_name` | CharField | KohakuRiver environment name |
| `registry_image` | CharField | Docker registry image (e.g., `ubuntu:22.04`) |
| `vps_backend` | CharField | `docker` or `qemu` |
| `vm_image` | CharField | Base VM image name (QEMU only) |
| `ssh_port` | Integer | SSH port for VPS tasks |
| `exit_code` | Integer | Process exit code |
| `error_message` | TextField | Error details |
| `submitted_at` | DateTime | Submission timestamp |
| `started_at` | DateTime | Execution start timestamp |
| `completed_at` | DateTime | Completion timestamp |

#### Node

The `nodes` table tracks registered Runner nodes:

| Column | Type | Description |
|--------|------|-------------|
| `hostname` | CharField (PK) | Unique node identifier |
| `url` | CharField | Runner API URL (e.g., `http://192.168.1.101:8001`) |
| `total_cores` | Integer | Available CPU cores |
| `memory_total_bytes` | BigInteger | Total RAM |
| `status` | CharField | `online` or `offline` |
| `last_heartbeat` | DateTime | Last heartbeat timestamp |
| `cpu_percent` | Float | Current CPU utilization |
| `memory_percent` | Float | Current memory utilization |
| `numa_topology` | TextField (JSON) | NUMA node to CPU core mapping |
| `gpu_info` | TextField (JSON) | GPU device details |
| `vm_capable` | Boolean | Whether QEMU/KVM is available |
| `vfio_gpus` | TextField (JSON) | VFIO-capable GPUs for passthrough |

### Authentication Tables

| Table | Purpose |
|-------|---------|
| `users` | User accounts with bcrypt password hashes. Role field: `anony`, `viewer`, `user`, `operator`, `admin`. |
| `sessions` | Cookie-based sessions with expiration (default 30 days). |
| `tokens` | API tokens stored as SHA3-512 hashes. Plaintext shown only on creation. |
| `invitations` | Registration tokens with role, usage limits, and expiration. |
| `groups` | User groups with JSON-based resource quotas (max tasks, max VPS, GPU cap). |
| `user_groups` | Many-to-many user-group membership with optional role override. |
| `vps_assignments` | Many-to-many mapping of VPS tasks to authorized users. |

### Task State Machine

```
                  ┌──────────┐
                  |  PENDING  |
                  └────┬─────┘
                       |  Host assigns to Runner
                  ┌────┴──────┐
                  | ASSIGNING |
                  └────┬──────┘
                       |  Runner acknowledges
                  ┌────┴────┐
            ┌─────| RUNNING |─────┐
            |     └────┬────┘     |
            |          |          |
       ┌────┴───┐     |     ┌────┴─────┐
       | PAUSED |     |     | STOPPED  |
       └────┬───┘     |     └──────────┘
            |         |
            └─────┬───┘
                  |
     ┌────────────┼────────────┬────────────┐
     |            |            |            |
┌────┴─────┐ ┌───┴──┐ ┌──────┴──┐ ┌───────┴────┐
| COMPLETED| |FAILED| | KILLED  | | KILLED_OOM |
└──────────┘ └──────┘ └─────────┘ └────────────┘

                  ┌──────┐
                  | LOST |   (Runner went offline)
                  └──────┘
```

Terminal states: `COMPLETED`, `FAILED`, `KILLED`, `KILLED_OOM`, `STOPPED`, `LOST`.

VPS tasks can recover from `LOST` back to `RUNNING` if the Runner comes back online and the container is still alive.

---

## Configuration Model

Both Host and Runner use Python dataclasses for configuration. The global config instance is created at module import time and can be modified before server startup.

### Host Configuration (`host/config.py`)

```python
@dataclass
class HostConfig:
    # Network
    HOST_BIND_IP: str = "0.0.0.0"
    HOST_PORT: int = 8000
    HOST_SSH_PROXY_PORT: int = 8002
    HOST_REACHABLE_ADDRESS: str = "127.0.0.1"  # CRITICAL: must be set to actual IP

    # Paths
    SHARED_DIR: str = "/mnt/cluster-share"
    DB_FILE: str = "/var/lib/kohakuriver/kohakuriver.db"

    # Timing
    HEARTBEAT_INTERVAL_SECONDS: int = 5
    HEARTBEAT_TIMEOUT_FACTOR: int = 6        # Dead after 30s of silence

    # Docker
    DEFAULT_CONTAINER_NAME: str = "kohakuriver-base"
    INITIAL_BASE_IMAGE: str = "python:3.12-alpine"

    # Overlay
    OVERLAY_ENABLED: bool = False
    OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"
    OVERLAY_VXLAN_ID: int = 100
    OVERLAY_VXLAN_PORT: int = 4789

    # Auth
    AUTH_ENABLED: bool = False
    ADMIN_SECRET: str = ""
    SESSION_EXPIRE_HOURS: int = 720          # 30 days
```

### Runner Configuration (`runner/config.py`)

```python
@dataclass
class RunnerConfig:
    # Network
    RUNNER_BIND_IP: str = "0.0.0.0"
    RUNNER_PORT: int = 8001
    HOST_ADDRESS: str = "127.0.0.1"
    HOST_PORT: int = 8000

    # Paths
    SHARED_DIR: str = "/mnt/cluster-share"
    LOCAL_TEMP_DIR: str = "/tmp/kohakuriver"

    # Docker
    DOCKER_NETWORK_NAME: str = "kohakuriver-net"
    DOCKER_NETWORK_SUBNET: str = "172.30.0.0/16"
    DOCKER_NETWORK_GATEWAY: str = "172.30.0.1"

    # Tunnel
    TUNNEL_ENABLED: bool = True

    # Snapshots
    AUTO_SNAPSHOT_ON_STOP: bool = True
    MAX_SNAPSHOTS_PER_VPS: int = 3

    # VM (QEMU/KVM)
    VM_IMAGES_DIR: str = "/var/lib/kohakuriver/vm-images"
    VM_INSTANCES_DIR: str = "/var/lib/kohakuriver/vm-instances"
    VM_DEFAULT_MEMORY_MB: int = 4096
    VM_DEFAULT_DISK_SIZE: str = "50G"

    # Overlay (must match Host)
    OVERLAY_ENABLED: bool = False
    OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"
```

### Configuration Loading

User configuration files are plain Python scripts in `~/.kohakuriver/`:

- `host_config.py` -- executed to modify the global `HostConfig` instance
- `runner_config.py` -- executed to modify the global `RunnerConfig` instance

This approach allows arbitrary Python logic in configuration (conditional settings, environment variable reads, computed values) while keeping defaults in the dataclass.

---

## Service Startup Sequence

### Host Startup

The Host startup sequence is defined in `host/app.py:startup_event()`:

```
1. Initialize database
   └─ Connect to SQLite file
   └─ Create tables (Task, Node, auth tables) if not present
   └─ Run column migrations for schema evolution

2. Ensure container directory
   └─ Verify SHARED_DIR/kohakuriver-containers exists
   └─ Create if missing

3. Clean up broken containers
   └─ Remove Docker containers with missing images
      (leftover from failed migrations)

4. Ensure default container environment
   └─ Check for existing tarball in shared storage
   └─ If none: create from INITIAL_BASE_IMAGE, export to tarball

5. Initialize overlay network (if OVERLAY_ENABLED)
   └─ Create OverlayNetworkManager
   └─ Create kohaku-host dummy interface (10.0.0.1/8)
   └─ Recover state from existing vxkr* VXLAN interfaces
   └─ Initialize IPReservationManager

6. Start background tasks
   └─ Runner monitor (dead node detection)
   └─ Health data collator
   └─ SSH proxy server (port 8002)
```

### Runner Startup

The Runner startup sequence is defined in `runner/app.py:startup_event()`:

```
1. Check Docker access
   └─ Ping Docker daemon
   └─ Ensure kohakuriver-net bridge network exists
   └─ Create network if missing (172.30.0.0/16)

2. Verify directories
   └─ Check SHARED_DIR exists
   └─ Create shared_data subdirectory if missing
   └─ Create LOCAL_TEMP_DIR if missing

3. Initialize task state store
   └─ Open local SQLite database for ephemeral task tracking
   └─ Set dependencies on endpoint modules

4. Detect NUMA topology
   └─ Enumerate NUMA nodes and their CPU core mappings

5. Register with Host (up to 5 retries)
   └─ POST /api/register with hostname, URL, cores, RAM, NUMA, GPU info
   └─ Receive overlay configuration from Host response

6. Set up overlay network (if configured)
   └─ Create VXLAN interface to Host
   └─ Create overlay bridge and Docker network
   └─ Configure routing and NAT rules

7. Initialize VM network manager
   └─ Set up bridge and TAP interfaces for QEMU VMs

8. Run startup check
   └─ Reconcile local containers with Host state
   └─ Recover orphaned VPS sessions

9. Start heartbeat background task
   └─ Send resource metrics every 5 seconds
   └─ Report killed tasks
   └─ Re-register if Host returns 404
```

---

## Key Design Decisions

### Why Subprocess Docker (Not Docker SDK)

The task executor uses `subprocess` to run `docker run --rm` commands rather than the Docker SDK (`docker-py`). This is a deliberate choice:

| Factor | Subprocess | Docker SDK |
|--------|-----------|------------|
| Signal handling | `exec` replaces shell, Docker handles signals directly | SDK requires explicit signal forwarding |
| GPU passthrough | `--gpus "device=0,1"` flag works natively | SDK GPU support requires complex device requests |
| NUMA binding | `numactl` prefix inside container works naturally | Would need custom entrypoint wrapper |
| Output redirection | Shell `> stdout 2> stderr` redirects directly | Would need stream copying logic |
| Debugging | You can reproduce issues with `docker run` manually | SDK calls are harder to replicate |
| Tunnel integration | Shell command wrapping for tunnel-client startup | Would need custom entrypoint management |

The Docker SDK *is* used for other operations (image management, container listing, network creation) where the programmatic API is more convenient. The separation is intentional: task execution uses subprocess for its shell integration benefits, while administrative operations use the SDK for its convenience.

### Why SQLite

SQLite is used as the sole database for the Host:

| Consideration | Rationale |
|---------------|-----------|
| Deployment simplicity | No external database server to install, configure, or maintain |
| Single-writer model | Only the Host writes to the database; Runners communicate via HTTP |
| Data volume | Cluster metadata is small (thousands of tasks, tens of nodes) |
| Atomic operations | Peewee ORM handles SQLite's write serialization |
| Portability | Database is a single file, easy to back up or move |
| Performance | Adequate for the write patterns (heartbeats, status updates) |

The Runner uses a separate local SQLite database (`runner-state.db`) solely for ephemeral task tracking. This database is not the source of truth -- the Host database is.

### Why VXLAN Hub-and-Spoke

The overlay network uses a hub-and-spoke topology with the Host as the central L3 router:

```
Runner 1 ──VXLAN──> Host (router) <──VXLAN── Runner 2
```

Cross-node container traffic always routes through the Host. This was chosen over a full mesh for several reasons:

| Factor | Hub-and-Spoke | Full Mesh |
|--------|--------------|-----------|
| Tunnel count | N tunnels (one per Runner) | N*(N-1)/2 tunnels |
| Configuration | Each Runner only knows the Host IP | Each Runner needs all other Runner IPs |
| Dynamic scaling | Add a Runner, create one tunnel | Add a Runner, create N-1 tunnels |
| Failure domain | Host failure affects all networking | Any node failure affects its peers |
| NAT traversal | Runners only need to reach Host | Runners may need to reach each other through NAT |
| State recovery | Host recovers from `vxkr*` interfaces | Would need a distributed state protocol |

The tradeoff is that the Host becomes a bottleneck for cross-node container traffic. In practice, this is acceptable because:

1. Most container traffic is to the internet (via Runner-local NAT, bypassing Host entirely)
2. Shared storage handles bulk data transfer (not overlay network)
3. The primary cross-node use case is lightweight service-to-service communication

Each Runner receives a /16 subnet (up to ~65,000 container IPs) and the system supports up to 255 Runners with the default overlay configuration.
