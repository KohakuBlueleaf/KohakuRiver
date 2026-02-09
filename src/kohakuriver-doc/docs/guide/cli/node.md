---
title: kohakuriver node
description: Node management and monitoring commands.
icon: i-carbon-network-3
---

# kohakuriver node

The `kohakuriver node` command group provides node monitoring, overlay network management, and IP reservation.

## Node Monitoring Commands

### node list

List all registered nodes.

```bash
kohakuriver node list
```

Displays a table with hostname, status, URL, cores, memory, GPU count, and last heartbeat.

### node status

Show detailed status for a specific node.

```bash
kohakuriver node status <hostname>
```

Displays:

- Online/offline status and last heartbeat
- CPU cores (total, allocated, available)
- Memory (total, used, allocated, available)
- NUMA topology (if multi-NUMA)
- Per-GPU metrics (name, utilization, memory, temperature)
- VM capability and VFIO GPU list
- Runner version

### node health

Show health metrics for one or all nodes.

```bash
# All nodes
kohakuriver node health

# Specific node
kohakuriver node health <hostname>
```

Displays CPU utilization, memory percentage, temperature, and GPU metrics.

### node watch

Watch a node's status in real-time.

```bash
kohakuriver node watch <hostname>
```

Continuously polls and displays updated health metrics.

### node summary

Show aggregated cluster statistics.

```bash
kohakuriver node summary
```

Displays totals across all nodes: cores, memory, GPUs, running tasks.

## Overlay Network Commands

### node overlay

Show overlay network status for a node.

```bash
kohakuriver node overlay <hostname>
```

Displays the node's overlay subnet, VXLAN ID, and connected containers.

### node overlay-release

Release a node's overlay subnet allocation.

```bash
kohakuriver node overlay-release <hostname>
```

Frees the /16 subnet assigned to the node. Only use this when a node is permanently removed.

### node overlay-cleanup

Clean up stale overlay network entries.

```bash
kohakuriver node overlay-cleanup
```

Removes overlay entries for nodes that are no longer registered.

## IP Reservation Commands

IP reservation allows you to obtain a container IP address before launching a task, which is essential for distributed training scenarios.

### node ip-reserve

Reserve an IP address on a node.

```bash
kohakuriver node ip-reserve <hostname> [--ttl 300]
```

Returns:

- Reserved IP address
- Reservation token (used when submitting the task)
- TTL (time-to-live in seconds)

### node ip-release

Release a reserved IP address.

```bash
kohakuriver node ip-release <hostname> --token <token>
```

### node ip-list

List all IP reservations on a node.

```bash
kohakuriver node ip-list <hostname>
```

### node ip-info

Show details about a specific IP reservation.

```bash
kohakuriver node ip-info <hostname> --token <token>
```

### node ip-available

Show available IP addresses on a node.

```bash
kohakuriver node ip-available <hostname>
```

## Distributed Training Example

```bash
# 1. Reserve IP on master node
kohakuriver node ip-reserve master-node --ttl 300
# Output: IP=10.128.0.5, Token=abc123

# 2. Launch master with reserved IP
kohakuriver task submit -t master-node --ip-token abc123 -- \
    python train.py --role master --ip 10.128.0.5

# 3. Launch workers
kohakuriver task submit -t worker-node -- \
    python train.py --role worker --master-ip 10.128.0.5
```

## Related Topics

- [Overlay Network](../setup/overlay-network.md) -- Network setup
- [Monitoring](../tasks/monitoring.md) -- Task monitoring
- [Scheduling](../tasks/scheduling.md) -- Task scheduling and IP reservation
