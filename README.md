# KohakuRiver - Lightweight Cluster Manager for Small Teams

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![en](https://img.shields.io/badge/lang-en-red.svg)](./README.md)
[![中文](https://img.shields.io/badge/lang-中文-green.svg)](./README.zh.md)

![KohakuRiver logo svg](image/logo.svg)

**KohakuRiver** is a lightweight, self-hosted cluster manager designed for distributing command-line tasks and launching persistent interactive sessions (**VPS Tasks**) across compute nodes. It leverages **Docker** to manage reproducible task environments, treating containers as portable "virtual environments" that auto-sync across your cluster.

It provides resource allocation (CPU/memory/GPU limits), multi-node/NUMA/GPU task submission, and status tracking, making it ideal for research labs, small-to-medium teams, home labs, or development environments needing simple, reproducible distributed task execution without the overhead of complex HPC schedulers.

## Key Features

| Feature | Description |
|---------|-------------|
| **Container as Portable Environment** | Docker containers function as auto-synced virtual environments. Set up once on Host, package as tarball, and use across all nodes automatically. |
| **Task/VPS System** | **Tasks** for batch command execution, **VPS** for persistent interactive sessions. VPS is crucial for R&D workflows where you can't create a complete Docker image upfront. |
| **VXLAN Overlay Network** | Cross-node container networking with minimal setup. Just set Host IP and open UDP 4789 - automatic VXLAN tunnels, IP allocation, and firewall configuration. |
| **TTY Forwarding** | WebSocket-based terminal access (`kohakuriver connect`) without Docker port mapping. Supports full TTY (vim, htop, etc.) and works even after system restarts. |
| **Port Forwarding** | Dynamic port forwarding (`kohakuriver forward`) through tunnel proxy. Access container services without Docker port mapping, avoiding port conflicts on runner nodes. |
| **Web UI & Terminal TUI** | Web dashboard for visual management, Terminal TUI (`kohakuriver terminal`) with VSCode-like layout, and IDE mode with file tree and integrated terminal. |

## Introduction to KohakuRiver

### Problem Statement

Researchers and small teams often face a challenging middle ground when working with a modest number of compute nodes (typically 3-8 machines). This creates an awkward situation:

- **Too many machines** to manage manually with SSH and shell scripts
- **Too few machines** to justify the overhead of complex HPC schedulers like Slurm
- **Unsuitable complexity** of container orchestration systems like Kubernetes for simple task distribution or single, long-running interactive sessions.

You have these powerful compute resources at your disposal, but no efficient way to utilize them as a unified computing resource without significant operational overhead.

### Core Concept: Your Nodes as One Big Computer

KohakuRiver addresses this problem by letting you treat your small cluster as a single powerful computer, with these key design principles:

- **Lightweight Resource Management**: Distribute command-line tasks and interactive VPS sessions across your nodes with minimal setup
- **Environment Consistency**: Use Docker containers as portable virtual environments, not as complex application deployments
- **Seamless Synchronization**: Automatically distribute container environments to runners without manual setup on each node
- **Familiar Workflow**: Submit tasks through a simple interface that feels like running a command or launching an environment on your local machine

> Docker in KohakuRiver functions as a virtual environment that can be dynamically adjusted and automatically synchronized. You can run dozens of tasks or launch multiple interactive sessions using the same container environment, but execute them on completely different nodes.

### How It Works

1. **Environment Management**: Create and customize Docker containers on the Host node using `kohakuriver docker container` commands and interactive shells.
2. **Package & Distribute**: The environment is packaged as a tarball using `kohakuriver docker tar create` and stored in shared storage.
3. **Automatic Synchronization**: Runner nodes automatically fetch the required environment from shared storage before executing tasks.
4. **Parallel/Interactive Execution**: Submit single commands, batches of parallel tasks, or launch persistent VPS tasks to run across multiple nodes, with each task isolated in its own container instance.

This approach aligns with the philosophy that:

> For a small local cluster, you should prioritize solutions that are "lightweight, simple, and just sufficient." You shouldn't need to package every command into a complex Dockerfile - Docker's purpose here is environment management and synchronization.

KohakuRiver is built on the assumption that in small local clusters:

- Nodes can easily establish network communication
- Shared storage is readily available
- Doesn't require authentication or the complexity can be minimized
- High availability and fault tolerance are less critical at this scale

By focusing on these practical realities of small-scale computing, KohakuRiver provides a "just right" solution for multi-node task execution and interactive environments without the administrative burden of enterprise-grade systems.

---

## What KohakuRiver Is (and Isn't)

| KohakuRiver IS FOR... | KohakuRiver IS NOT FOR... |
|:------------------------------------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------------------------------------------------------------|
| ✅ Managing command-line tasks/scripts and persistent VPS sessions across small clusters (typically < 10-20 nodes). | ❌ Replacing feature-rich HPC schedulers (Slurm, PBS, LSF) on large-scale clusters. |
| ✅ **Executing tasks & VPS sessions within reproducible Docker container environments (managed by KohakuRiver).** | ❌ Orchestrating complex, multi-service applications (like Kubernetes or Docker Compose). |
| ✅ **Interactive environment setup on the Host and packaging these environments as portable tarballs for distribution.** | ❌ Automatically managing complex software dependencies *within* containers (user sets up the env via Host's shell). |
| ✅ **Conveniently submitting independent command-line tasks, batches of parallel tasks, or single-instance VPS sessions across nodes/NUMA zones/GPUs.** | ❌ Sophisticated task dependency management or complex workflow orchestration (Use Airflow, Prefect, Snakemake, Nextflow). |
| ✅ Providing on-demand interactive compute environments with SSH access (VPS tasks). | ❌ Providing highly available, load-balanced production *services* accessible directly by external users. |
| ✅ Personal, research lab, small team, or Home Lab usage needing a *simple* multi-node task/VPS management system. | ❌ Deploying or managing highly available, mission-critical production *services*. |
| ✅ Providing a lightweight system with minimal maintenance overhead for distributed task execution in controlled environments. | ❌ High-security, multi-tenant environments requiring robust built-in authentication and authorization layers. |

---

## Features

### Container Environment Management
- **Managed Docker Workflow:** Set up containers on Host (`kohakuriver docker container create`), customize interactively (`kohakuriver docker container shell`), package as tarballs (`kohakuriver docker tar create`).
- **Auto-Sync:** Runners automatically fetch and update container tarballs from shared storage before task execution.

### Task Execution
- **Command Tasks:** One-shot command execution in Docker containers with resource limits.
- **VPS Tasks:** Persistent interactive containers with SSH access - ideal for R&D where you need to iterate on your environment.
- **Multi-Target Submission:** Submit tasks to multiple nodes/NUMA nodes/GPUs in one command.

### Access & Connectivity (Without Docker Port Mapping)
- **TTY Forwarding (`kohakuriver connect`):** WebSocket-based terminal with full TTY support (vim, htop, etc.). Works with long-running containers across system restarts.
- **Port Forwarding (`kohakuriver forward`):** Dynamic TCP/UDP port forwarding through tunnel proxy. Access container services (web servers, databases, Jupyter) without port conflicts.
- **SSH Proxy:** Connect to VPS via SSH through Host relay (`kohakuriver vps connect`) without knowing runner IPs or dynamic ports.

### Resource Management
- **CPU/Memory Allocation:** Request specific cores (`-c/--cores`) and memory limits (`-m/--memory`).
- **GPU Allocation:** Target specific GPUs (`--target node::gpu_id1,gpu_id2`).
- **NUMA Binding:** Bind tasks to NUMA nodes (`--target node:numa_id`).

### Cross-Node Networking (VXLAN Overlay)
- **Automatic Setup:** Just set `HOST_REACHABLE_ADDRESS` and open UDP port 4789 - KohakuRiver handles the rest.
- **L3 Routed Topology:** Host acts as central router with VXLAN tunnels to each runner.
- **Automatic IP Allocation:** Each runner gets a /16 subnet (10.X.0.0/16) with up to 65,532 container IPs.
- **Firewall Auto-Configuration:** iptables rules and firewalld trusted zones configured automatically.
- **State Recovery:** VXLAN tunnels persist through Host/Runner restarts.
- **Cross-Node Communication:** Containers on different runners can communicate directly via overlay IPs.

### Monitoring & UI
- **Web Dashboard:** Vue.js frontend with cluster overview, task/VPS submission, Docker management, and web-based terminal.
- **Terminal TUI (`kohakuriver terminal`):** Full-screen dashboard with node status, task lists, and keyboard navigation.
- **IDE Mode (`kohakuriver connect --ide`):** TUI IDE with file tree, code editor, and integrated terminal panel.
- **Task Control:** Pause, resume, and kill tasks via CLI or Web UI.

---

## Quick Start Guide

### Prerequisites

- Python >= 3.10
- Access to a shared filesystem mounted on the Host and all Runner nodes.
- **Host Node:** Docker Engine installed (for managing environments and creating tarballs).
- **Runner Nodes:** Docker Engine installed (for executing containerized tasks and VPS). `numactl` is optional (only needed for NUMA binding features). `nvidia-ml-py` and NVIDIA drivers are optional (only needed for GPU reporting/allocation).
- **Client Machines:** SSH client installed (`ssh` command).
- **Docker Engine**: Ensure the data-root and storage driver are set up correctly. Run `docker run hello-world` to verify Docker is working correctly.

### Steps

1. **Install KohakuRiver** (on Host, all Runner nodes, and Client machines):

   ```bash
   # Clone the repository
   git clone https://github.com/KohakuBlueleaf/KohakuRiver.git
   cd KohakuRiver

   # Install
   pip install .

   # With GPU monitoring support (requires nvidia-ml-py & nvidia drivers)
   pip install ".[gpu]"
   ```

2. **Configure KohakuRiver** (on Host, all Runners, and Client machines):

   ```bash
   # Generate default config files
   kohakuriver init config --generate
   ```

   Edit the configuration files:
   - **Host config** (`~/.kohakuriver/host_config.py`):
     - **Crucial**: Set `HOST_REACHABLE_ADDRESS` to the Host's IP/hostname accessible by Runners/Clients.
     - **Crucial**: Set `SHARED_DIR` to your shared storage path (e.g., `/mnt/cluster-share`).
   - **Runner config** (`~/.kohakuriver/runner_config.py`):
     - **Crucial**: Set `HOST_ADDRESS` to the Host's IP/hostname.
     - **Crucial**: Set `SHARED_DIR` to the same shared storage path.

3. **Start Host Server** (on the manager node):

   ```bash
   kohakuriver.host
   # Or use a specific config: kohakuriver.host --config /path/to/host_config.py
   ```

   **For Systemd (recommended for production):**
   ```bash
   kohakuriver init service --host
   sudo systemctl start kohakuriver-host
   sudo systemctl enable kohakuriver-host
   ```

4. **Start Runner Agents** (on each compute node):

   ```bash
   kohakuriver.runner
   # Or use a specific config: kohakuriver.runner --config /path/to/runner_config.py
   ```

   **For Systemd:**
   ```bash
   kohakuriver init service --runner
   sudo systemctl start kohakuriver-runner
   sudo systemctl enable kohakuriver-runner
   ```

5. **(Optional) Prepare a Docker Environment** (on the Client/Host):

   ```bash
   # Create a base container on the Host
   kohakuriver docker container create python:3.12-slim my-py312-env

   # Install software interactively
   kohakuriver docker container shell my-py312-env
   # (inside container) pip install numpy pandas torch
   # (inside container) exit

   # Package it into a tarball
   kohakuriver docker tar create my-py312-env
   ```

6. **Submit Your First Task** (from the Client machine):

   ```bash
   # Submit a simple echo command using the default Docker env to node1
   kohakuriver task submit -t node1 -- echo "Hello KohakuRiver!"

   # Submit a Python script using your custom env on node2 with 2 cores
   # (Assuming myscript.py is in the shared dir, accessible via /shared)
   kohakuriver task submit -t node2 -c 2 --container my-py312-env -- python /shared/myscript.py

   # Submit a GPU command task to node3 using GPU 0 and 1
   kohakuriver task submit -t node3::0,1 --container my-cuda-env -- python /shared/train_gpu_model.py
   ```

7. **Launch a VPS Task** (from the Client machine):

   ```bash
   # Create a VPS with 4 cores and 8GB memory
   kohakuriver vps create -t node1 -c 4 -m 8G

   # Connect via SSH proxy
   kohakuriver vps connect <task_id>

   # Or use WebSocket terminal (works without Docker port mapping)
   kohakuriver connect <task_id>

   # Or open TUI IDE with file tree and terminal
   kohakuriver connect <task_id> --ide
   ```

8. **Forward Ports to Container Services** (without Docker port mapping):

   ```bash
   # Forward local port 8888 to Jupyter running on container port 8888
   kohakuriver forward <task_id> 8888

   # Forward local port 3000 to container port 80
   kohakuriver forward <task_id> 80 --local-port 3000

   # Forward UDP traffic
   kohakuriver forward <task_id> 5353 --proto udp
   ```

9. **Use Terminal TUI Dashboard**:

   ```bash
   # Launch full-screen dashboard
   kohakuriver terminal
   ```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Clients: CLI / Web Dashboard / Terminal TUI                │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP/WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│  HOST SERVER (Port 8000)                                    │
│  - Task scheduling and dispatch                             │
│  - Node registration and health monitoring                  │
│  - Docker environment management                            │
│  - SSH proxy for VPS access (Port 8002)                     │
│  - WebSocket proxy for terminal and port forwarding         │
│  - SQLite database for state                                │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  RUNNER 1       │ │  RUNNER 2       │ │  RUNNER N       │
│  Port 8001      │ │  Port 8001      │ │  Port 8001      │
│  - Task exec    │ │  - Task exec    │ │  - Task exec    │
│  - VPS mgmt     │ │  - VPS mgmt     │ │  - VPS mgmt     │
│  - Resource mon │ │  - Resource mon │ │  - Resource mon │
│  - Tunnel srv   │ │  - Tunnel srv   │ │  - Tunnel srv   │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                 │                 │
         ▼                 ▼                 ▼
    ┌─────────┐       ┌─────────┐       ┌─────────┐
    │Container│       │Container│       │Container│
    │(tunnel- │       │(tunnel- │       │(tunnel- │
    │ client) │       │ client) │       │ client) │
    └─────────┘       └─────────┘       └─────────┘

┌─────────────────────────────────────────────────────────────┐
│  SHARED STORAGE (/mnt/cluster-share)                        │
│  - kohakuriver-containers/  (Docker tarballs)               │
│  - shared_data/             (Mounted as /shared in tasks)   │
└─────────────────────────────────────────────────────────────┘
```

### TTY and Port Forwarding Architecture

The tunnel system enables access to container services without Docker port mapping:

```
End user/application
        │
        ▼ TCP/UDP (for Port forwarding)
kohakuriver connect/forward
        │
        ▼ WebSocket
   HOST (proxy) ------> RUNNER (tunnel server) ------> Container
                                                        (tunnel-client)
                                                            │
                                                            ▼ TCP/UDP (for Port forwarding)
                                                      Service inside Container
```

This design allows:
- Long-running containers to survive system restarts
- Multiple services on same port across different containers (no port conflicts)
- Secure access through Host without exposing runner nodes directly

---

## CLI Reference

### Task Management
```bash
kohakuriver task list                      # List all tasks
kohakuriver task submit [OPTIONS] -- CMD   # Submit a command task
kohakuriver task status <task_id>          # Get task status
kohakuriver task logs <task_id>            # View task output
kohakuriver task kill <task_id>            # Kill a running task
kohakuriver task pause <task_id>           # Pause a task
kohakuriver task resume <task_id>          # Resume a paused task
```

### VPS Management
```bash
kohakuriver vps list                       # List VPS instances
kohakuriver vps create [OPTIONS]           # Create a VPS
kohakuriver vps stop <task_id>             # Stop a VPS
kohakuriver vps connect <task_id>          # SSH to VPS via proxy
kohakuriver vps restart <task_id>          # Restart a VPS
```

### Terminal & Port Access
```bash
kohakuriver connect <task_id>              # WebSocket terminal (full TTY)
kohakuriver connect <task_id> --ide        # TUI IDE with file tree & terminal
kohakuriver forward <task_id> <port>       # Forward local port to container
kohakuriver forward <task_id> <port> -l <local_port>  # Custom local port
kohakuriver forward <task_id> <port> --proto udp      # UDP forwarding
kohakuriver terminal                       # Launch Terminal TUI dashboard
```

### Node Management
```bash
kohakuriver node list                      # List registered nodes
kohakuriver node overlay                   # View overlay network status
kohakuriver status                         # Quick cluster overview
```

### Docker Management
```bash
kohakuriver docker container list          # List Host containers
kohakuriver docker container create IMG NAME  # Create container from image
kohakuriver docker container shell NAME    # Shell into container
kohakuriver docker container start NAME    # Start a container
kohakuriver docker container stop NAME     # Stop a container
kohakuriver docker container delete NAME   # Delete a container
kohakuriver docker tar list                # List tarballs
kohakuriver docker tar create NAME         # Create tarball from container
kohakuriver docker tar delete NAME         # Delete a tarball
```

### Configuration
```bash
kohakuriver init config --all              # Generate all config files
kohakuriver init config --host             # Generate host config only
kohakuriver init config --runner           # Generate runner config only
kohakuriver init service --all             # Register all systemd services
kohakuriver init service --host            # Register host service
kohakuriver init service --runner          # Register runner service
```

---

## Configuration

Configuration files use Python with KohakuEngine. They are auto-loaded from `~/.kohakuriver/` if present.

### Host Configuration (`~/.kohakuriver/host_config.py`)

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `HOST_BIND_IP` | str | `"0.0.0.0"` | IP address the Host server binds to |
| `HOST_PORT` | int | `8000` | API server port |
| `HOST_SSH_PROXY_PORT` | int | `8002` | SSH proxy port for VPS access |
| `HOST_REACHABLE_ADDRESS` | str | `"127.0.0.1"` | **CRITICAL**: IP/hostname runners use to reach Host (and VXLAN local IP) |
| `SHARED_DIR` | str | `"/mnt/cluster-share"` | Shared storage path (must match on all nodes) |
| `DB_FILE` | str | `"/var/lib/kohakuriver/kohakuriver.db"` | SQLite database path |
| `DEFAULT_CONTAINER_NAME` | str | `"kohakuriver-base"` | Default environment for tasks |
| `OVERLAY_ENABLED` | bool | `False` | Enable VXLAN overlay networking |

### Runner Configuration (`~/.kohakuriver/runner_config.py`)

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `RUNNER_BIND_IP` | str | `"0.0.0.0"` | IP address the Runner binds to |
| `RUNNER_PORT` | int | `8001` | Runner API port |
| `HOST_ADDRESS` | str | `"127.0.0.1"` | **CRITICAL**: Host server address |
| `HOST_PORT` | int | `8000` | Host server port |
| `SHARED_DIR` | str | `"/mnt/cluster-share"` | Shared storage path (must match Host) |
| `LOCAL_TEMP_DIR` | str | `"/tmp/kohakuriver"` | Local temporary storage |
| `OVERLAY_ENABLED` | bool | `False` | Enable VXLAN overlay networking |

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `KOHAKURIVER_HOST` | Host server address | `localhost` |
| `KOHAKURIVER_PORT` | Host server port | `8000` |
| `KOHAKURIVER_SSH_PROXY_PORT` | SSH proxy port | `8002` |
| `KOHAKURIVER_SHARED_DIR` | Shared storage path | `/mnt/cluster-share` |

---

## Web Dashboard

The Vue.js frontend provides:
- Cluster overview with node status and resource monitoring
- Task submission with target selection and resource configuration
- VPS creation with SSH key management
- Docker environment management (containers and tarballs)
- Web-based terminal access to containers and tasks
- GPU utilization monitoring

```bash
cd src/kohakuriver-manager
npm install
npm run dev
```

---

## Requirements Summary

| Component | Requirements |
|-----------|-------------|
| **Host Node** | Docker Engine, Python >= 3.10, Shared storage access |
| **Runner Nodes** | Docker Engine, Python >= 3.10, Shared storage access, Optional: `numactl`, `nvidia-ml-py` |
| **Client Machines** | Python >= 3.10, SSH client |
| **Shared Storage** | NFS or similar, same mount path on all nodes, read/write access |

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

If you need a license exemption for commercial or proprietary use, please contact: **kohaku@kblueleaf.net**
