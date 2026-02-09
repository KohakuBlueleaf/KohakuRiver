---
title: Database Models
description: Peewee ORM models, JSON field pattern, migrations, and auth models
icon: i-carbon-data-base
---

# Database Models

KohakuRiver uses Peewee ORM with SQLite for persistent storage on the host. The database layer is in `src/kohakuriver/db/`.

## Module Layout

```
db/
├── base.py       Global db instance, BaseModel, initialize_database(), run_in_executor()
├── task.py       Task model (command tasks and VPS sessions)
├── node.py       Node model (compute nodes)
├── auth.py       User, Session, Token, Invitation, Group, UserGroup, VpsAssignment
└── models.py     Re-export shim for convenience imports
```

## Database Initialization

```python
from kohakuriver.db.base import db, initialize_database

# db is a global SqliteDatabase(None) -- path set at init time
initialize_database("/var/lib/kohakuriver/kohakuriver.db")
```

`initialize_database()` performs these steps:

1. Calls `db.init(path)` to bind the global `SqliteDatabase` to a file.
2. Opens the connection with `db.connect()`.
3. Creates all tables with `safe=True` (no-op if they exist).
4. Runs column-level migrations for new fields (both Task and Node tables).
5. Logs initial stats (task count, node count).

## The JSON Field Pattern

Since SQLite does not support structured columns, complex data is stored as JSON in `TextField` columns. Each JSON field gets a `get_X()` / `set_X()` accessor pair:

```python
class Task(BaseModel):
    # Stored as JSON string: '["--batch-size", "32"]'
    arguments = peewee.TextField(default="[]")

    def get_arguments(self) -> list[str]:
        """Parse arguments JSON to list."""
        if not self.arguments:
            return []
        try:
            return json.loads(self.arguments)
        except json.JSONDecodeError:
            return []

    def set_arguments(self, args: list[str] | None) -> None:
        """Store arguments list as JSON."""
        self.arguments = json.dumps(args or [])
```

JSON fields in the codebase:

| Model | Field               | Python Type            | Default | Storage Example              |
| ----- | ------------------- | ---------------------- | ------- | ---------------------------- |
| Task  | `arguments`         | `list[str]`            | `[]`    | `'["--lr", "0.01"]'`         |
| Task  | `env_vars`          | `dict[str, str]`       | `{}`    | `'{"CUDA": "0"}'`            |
| Task  | `required_gpus`     | `list[int]`            | `[]`    | `'[0, 1]'`                   |
| Task  | `docker_mount_dirs` | `list[str]`            | `[]`    | `'["/data"]'`                |
| Node  | `numa_topology`     | `dict[int, list[int]]` | `null`  | `'{"0": [0,1,2,3]}'`         |
| Node  | `gpu_info`          | `list[dict]`           | `null`  | `'[{"id":0,"name":"A100"}]'` |
| Node  | `vfio_gpus`         | `list[dict]`           | `null`  | `'[{"pci":"0000:01:00.0"}]'` |
| Group | `limits_json`       | `dict`                 | `{}`    | `'{"max_gpus": 4}'`          |

## Task Model

The Task model (`db/task.py`) represents both command tasks and VPS sessions. Key fields organized by category:

```
Category        Fields
──────────────  ──────────────────────────────────────────────────────
Identity        task_id (snowflake PK), task_type, batch_id, name
Ownership       owner_id, approval_status, approved_by_id, approved_at,
                rejection_reason
Specification   command, arguments (JSON), env_vars (JSON),
                required_cores, required_gpus (JSON),
                required_memory_bytes, target_numa_node_id
Docker          container_name, registry_image, docker_image_name,
                docker_privileged, docker_mount_dirs (JSON)
VPS             ssh_port, vps_backend ("docker"/"qemu"),
                vm_image, vm_disk_size, vm_ip
Status          status, assigned_node, assignment_suspicion_count
Results         exit_code, error_message, stdout_path, stderr_path
Timestamps      submitted_at, started_at, completed_at
```

Status helper methods: `is_pending()`, `is_running()`, `is_finished()`, `is_vps()`.

Status transition methods: `mark_running()`, `mark_completed()`, `mark_failed()`, `mark_killed()`, `mark_lost()`, `mark_paused()`.

## Node Model

The Node model (`db/node.py`) stores compute node state:

```
Category        Fields
──────────────  ──────────────────────────────────────────────────────
Identity        hostname (PK), url
Hardware        total_cores, memory_total_bytes
Health          status, last_heartbeat, cpu_percent, memory_percent,
                memory_used_bytes, current_avg_temp
Topology        numa_topology (JSON), gpu_info (JSON)
VM              vm_capable, vfio_gpus (JSON)
Version         runner_version
```

## Auth Models

The auth subsystem (`db/auth.py`) provides seven models:

```
Model            Purpose
───────────────  ────────────────────────────────────────────
User             Username, bcrypt password hash, role, active status
Session          Cookie-based session with expiry
Token            API tokens stored as SHA3-512 hashes
Invitation       Invitation-only registration tokens with usage limits
Group            User groups with JSON resource quotas (limits_json)
UserGroup        Many-to-many user <-> group membership
VpsAssignment    Many-to-many VPS access grants (user <-> task)
```

The **UserRole** class defines a hierarchy with `is_at_least()` for permission checks:

```
anony < viewer < user < operator < admin
```

- `anony`: Can view public status
- `viewer`: Can view tasks, nodes, VPS
- `user`: Can submit tasks (with approval), create VPS
- `operator`: Can approve tasks, manage Docker, admin operations
- `admin`: Full access, user management, invitations

## Migrations

Migrations are handled in `db/base.py` using Peewee's `playhouse.migrate`:

```python
def _run_migrations(Task) -> None:
    cursor = db.execute_sql("PRAGMA table_info(tasks)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    migrations = []
    if "vps_backend" not in existing_columns:
        migrations.append(
            migrator.add_column("tasks", "vps_backend",
                                peewee.CharField(default="docker"))
        )
    if migrations:
        migrate(*migrations)
```

New columns are added by checking `PRAGMA table_info` and conditionally appending `add_column` operations. This runs on every startup, making schema evolution automatic. Both `_run_migrations()` (for the tasks table) and `_run_node_migrations()` (for the nodes table) follow this pattern.

Currently migrated columns include: `registry_image`, `owner_id`, `name`, `approval_status`, `approved_by_id`, `approved_at`, `rejection_reason`, `vps_backend`, `vm_image`, `vm_disk_size`, `vm_ip` (tasks table) and `vm_capable`, `vfio_gpus`, `runner_version` (nodes table).

## Async Access

For use in FastAPI async handlers:

```python
from kohakuriver.db.base import run_in_executor

task = await run_in_executor(Task.get_or_none, Task.task_id == task_id)
```

This runs the blocking Peewee call in a thread pool executor via `asyncio.get_event_loop().run_in_executor(None, ...)`.
