---
title: Command Tasks
description: Submitting and managing one-shot command tasks in KohakuRiver.
icon: i-carbon-terminal
---

# Command Tasks

Command tasks execute a one-shot command inside a Docker container, capture output, and report completion.

## Submitting Tasks

### Basic Submission

```bash
kohakuriver task submit -t mynode -- echo "Hello World"
```

The `--` separator is required to distinguish CLI options from the command to execute.

### With Resource Constraints

```bash
kohakuriver task submit \
    -t mynode \
    -c 4 \
    -m 8G \
    -- python /shared/train.py --batch-size 32
```

| Flag           | Description                                                   |
| -------------- | ------------------------------------------------------------- |
| `-t, --target` | Target node (format: `hostname[:numa][::gpus]`)               |
| `-c, --cores`  | Number of CPU cores (0 = no limit; defaults to 1)             |
| `-m, --memory` | Memory limit (e.g., `4G`, `512M`)                             |
| `--container`  | Container environment name                                    |
| `--image`      | Docker registry image (mutually exclusive with `--container`) |
| `--privileged` | Run with `--privileged` flag                                  |
| `--mount`      | Additional mounts (repeatable)                                |
| `-w, --wait`   | Wait for task completion                                      |

### Container Options

```bash
# Use a custom environment
kohakuriver task submit -t mynode --container my-pytorch -- python train.py

# Use a registry image directly
kohakuriver task submit -t mynode --image ubuntu:22.04 -- apt list

# Additional mounts
kohakuriver task submit -t mynode --mount /data:/data -- ls /data
```

### GPU Targeting

```bash
# Allocate specific GPUs
kohakuriver task submit -t mynode::0,1 -- python multi_gpu_train.py

# GPU with NUMA node
kohakuriver task submit -t mynode:0::0,1 -- python train.py
```

## Viewing Output

### Stdout

```bash
kohakuriver task logs <task_id>
```

### Stderr

```bash
kohakuriver task logs <task_id> --stderr
```

### Follow Mode

```bash
kohakuriver task logs <task_id> -f
```

Streams new output as it is written, similar to `tail -f`.

## Task Control

```bash
# Kill a running task
kohakuriver task kill <task_id>

# Pause execution
kohakuriver task pause <task_id>

# Resume paused task
kohakuriver task resume <task_id>
```

## Monitoring

```bash
# Detailed task status
kohakuriver task status <task_id>

# Live status updates
kohakuriver task watch <task_id>
```

## How It Works

1. CLI sends `POST /api/submit` to the host with task details
2. Host validates resources, finds suitable node (or uses specified target)
3. Host creates a Task record in the database with status `assigning`
4. Host sends `POST /api/tasks/execute` to the runner with execution details
5. Runner creates a Docker container with:
   - The specified image/environment
   - CPU cores and memory limits
   - GPU allocation via `--gpus` flag (NVIDIA Container Toolkit)
   - Shared storage mounted at `/shared` (when shared storage is configured)
   - Working directory set to `/shared` (or `/` if shared storage is not configured)
6. Runner executes the command, streaming stdout/stderr to log files
7. Runner reports task status via heartbeats
8. On completion, runner reports exit code back to host
