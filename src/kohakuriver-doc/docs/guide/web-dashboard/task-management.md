---
title: Task Management
description: Managing tasks through the KohakuRiver web dashboard.
icon: i-carbon-task-settings
---

# Task Management

The web dashboard provides a graphical interface for submitting, monitoring, and managing tasks.

## Task List View

The task list displays all tasks with:

- Task ID and optional name
- Task type (COMMAND or VPS)
- Current status with color-coded badges
- Assigned node
- Resource allocation (cores, memory, GPUs)
- Submission and completion timestamps
- Exit code (for completed tasks)

### Filtering

Filter tasks by:

- **Status**: Running, completed, failed, killed, etc.
- **Type**: Command or VPS
- **Node**: Filter by assigned node

### Sorting

Tasks are sorted by submission time (newest first) by default. Click column headers to sort by other fields.

## Submitting Tasks

The dashboard supports task submission through a form:

1. Click the "Submit Task" button
2. Fill in the form:
   - **Command**: The command to execute
   - **Target node**: Select from available nodes
   - **CPU cores**: Number of cores to allocate
   - **Memory**: Memory limit
   - **GPU IDs**: Comma-separated GPU indices
   - **Container**: Environment name or registry image
3. Click "Submit"

The task appears in the list with `assigning` status.

## Task Details

Click a task row to view details:

- **Configuration**: Full command, container image, resource constraints
- **Timing**: Submitted, started, and completed timestamps
- **Output**: Stdout and stderr logs with syntax highlighting
- **Error**: Error message if the task failed

## Task Actions

Available actions depend on the task's current status:

| Status             | Available Actions                     |
| ------------------ | ------------------------------------- |
| `running`          | Kill, Pause                           |
| `paused`           | Resume, Kill                          |
| `pending_approval` | Approve, Reject (operator/admin only) |
| `assigning`        | Kill                                  |

### Kill a Task

Click the "Kill" button on a running or assigning task. This sends a kill signal to the runner, which stops the container and reports the task as `killed`.

### Pause / Resume

For running tasks, click "Pause" to freeze execution. The task enters `paused` state and all processes are suspended. Click "Resume" to continue execution.

## Log Viewer

The log viewer provides:

- **Stdout tab**: Standard output from the task
- **Stderr tab**: Standard error output
- **Auto-scroll**: Automatically scrolls to the latest output
- **Follow mode**: Streams new output in real-time via WebSocket
- **Download**: Download full log files

Logs are stored at `SHARED_DIR/logs/<task_id>/stdout.log` and `stderr.log`.

## Task Approval

When authentication is enabled, tasks submitted by users with the `user` role require approval. The dashboard shows a notification badge for pending approvals.

Operators and admins can:

1. View pending tasks in the approval queue
2. Review the task's command, resources, and target
3. Approve or reject with one click

Approved tasks proceed to scheduling. Rejected tasks are marked as `rejected`.

## Batch Operations

Tasks submitted to multiple targets share a `batch_id`. The dashboard groups these tasks together, allowing you to:

- View all tasks in a batch
- Kill all tasks in a batch
- Monitor batch progress

## Related Topics

- [VPS Management](vps-management.md) -- Managing VPS instances
- [Node Monitoring](node-monitoring.md) -- Checking node resource availability
- [Command Tasks](../tasks/command-tasks.md) -- CLI-based task submission
