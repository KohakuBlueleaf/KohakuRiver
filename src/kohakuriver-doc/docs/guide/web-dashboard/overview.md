---
title: Web Dashboard Overview
description: Overview of the KohakuRiver web dashboard built with Vue.js.
icon: i-carbon-dashboard
---

# Web Dashboard Overview

KohakuRiver includes a Vue.js 3 web dashboard that provides a graphical interface for managing tasks, VPS instances, nodes, and users. The dashboard communicates with the host API at `http://host:8000`.

## Technology Stack

| Component          | Technology                                   |
| ------------------ | -------------------------------------------- |
| Framework          | Vue.js 3 (Composition API, `<script setup>`) |
| Build Tool         | Vite                                         |
| UI Library         | Element Plus                                 |
| State Management   | Pinia                                        |
| Terminal Emulation | xterm.js                                     |
| Charts             | Plotly.js                                    |
| Language           | JavaScript (no TypeScript)                   |

The frontend source is at `src/kohakuriver-manager/`.

## Accessing the Dashboard

The dashboard is served by the host's FastAPI server:

```
http://<host_address>:8000
```

### Development Mode

For development with hot-reload:

```bash
cd src/kohakuriver-manager
npm install
npm run dev
```

The dev server proxies API requests to the host backend.

### Production Build

```bash
cd src/kohakuriver-manager
npm run build
```

The build output is served by the host's static file handler.

## Dashboard Views

### Cluster Overview

The main dashboard provides a summary of:

- Total nodes and their online/offline status
- Running tasks count
- Active VPS instances
- Cluster resource utilization

### Node Monitoring

Real-time node health with Plotly charts:

- CPU utilization over time
- Memory usage trends
- GPU utilization and memory per GPU
- Temperature monitoring (CPU and GPU)
- Per-node status indicators

See [Node Monitoring](node-monitoring.md) for details.

### Task Management

Task list with filtering and management:

- Filter by status (running, completed, failed, etc.)
- View task details (command, resources, timing)
- View stdout/stderr logs
- Kill, pause, or resume tasks

See [Task Management](task-management.md) for details.

### VPS Management

VPS instance management with interactive features:

- Create new VPS instances (Docker or QEMU backend)
- Start, stop, restart VPS
- Web-based terminal via xterm.js
- Snapshot management
- SSH connection information

See [VPS Management](vps-management.md) for details.

### Admin Panel

User and access management (when authentication is enabled):

- User list and role management
- Token management
- Task approval queue

See [Admin Panel](admin-panel.md) for details.

## Authentication

When the host has `AUTH_ENABLED = True`, the dashboard presents a login screen. Users authenticate with username/password or API token:

1. Enter credentials on the login page
2. The dashboard stores the session token
3. All subsequent API requests include the authentication header
4. Session expires after `SESSION_EXPIRE_HOURS` (default: 24 hours)

Without authentication enabled, the dashboard provides full access without login.

## API Communication

The dashboard communicates with the host via REST API:

| Endpoint Pattern              | Description                  |
| ----------------------------- | ---------------------------- |
| `GET /api/nodes`              | Fetch node list and health   |
| `GET /api/tasks`              | Fetch task list with filters |
| `POST /api/submit`            | Submit new tasks             |
| `POST /api/vps/create`        | Create VPS instances         |
| `GET /api/vps/snapshots/<id>` | Fetch snapshots              |
| `WS /api/ws/terminal/<id>`    | WebSocket terminal           |
| `WS /api/ws/tunnel/<id>`      | WebSocket tunnel             |

## WebSocket Features

The dashboard uses WebSocket connections for real-time features:

- **Terminal**: xterm.js connects via WebSocket for interactive container terminals
- **Log streaming**: Live task log following
- **Status updates**: Real-time task and node status changes

## Related Topics

- [Task Management](task-management.md) -- Managing tasks via the dashboard
- [VPS Management](vps-management.md) -- Managing VPS via the dashboard
- [Node Monitoring](node-monitoring.md) -- Monitoring nodes and resources
- [Admin Panel](admin-panel.md) -- User and access management
