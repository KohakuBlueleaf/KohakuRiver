---
title: kohakuriver task
description: Task management commands for submitting and monitoring tasks.
icon: i-carbon-task
---

# kohakuriver task

The `kohakuriver task` command group manages command tasks -- submitting, monitoring, and controlling them.

## Commands

### task submit

Submit a command task for execution.

```bash
kohakuriver task submit [options] -- <command> [args...]
```

The `--` separator is required to distinguish CLI options from the command to execute.

| Flag           | Short | Default       | Description                             |
| -------------- | ----- | ------------- | --------------------------------------- |
| `--target`     | `-t`  | Auto-schedule | Target node (`hostname[:numa][::gpus]`) |
| `--cores`      | `-c`  | `1`           | Number of CPU cores                     |
| `--memory`     | `-m`  | None          | Memory limit (e.g., `4G`, `512M`)       |
| `--container`  |       | None          | Container environment name              |
| `--image`      |       | None          | Docker registry image                   |
| `--privileged` |       | `False`       | Run with Docker `--privileged`          |
| `--mount`      |       | None          | Additional mount (repeatable)           |
| `--wait`       | `-w`  | `False`       | Wait for task completion                |

Examples:

```bash
# Basic task
kohakuriver task submit -t node1 -- echo "Hello World"

# GPU task with resources
kohakuriver task submit -t node1::0,1 -c 8 -m 32G -- python train.py

# With custom environment
kohakuriver task submit -t node1 --container my-pytorch -- python train.py

# Wait for completion
kohakuriver task submit -t node1 -w -- python benchmark.py
```

### task list

List tasks with optional filters.

```bash
kohakuriver task list [options]
```

| Flag        | Short | Default | Description                              |
| ----------- | ----- | ------- | ---------------------------------------- |
| `--status`  | `-s`  | All     | Filter by status (running, failed, etc.) |
| `--node`    | `-n`  | All     | Filter by assigned node                  |
| `--limit`   | `-l`  | `50`    | Maximum results                          |
| `--compact` | `-c`  | `False` | Compact table format                     |

Examples:

```bash
kohakuriver task list
kohakuriver task list -s running
kohakuriver task list -n node1 -l 100
kohakuriver task list -c
```

### task status

Show detailed information about a specific task.

```bash
kohakuriver task status <task_id>
```

Displays:

- Task type, status, and exit code
- Assigned node and target specification
- Resource allocation (cores, memory, GPUs)
- Container configuration
- Timestamps (submitted, started, completed)
- Error message (if failed)

### task logs

View task output.

```bash
kohakuriver task logs <task_id> [options]
```

| Flag       | Short | Default | Description                   |
| ---------- | ----- | ------- | ----------------------------- |
| `--stderr` |       | `False` | Show stderr instead of stdout |
| `--follow` | `-f`  | `False` | Stream output in real-time    |

Examples:

```bash
kohakuriver task logs 1234567890
kohakuriver task logs 1234567890 --stderr
kohakuriver task logs 1234567890 -f
```

### task kill

Terminate a running task.

```bash
kohakuriver task kill <task_id>
```

Sends a kill request to the runner, which stops the Docker container.

### task pause

Pause a running task.

```bash
kohakuriver task pause <task_id>
```

Freezes all processes in the container using Docker pause.

### task resume

Resume a paused task.

```bash
kohakuriver task resume <task_id>
```

Unfreezes processes in the container.

### task watch

Watch a task's status in real-time.

```bash
kohakuriver task watch <task_id>
```

Polls the task status at regular intervals and displays updates.

## Related Topics

- [Command Tasks](../tasks/command-tasks.md) -- Detailed command task documentation
- [Scheduling](../tasks/scheduling.md) -- How tasks are scheduled
- [Monitoring](../tasks/monitoring.md) -- Monitoring task status
- [VPS](vps.md) -- VPS management commands
