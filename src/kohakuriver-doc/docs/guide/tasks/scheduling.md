---
title: Task Scheduling
description: How KohakuRiver schedules tasks to nodes with resource constraints.
icon: i-carbon-calendar
---

# Task Scheduling

KohakuRiver's task scheduler assigns tasks to runner nodes based on resource availability and user-specified constraints.

## Target Specification

The target format is `hostname[:numa_id][::gpu_ids]`:

| Format                | Example        | Description               |
| --------------------- | -------------- | ------------------------- |
| `hostname`            | `node1`        | Run on specific node      |
| `hostname:numa`       | `node1:0`      | Run on specific NUMA node |
| `hostname::gpus`      | `node1::0,1`   | Run with specific GPUs    |
| `hostname:numa::gpus` | `node1:0::0,1` | NUMA node + specific GPUs |

## Auto-Scheduling

When no target is specified, the scheduler finds a suitable node automatically:

```bash
kohakuriver task submit -- echo "auto-scheduled"
```

The scheduler considers:

- Node must be online
- Node must have enough available CPU cores
- Node must have enough available memory (if specified)

Auto-scheduling does not support GPU tasks -- you must specify a target with GPU IDs.

## Resource Validation

Before dispatching a task, the host validates:

1. **Node exists and is online** -- Checks the node registration database
2. **NUMA topology** -- If a NUMA node is specified, validates it exists on the target
3. **GPU availability** -- Checks that requested GPU indices are valid and not allocated to other tasks
4. **CPU cores** -- Verifies enough cores are available on the node
5. **Memory** -- Verifies enough memory is available

## Multi-Target Submission

Submit to multiple nodes simultaneously:

```bash
# Via the API (targets field supports a list)
# Each target creates a separate task, all sharing a batch_id
```

Multi-target submission is only available for command tasks. VPS tasks must target a single node.

## IP Reservation for Distributed Training

For distributed training scenarios where you need to know IP addresses before launching tasks:

```bash
# 1. Reserve an IP on the master node
kohakuriver node ip-reserve master-node --ttl 300
# Returns: IP=10.128.0.5, Token=abc123

# 2. Launch master with reserved IP
kohakuriver task submit -t master-node --ip-token abc123 -- \
    python train.py --role master --ip 10.128.0.5

# 3. Launch workers pointing to master
kohakuriver task submit -t worker-node -- \
    python train.py --role worker --master-ip 10.128.0.5
```

IP reservation requires the overlay network to be enabled.

## Task Assignment Reconciliation

The host reconciles task states during heartbeat processing:

- **assigning -> running**: When a runner reports a task in its `running_tasks` list, the host confirms the assignment
- **assigning -> failed**: If a task stays in `assigning` state for too long (3x heartbeat interval) without the runner confirming, it is marked as suspected and eventually failed
- **pending -> failed**: Tasks stuck in `pending` on a specific runner for too long (3x heartbeat timeout) are marked as failed
- **killed by runner**: Runners report killed tasks (e.g., OOM) in their heartbeat, and the host updates the task status accordingly
