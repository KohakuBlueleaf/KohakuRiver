---
title: Task Monitoring
description: Monitoring task status, logs, and resource usage in KohakuRiver.
icon: i-carbon-activity
---

# Task Monitoring

KohakuRiver provides multiple ways to monitor tasks, nodes, and cluster health.

## Task Status

### Single Task

```bash
kohakuriver task status <task_id>
```

Shows detailed information including:

- Task type, status, and exit code
- Assigned node and resource allocation
- Timestamps (submitted, started, completed)
- Container configuration
- Error messages (if failed)

### Task List

```bash
# Recent tasks
kohakuriver task list

# Filter by status
kohakuriver task list -s running
kohakuriver task list -s failed

# Filter by node
kohakuriver task list -n mynode

# Limit results
kohakuriver task list -l 100

# Compact view
kohakuriver task list -c
```

### Live Monitoring

```bash
# Watch a specific task's status updates
kohakuriver task watch <task_id>
```

## Task Logs

### View Output

```bash
# Stdout
kohakuriver task logs <task_id>

# Stderr
kohakuriver task logs <task_id> --stderr

# Follow output in real-time
kohakuriver task logs <task_id> -f
```

Log files are stored at `SHARED_DIR/logs/<task_id>/stdout.log` and `stderr.log`.

## Node Health

### All Nodes

```bash
kohakuriver node list
kohakuriver node health
```

### Specific Node

```bash
kohakuriver node status <hostname>
kohakuriver node health <hostname>
```

Node health includes:

- CPU utilization percentage
- Memory usage (used/total, percentage)
- Temperature (average, maximum)
- GPU metrics (utilization, memory, temperature per GPU)
- Online/offline status and last heartbeat time

### Cluster Summary

```bash
kohakuriver node summary
```

Aggregated cluster statistics across all nodes.

## TUI Dashboard

Launch a full-screen terminal dashboard:

```bash
kohakuriver terminal
```

The dashboard shows:

- **Dashboard view** (key: 1) -- Cluster overview
- **Nodes view** (key: 2) -- Node list with health metrics
- **Tasks view** (key: 3) -- Task list with filtering
- **VPS view** (key: 4) -- VPS instance list

Navigation keys:

- `1-4` -- Switch views
- `f` -- Filter tasks (in Tasks view)
- `r` -- Refresh data
- `q` -- Quit

Options:

```bash
kohakuriver terminal --host 192.168.1.100 --port 8000 --refresh 2.0
```

## Web Dashboard

The Vue.js web dashboard at `http://host:8000` provides:

- Real-time node monitoring with GPU graphs (Plotly)
- Task management with status filtering
- VPS management with terminal access (xterm.js)
- Admin panel for user management

See [Web Dashboard Overview](../web-dashboard/overview.md).

## Container Attach

For debugging, attach directly to a running container:

```bash
# WebSocket terminal (recommended)
kohakuriver connect <task_id>

# Direct Docker exec (requires Docker access on the runner)
kohakuriver terminal attach <task_id>

# Execute a command in a running container
kohakuriver terminal exec <task_id> -- ps aux
```

## Programmatic Monitoring

Use the host API directly:

```bash
# Get task status
curl http://host:8000/api/tasks/<task_id>

# List tasks
curl http://host:8000/api/tasks?status=running

# Get node status
curl http://host:8000/api/nodes

# Health check
curl http://host:8000/api/health
```
