---
title: Port Reference
description: All network ports used by KohakuRiver services and their purpose.
icon: i-carbon-port-input
---

# Port Reference

KohakuRiver uses several network ports for inter-service communication, user access, and overlay networking. This page lists all ports and which component uses them.

## Service Ports

| Port | Protocol | Service             | Component | Configurable          |
| ---- | -------- | ------------------- | --------- | --------------------- |
| 8000 | TCP/HTTP | Host API server     | Host      | `HOST_PORT`           |
| 8001 | TCP/HTTP | Runner API server   | Runner    | `RUNNER_PORT`         |
| 8002 | TCP      | SSH proxy server    | Host      | `HOST_SSH_PROXY_PORT` |
| 5173 | TCP/HTTP | Web dashboard (dev) | Frontend  | `vite.config.js`      |

### Host Server (port 8000)

The host server exposes both HTTP REST endpoints (under `/api`) and WebSocket endpoints (under `/ws`). All client-facing communication goes through this port:

- REST API for task submission, node management, VPS control
- WebSocket terminal proxy for interactive shell access
- WebSocket filesystem watch proxy for real-time file notifications
- WebSocket port forwarding proxy to reach services inside containers

### Runner Server (port 8001)

Each runner node listens on this port. The host communicates with runners through this port for:

- Task execution dispatch
- VPS creation and lifecycle control
- Docker image synchronization
- Container filesystem operations
- WebSocket tunnel connections from in-container tunnel clients
- WebSocket port forwarding sessions

### SSH Proxy (port 8002)

The host runs an SSH proxy server that allows CLI users to SSH into VPS instances without direct runner access. VPS SSH sessions are multiplexed through this single port.

### Web Dashboard (port 5173)

The Vite development server for the Vue.js management dashboard. In development mode, it proxies `/api` and `/ws` requests to `localhost:8000`. In production, the built frontend is served directly by the host or a reverse proxy.

## VPS SSH Ports

| Port Range | Protocol | Purpose                                 |
| ---------- | -------- | --------------------------------------- |
| 2222+      | TCP      | VPS SSH access (allocated sequentially) |

Each VPS instance is assigned an SSH port starting from `2222`. Ports are allocated sequentially, skipping any already in use by active VPS instances. These ports are used by the SSH proxy on the host to route connections to the correct runner and container.

## Overlay Network Ports

| Port | Protocol | Purpose                    | Configurable         |
| ---- | -------- | -------------------------- | -------------------- |
| 4789 | UDP      | VXLAN tunnel encapsulation | `OVERLAY_VXLAN_PORT` |

When the VXLAN overlay network is enabled, UDP port 4789 carries encapsulated L2 frames between the host and all runner nodes. This port must be open in firewalls between the host and every runner.

## Docker Network Subnets

These are internal container network ranges, not externally exposed ports:

| Network               | Default Subnet   | Default Gateway    | Purpose                          |
| --------------------- | ---------------- | ------------------ | -------------------------------- |
| `kohakuriver-net`     | `172.30.0.0/16`  | `172.30.0.1`       | Default container bridge network |
| `kohakuriver-overlay` | Assigned by host | Per-runner gateway | Overlay container network        |
| `kohaku-br0`          | `10.200.0.0/24`  | `10.200.0.1`       | VM NAT bridge (non-overlay mode) |

## Overlay Network Subnets

When overlay is enabled, the host allocates subnets from the configured overlay address space:

| Default Config    | Value           | Description                                           |
| ----------------- | --------------- | ----------------------------------------------------- |
| Overlay CIDR      | `10.128.0.0/12` | Full overlay address space                            |
| Per-runner subnet | `/16` derived   | Each runner gets a /16 subnet (e.g., `10.128.0.0/16`) |
| VXLAN base ID     | `100`           | Each runner gets `base_id + runner_id`                |
| MTU               | `1450`          | Accounts for 50-byte VXLAN overhead                   |

## Tunnel Port Forwarding

The tunnel system does not use fixed ports. Instead, it multiplexes TCP and UDP connections over WebSocket using an 8-byte binary header protocol:

| Header Field | Size    | Description                      |
| ------------ | ------- | -------------------------------- |
| Message type | 1 byte  | CONNECT, CONNECTED, DATA, CLOSE  |
| Protocol     | 1 byte  | TCP (1) or UDP (2)               |
| Client ID    | 2 bytes | Multiplexing session identifier  |
| Port         | 2 bytes | Target port inside the container |
| Reserved     | 2 bytes | Unused                           |

Users access container services through the host WebSocket endpoint `/ws/forward/{task_id}/{port}`, which proxies to the runner, which forwards through the tunnel to the container.

## Firewall Requirements

For a minimal deployment, ensure these ports are accessible:

| Direction            | Port | Protocol | Required By                         |
| -------------------- | ---- | -------- | ----------------------------------- |
| Clients to Host      | 8000 | TCP      | API and WebSocket access            |
| Clients to Host      | 8002 | TCP      | SSH proxy access (if using VPS SSH) |
| Host to Runners      | 8001 | TCP      | Task dispatch and management        |
| Host to/from Runners | 4789 | UDP      | Overlay network (if enabled)        |

## Related Topics

- [Configuration Reference](configuration.md) -- Setting port values
- [Host API Reference](api-host.md) -- Endpoints on port 8000
- [Runner API Reference](api-runner.md) -- Endpoints on port 8001
