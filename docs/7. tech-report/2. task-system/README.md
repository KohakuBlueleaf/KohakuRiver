# KohakuRiver Task System

Task lifecycle management for command execution and interactive VPS sessions.

## Documents

| Document | Description |
|----------|-------------|
| [overview.md](overview.md) | Task types, state machine, scheduling, execution flow, and error handling |

## Quick Reference

### Task Types

| Type | Purpose | Endpoint | Lifecycle |
|------|---------|----------|-----------|
| **COMMAND** | One-shot execution with stdout/stderr capture | `/api/execute` | Runs to completion, then exits |
| **VPS** | Long-running interactive session with SSH access | `/api/vps/create` | Persists until explicitly stopped |

### State Flow

```
PENDING_APPROVAL ──► PENDING ──► ASSIGNING ──► RUNNING ──► COMPLETED
       │                                         │  ▲       FAILED
       ▼                                         │  │       KILLED
    REJECTED                                     ▼  │       KILLED_OOM
                                              PAUSED        STOPPED
                                                            LOST
```

### Key Components

| Component | Path | Role |
|-----------|------|------|
| Task Model | `src/kohakuriver/db/task.py` | Peewee ORM model (SQLite) |
| Task Scheduler | `src/kohakuriver/host/services/task_scheduler.py` | Host-side dispatch and status tracking |
| Task Executor | `src/kohakuriver/runner/services/task_executor.py` | Runner-side Docker execution |
| VPS Manager | `src/kohakuriver/runner/services/vps_manager.py` | Runner-side VPS lifecycle |
| Enums | `src/kohakuriver/models/enums.py` | TaskStatus, TaskType definitions |
