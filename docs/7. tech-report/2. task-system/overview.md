# Task System Overview

This document describes KohakuRiver's task system: the types of tasks, their
lifecycle states, the data model, execution flows, scheduling algorithm,
approval workflow, and error handling.

---

## Task Types

KohakuRiver supports two task types, both executed inside Docker containers
on runner nodes.

| Property | COMMAND | VPS |
|----------|---------|-----|
| **Purpose** | One-shot execution | Long-running interactive session |
| **Output** | stdout/stderr captured to files | SSH terminal access |
| **Lifecycle** | Runs to completion, container removed | Persists until user stops it |
| **Host endpoint** | `POST /api/submit` | `POST /api/vps/submit` |
| **Runner endpoint** | `POST /api/execute` | `POST /api/vps/create` |
| **Container naming** | `kohakuriver-task-{task_id}` | `kohakuriver-vps-{task_id}` |
| **Docker flag** | `--rm` (auto-remove) | Persistent (no `--rm`) |
| **Backend** | Docker only | Docker or QEMU (`vps_backend` field) |

---

## State Machine

### All States

| State | Value | Description |
|-------|-------|-------------|
| PENDING_APPROVAL | `pending_approval` | User-tier task awaiting operator/admin approval |
| REJECTED | `rejected` | Task rejected by operator/admin |
| PENDING | `pending` | Approved and queued, waiting for node assignment |
| ASSIGNING | `assigning` | Being dispatched to a runner node |
| RUNNING | `running` | Actively executing inside a Docker container |
| PAUSED | `paused` | Container paused via `docker pause` |
| COMPLETED | `completed` | Finished successfully (exit code 0) |
| FAILED | `failed` | Finished with non-zero exit code |
| KILLED | `killed` | Terminated by user request |
| KILLED_OOM | `killed_oom` | Killed by kernel OOM (exit code 137) |
| STOPPED | `stopped` | Gracefully stopped (VPS) |
| LOST | `lost` | Runner connection lost, task status unknown |

### State Transition Diagram

```
                              ┌──────────────────┐
                              │ PENDING_APPROVAL  │
                              └────────┬─────────┘
                                       │
                          ┌────────────┼────────────┐
                          │ approved   │             │ rejected
                          ▼            │             ▼
                     ┌─────────┐       │       ┌──────────┐
                     │ PENDING │       │       │ REJECTED │
                     └────┬────┘       │       └──────────┘
                          │            │
                          ▼            │
                    ┌───────────┐      │
                    │ ASSIGNING │      │
                    └─────┬─────┘      │
                          │            │
                          ▼            │
                     ┌─────────┐       │
            ┌───────►│ RUNNING │◄──────┘ (VPS recovery from LOST)
            │        └────┬────┘
            │             │
            │    ┌────────┼──────────┬──────────┬──────────┐
            │    │        │          │          │          │
            │    ▼        ▼          ▼          ▼          ▼
         ┌──────┐  ┌──────────┐ ┌────────┐ ┌──────┐ ┌──────────┐
         │PAUSED│  │COMPLETED │ │ FAILED │ │KILLED│ │KILLED_OOM│
         └──────┘  └──────────┘ └────────┘ └──────┘ └──────────┘
     (resume ▲)                                │
                                               ▼
                                          ┌─────────┐
                                          │ STOPPED │
                                          └─────────┘

         Any state ─────────────────────► ┌──────┐
              (runner connection lost)     │ LOST │
                                          └──┬───┘
                                             │
                                             ▼
                                    (VPS only: may recover
                                     back to RUNNING if
                                     runner restarts and
                                     container is still up)
```

### Transition Rules

| From | To | Trigger |
|------|----|---------|
| PENDING_APPROVAL | PENDING | Operator/admin approves |
| PENDING_APPROVAL | REJECTED | Operator/admin rejects |
| PENDING | ASSIGNING | Scheduler selects a target node |
| ASSIGNING | RUNNING | Runner acknowledges and starts execution |
| RUNNING | COMPLETED | Process exits with code 0 |
| RUNNING | FAILED | Process exits with non-zero code (not 137) |
| RUNNING | KILLED | User sends kill request |
| RUNNING | KILLED_OOM | Process exits with code 137 (SIGKILL / OOM) |
| RUNNING | STOPPED | Graceful stop (VPS) |
| RUNNING | PAUSED | User sends pause request (`docker pause`) |
| PAUSED | RUNNING | User sends resume request (`docker unpause`) |
| Any | LOST | Host detects runner heartbeat timeout |
| LOST | RUNNING | VPS recovery: runner restarts, finds container alive |

---

## Task Data Model

The `Task` model is defined in `src/kohakuriver/db/task.py` using Peewee ORM
with an SQLite backend. Fields are grouped by function.

### Identification

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task_id` | BigInteger (PK) | Snowflake ID | Unique task identifier |
| `task_type` | CharField | `"command"` | `"command"` or `"vps"` |
| `batch_id` | BigInteger | null | Links tasks submitted together |
| `name` | CharField | null | Optional user-friendly name |

### Ownership and Approval

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `owner_id` | Integer | null | References `User.id` |
| `approval_status` | CharField | null | `null` (auto), `"pending"`, `"approved"`, `"rejected"` |
| `approved_by_id` | Integer | null | References approver `User.id` |
| `approved_at` | DateTime | null | Approval timestamp |
| `rejection_reason` | Text | null | Reason for rejection |

### Command Specification

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `command` | Text | required | Command to execute (or SSH pubkey for VPS) |
| `arguments` | Text (JSON) | `"[]"` | JSON array of command arguments |
| `env_vars` | Text (JSON) | `"{}"` | JSON object of environment variables |

### Resource Requirements

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `required_cores` | Integer | 1 | CPU core count |
| `required_gpus` | Text (JSON) | `"[]"` | JSON array of GPU indices |
| `required_memory_bytes` | BigInteger | null | Memory limit in bytes |
| `target_numa_node_id` | Integer | null | Pin to specific NUMA node |

### Docker Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `container_name` | CharField | null | KohakuRiver environment name |
| `registry_image` | CharField | null | Docker registry image (e.g. `ubuntu:22.04`) |
| `docker_image_name` | CharField | null | Resolved full image tag |
| `docker_privileged` | Boolean | false | Run with `--privileged` |
| `docker_mount_dirs` | Text (JSON) | null | Additional bind mounts |

### VPS-Specific

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ssh_port` | Integer | null | SSH port assigned on runner |
| `vps_backend` | CharField | `"docker"` | `"docker"` or `"qemu"` |
| `vm_image` | CharField | null | Base VM image (QEMU only) |
| `vm_disk_size` | CharField | null | Disk size string, e.g. `"50G"` (QEMU only) |
| `vm_ip` | CharField | null | VM IP address (QEMU only) |

### Assignment and Status

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | CharField | `"pending"` | Current lifecycle state |
| `assigned_node` | CharField | null | Hostname of assigned runner |
| `assignment_suspicion_count` | Integer | 0 | Retry counter for unresponsive assignments |

### Results and Output

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `exit_code` | Integer | null | Process exit code |
| `error_message` | Text | null | Error description |
| `stdout_path` | Text | `""` | Path to stdout log file |
| `stderr_path` | Text | `""` | Path to stderr log file |

### Timestamps

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `submitted_at` | DateTime | `now()` | When the task was submitted |
| `started_at` | DateTime | null | When execution began |
| `completed_at` | DateTime | null | When execution finished |

---

## COMMAND Task Execution Flow

### Sequence Overview

```
  Client              Host                    Runner                Docker
    │                  │                        │                     │
    │  POST /api/submit│                        │                     │
    │ ────────────────►│                        │                     │
    │                  │                        │                     │
    │                  │ 1. Validate + create   │                     │
    │                  │    Task record         │                     │
    │                  │ 2. Select target node  │                     │
    │                  │ 3. Reserve overlay IP  │                     │
    │                  │                        │                     │
    │                  │  POST /api/execute     │                     │
    │                  │ ──────────────────────►│                     │
    │                  │                        │                     │
    │                  │                        │ 4. Sync Docker image│
    │                  │                        │ 5. Build docker run │
    │                  │                        │    command          │
    │                  │                        │                     │
    │                  │                        │  docker run --rm    │
    │                  │                        │ ───────────────────►│
    │                  │                        │                     │
    │                  │  POST /api/update      │                     │
    │                  │  status="running"      │                     │
    │                  │ ◄──────────────────────│                     │
    │                  │                        │                     │
    │                  │                        │     (executing...)  │
    │                  │                        │ ◄───────────────────│
    │                  │                        │    exit code        │
    │                  │                        │                     │
    │                  │  POST /api/update      │                     │
    │                  │  status="completed"    │                     │
    │                  │  exit_code=0           │                     │
    │                  │ ◄──────────────────────│                     │
    │                  │                        │                     │
```

### Detailed Steps

1. **Client submits task** via `POST /api/submit` to the Host REST API. The
   request includes command, arguments, resource requirements, container name,
   and optionally a target node specification.

2. **Host creates Task record** in SQLite with a Snowflake ID. If the user
   has `USER` role, the task enters `PENDING_APPROVAL`; for `OPERATOR`/`ADMIN`,
   it goes directly to `PENDING`.

3. **Host scheduler selects a target node.** If the user specified a target
   (format: `node[:numa][::gpus]`), that node is used. Otherwise, the
   scheduler picks the node with the most available resources matching the
   task constraints. The task transitions to `ASSIGNING`.

4. **Host sends task to runner** via `POST /api/execute` on the runner's
   HTTP API (port 8001). The payload includes task ID, command, arguments,
   resource requirements, container name, and reserved overlay IP.

5. **Runner syncs Docker image.** If the container uses a registry image,
   `docker pull` is executed. Otherwise, the runner checks shared storage
   for a tarball and loads it if the local image is outdated. A lock
   (`docker_sync_lock`) prevents concurrent sync operations.

6. **Runner builds `docker run` command** with:
   - `--rm` flag (auto-remove on exit)
   - `--name kohakuriver-task-{task_id}`
   - Network attachment (overlay or bridge)
   - `--ip` for reserved overlay address
   - `--cpus`, `--memory`, `--gpus` resource constraints
   - Bind mounts for shared storage, logs, and local temp
   - Environment variables (user-defined + system)
   - NUMA prefix via `numactl` if a NUMA node is specified
   - stdout/stderr redirection to log files
   - Tunnel client integration if enabled

7. **Runner starts subprocess** and reports `status="running"` to the Host
   via `POST /api/update`.

8. **Runner waits for process completion.** On exit, the runner interprets
   the exit code and reports the final status to the Host.

---

## VPS Task Creation Flow

VPS tasks follow a different path from COMMAND tasks. The container persists
until explicitly stopped by the user.

```
  Client              Host                    Runner                Docker
    │                  │                        │                     │
    │ POST /api/vps/   │                        │                     │
    │      submit      │                        │                     │
    │ ────────────────►│                        │                     │
    │                  │                        │                     │
    │                  │ 1. Create Task record  │                     │
    │                  │    (type="vps")        │                     │
    │                  │ 2. Select target node  │                     │
    │                  │ 3. Reserve overlay IP  │                     │
    │                  │                        │                     │
    │                  │ POST /api/vps/create   │                     │
    │                  │ ──────────────────────►│                     │
    │                  │                        │                     │
    │                  │                        │ 4. Create container │
    │                  │                        │    with SSH daemon  │
    │                  │                        │ 5. Inject SSH key   │
    │                  │                        │ 6. Allocate SSH port│
    │                  │                        │                     │
    │                  │  POST /api/update      │                     │
    │                  │  status="running"      │                     │
    │                  │  ssh_port=NNNNN        │                     │
    │                  │ ◄──────────────────────│                     │
    │                  │                        │                     │
    │  SSH via Host    │                        │                     │
    │  proxy (8002)    │                        │                     │
    │ ────────────────►│ ──────────────────────►│ ──────────────────►│
    │                  │                        │                     │
```

Key differences from COMMAND tasks:

- **Payload** includes `ssh_public_key` and `ssh_port` instead of `command`
  and `arguments`.
- **Runner endpoint** is `/api/vps/create` rather than `/api/execute`.
- **Container is persistent** -- no `--rm` flag. It runs until the user
  issues a stop/kill command.
- **SSH port** is allocated by the runner and reported back to the Host in
  the status update. The Host stores it in `task.ssh_port`.
- **SSH access** is proxied through the Host's SSH proxy service on port 8002,
  or directly via the runner if the user has network access.
- **VPS backend** can be `"docker"` (default) or `"qemu"` for full VM
  virtualization with separate disk images.
- **Timeout** for the Host-to-Runner HTTP call is 60 seconds (vs 30 for
  COMMAND), since VPS container creation may take longer.

---

## Scheduling Algorithm

### Target Specification

Users can optionally specify a target node using the format:

```
node[:numa_node_id][::gpu_count]
```

Examples:
- `worker-01` -- run on worker-01, any NUMA node, no GPU
- `worker-01:0` -- run on worker-01, NUMA node 0
- `worker-01::2` -- run on worker-01, any NUMA, 2 GPUs
- `worker-01:0::4` -- run on worker-01, NUMA 0, 4 GPUs

When no target is specified, the scheduler selects automatically.

### Automatic Node Selection

1. **Filter online nodes** -- only nodes with recent heartbeats are candidates.
2. **Filter by resources** -- exclude nodes that cannot satisfy the task's
   `required_cores`, `required_memory_bytes`, or GPU count.
3. **GPU matching** -- the requested GPU count is matched against available
   (unallocated) GPUs on each candidate node. Specific GPU indices are
   assigned from the available pool.
4. **NUMA awareness** -- if `target_numa_node_id` is set, only nodes with
   that NUMA node topology are considered. Tasks are pinned using `numactl
   --cpunodebind=N --membind=N`.
5. **Select best fit** -- the node with the most free resources matching
   all constraints is chosen.

### GPU Allocation

GPUs are tracked as a list of device indices per node. When a task requests
GPUs:

- The scheduler inspects the node's reported GPU list.
- Already-allocated GPU indices (from running tasks) are excluded.
- The requested number of GPUs is taken from the remaining pool.
- The allocated indices are stored in `task.required_gpus` as a JSON array.
- At execution time, Docker receives `--gpus "device=0,1"` (or whichever
  indices were assigned).

### NUMA Pinning

When `target_numa_node_id` is set on a task:

- The runner's NUMA detector (`runner/numa/detector.py`) generates the
  appropriate `numactl` prefix.
- The inner command is wrapped: `numactl --cpunodebind=N --membind=N <cmd>`.
- The environment variable `KOHAKURIVER_TARGET_NUMA_NODE` is set inside the
  container for application-level awareness.

---

## Approval Workflow

Task submission respects the user's role tier:

```
                    ┌──────────────────────────┐
                    │   Client submits task     │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │   Check user role         │
                    └────────────┬─────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 │               │               │
            ADMIN/OPERATOR      USER         (no auth)
                 │               │               │
                 ▼               ▼               ▼
          auto-approved    PENDING_APPROVAL  auto-approved
          (status=PENDING) (needs review)   (status=PENDING)
                                │
                   ┌────────────┼────────────┐
                   │                         │
              approved                   rejected
                   │                         │
                   ▼                         ▼
              PENDING                    REJECTED
         (enters scheduler)         (terminal state)
```

- **ADMIN / OPERATOR**: Tasks are auto-approved. The `approval_status` field
  is left `null` and the task enters `PENDING` immediately.
- **USER**: Tasks enter `PENDING_APPROVAL`. An operator or admin must review
  and approve (setting `approval_status="approved"`, `approved_by_id`,
  `approved_at`) before the task moves to `PENDING`.
- **No auth mode**: When authentication is disabled, all tasks are
  auto-approved.
- **Rejection**: The reviewer sets `approval_status="rejected"` with an
  optional `rejection_reason`. The task enters `REJECTED` (terminal state).

---

## Error Handling and Recovery

### Exit Code Interpretation

The runner interprets the Docker container's exit code to determine the final
task status:

| Exit Code | Signal | Status | Description |
|-----------|--------|--------|-------------|
| 0 | -- | `completed` | Successful execution |
| 137 | SIGKILL (9) | `killed_oom` | Container killed, likely OOM |
| 143 | SIGTERM (15) | `failed` | Container terminated |
| Other | -- | `failed` | Non-zero exit with error message |

For non-zero exits (other than 137), the runner appends the Docker stderr
output (up to 500 characters) to the `error_message` field.

### Assignment Suspicion and Retry

If a runner does not acknowledge a task assignment (no status callback within
the expected window), the Host increments the task's
`assignment_suspicion_count`:

1. Host sends task to runner via HTTP POST.
2. If the runner does not respond or does not send a `status="running"`
   update, the suspicion count increments on each health check cycle.
3. When the count exceeds the configured threshold, the Host reassigns
   the task to a different node.
4. The suspicion count resets to 0 on any successful status update from
   the runner.

This mechanism handles transient runner failures, network partitions, and
cases where a runner accepts a task but crashes before starting execution.

### LOST State

When the Host detects that a runner has stopped sending heartbeats (the node
transitions to `OFFLINE`), all tasks assigned to that runner are marked as
`LOST`:

- **COMMAND tasks**: `LOST` is a terminal state. The task must be manually
  resubmitted by the user.
- **VPS tasks**: `LOST` may be recoverable. If the runner restarts and
  discovers the VPS container is still running, it reports `status="running"`
  back to the Host. The Host validates this transition (LOST -> RUNNING is
  allowed only for VPS tasks) and clears the `completed_at` timestamp,
  effectively reviving the task.

### External Kill Detection

When a task is killed via the Host API:

1. The Host calls `send_kill_to_runner()` which POSTs to `/api/kill` on
   the runner.
2. The runner removes the task from its local `TaskStateStore` **before**
   issuing `docker kill`.
3. When the subprocess completes (due to the kill), `execute_task()` checks
   the store. Since the task was removed, it knows the kill was external
   and **skips** the final status report to avoid overwriting the `killed`
   status.

### Pause and Resume

Pause and resume operations use Docker's native container freeze mechanism:

- **Pause**: `docker pause {container_name}` -- freezes all processes in the
  container via cgroups. The task transitions to `PAUSED`.
- **Resume**: `docker unpause {container_name}` -- thaws all processes. The
  task transitions back to `RUNNING`.

These operations preserve the container's memory state entirely. No data is
lost during pause/resume cycles.

---

## Docker Container Configuration

Each COMMAND task container is created with the following standard
configuration:

### Bind Mounts

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `{SHARED_DIR}/shared_data` | `/shared` | Shared data across cluster |
| `{SHARED_DIR}/logs` | `/kohakuriver-logs` | Task stdout/stderr output |
| `{LOCAL_TEMP_DIR}` | `/local_temp` | Node-local temporary storage |
| Additional mounts from config | Configurable | User-defined mounts |
| Tunnel client binary | Configurable | Port forwarding support |

### Environment Variables (System-Injected)

| Variable | Value | Description |
|----------|-------|-------------|
| `KOHAKURIVER_TASK_ID` | `{task_id}` | Task identifier |
| `KOHAKURIVER_LOCAL_TEMP_DIR` | Config value | Local temp path |
| `KOHAKURIVER_SHARED_DIR` | Config value | Shared storage path |
| `KOHAKURIVER_TARGET_NUMA_NODE` | `{numa_id}` | NUMA node (if pinned) |
| Tunnel vars | Auto-generated | Tunnel client connection info |

### Output Capture

stdout and stderr are redirected to files on the shared filesystem:

```
{SHARED_DIR}/logs/{task_id}/stdout.log
{SHARED_DIR}/logs/{task_id}/stderr.log
```

Inside the container, these paths are translated to `/kohakuriver-logs/...`
via the bind mount. The inner command uses shell redirection:

```sh
exec {numa_prefix} {command} {arguments} > /kohakuriver-logs/.../stdout.log 2> /kohakuriver-logs/.../stderr.log
```

The `exec` replaces the shell process with the task command, ensuring proper
signal handling (SIGTERM/SIGKILL reach the actual process, not the wrapper
shell).
