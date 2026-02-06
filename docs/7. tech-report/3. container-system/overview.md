# Container System Overview

KohakuRiver uses Docker containers as portable virtual environments. Every workload -- whether a one-shot command task or a long-running VPS session -- runs inside a Docker container on a Runner node. This document covers the container lifecycle from image distribution through execution and teardown.

---

## Containers as Portable Environments

A "container environment" in KohakuRiver is a Docker image that encapsulates a user's complete workspace: OS packages, language runtimes, libraries, and configuration. The `container_name` field in a task submission maps to a local Docker image tagged under the `kohakuriver/` namespace:

```
container_name = "cuda-dev"  -->  Docker image: kohakuriver/cuda-dev:base
```

Environments can originate from two sources:

| Source | Field | Example | Resolution |
|--------|-------|---------|------------|
| Shared storage tarball | `container_name` | `"cuda-dev"` | Load from `{SHARED_DIR}/kohakuriver-containers/cuda-dev-{ts}.tar` |
| Docker registry | `registry_image` | `"ubuntu:22.04"` | Pull directly via `docker pull` |

When `registry_image` is provided, it takes precedence and the Runner pulls directly from the registry. Otherwise, the Runner syncs from shared storage.

---

## Image Sync Mechanism

KohakuRiver distributes container images across cluster nodes using timestamped tarballs stored on shared filesystem (NFS, GPFS, etc.). This avoids the need for a private Docker registry.

### Tarball Naming Convention

```
{container_name_lowercase}-{unix_timestamp}.tar

Examples:
  cuda-dev-1706000000.tar
  pytorch-base-1706100000.tar
```

Tarballs are stored in `{SHARED_DIR}/kohakuriver-containers/`.

### Sync Decision Flow

```
                   ensure_docker_image_synced()
                              │
                    ┌─────────▼──────────┐
                    │ Acquire sync lock   │
                    │ (docker_sync_lock)  │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ Get local image     │    docker.from_env()
                    │ creation timestamp  │──► images.get(tag).attrs["Created"]
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │ List shared tarballs│    Scan directory for
                    │ sorted newest first │──► {name}-{ts}.tar pattern
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐     No tarballs found,
                    │ Compare timestamps  │──── or local >= shared ──► Skip sync
                    └─────────┬──────────┘
                              │ shared > local (or local missing)
                    ┌─────────▼──────────┐
                    │ Load tarball into   │    docker images.load()
                    │ local Docker daemon │──► Tag as kohakuriver/{name}:base
                    └─────────┬──────────┘
                              │
                           Done ✓
```

### Sync Lock

A per-Runner `asyncio.Lock` (`docker_sync_lock`) prevents concurrent image syncs. Without this lock, two tasks requesting the same image simultaneously could trigger redundant multi-gigabyte loads. The lock is held for the entire check-and-load operation:

```python
async with docker_sync_lock:
    needs_sync, sync_path = docker_utils.needs_sync(container_name, tar_dir)
    if needs_sync and sync_path:
        await run_in_executor(docker_utils.sync_from_shared, ...)
```

### Tarball Creation

New tarballs are created via `create_container_tar()`, which:

1. Stops the source container for filesystem consistency
2. Commits the container to a Docker image
3. Saves the image as a tarball with the current timestamp
4. Removes older tarballs for the same container name
5. Prunes dangling Docker images

---

## Docker Execution Model

KohakuRiver runs containers via **subprocess** (`asyncio.create_subprocess_exec`) rather than the Python Docker SDK. The key reasons:

1. **Signal handling**: Using `exec` to replace the shell process with the user command ensures signals (SIGTERM, SIGKILL) reach the actual process, not a shell wrapper. This is critical for OOM detection (exit code 137 = SIGKILL) and graceful termination (exit code 143 = SIGTERM).

2. **stdio capture**: Task stdout/stderr are redirected to files inside the container (`> /kohakuriver-logs/...`), which map to shared storage via bind mounts. This provides persistent output without streaming through the Runner process.

3. **Process lifetime**: The Runner process awaits the subprocess directly. When a container finishes (or is killed), the Runner gets the exit code immediately.

### Command Construction

The final command executed inside the container follows this structure:

```
/bin/sh -c "(nohup tunnel-client ... &) && sleep 0.1 && exec [numactl ...] <command> <args> > <stdout> 2> <stderr>"
```

Breaking this down:

| Part | Purpose |
|------|---------|
| `/bin/sh -c "..."` | Shell wrapper for redirection and backgrounding |
| `nohup tunnel-client ... &` | Start tunnel client as background daemon (if enabled) |
| `sleep 0.1` | Brief pause to let tunnel client initialize |
| `exec` | Replace shell with user command for direct signal delivery |
| `numactl --cpunodebind=N --membind=N` | NUMA pinning (if target_numa_node_id set) |
| `> stdout 2> stderr` | Redirect output to log files on shared storage |

### Exit Code Interpretation

| Exit Code | Status Reported | Meaning |
|-----------|----------------|---------|
| 0 | `completed` | Success |
| 137 (128+9) | `killed_oom` | SIGKILL -- likely OOM killer |
| 143 (128+15) | `failed` | SIGTERM -- graceful termination |
| Other | `failed` | Application error |

---

## Resource Constraints

Resource constraints from the task submission are mapped directly to Docker flags:

### CPU

```bash
docker run --cpus 4 ...    # Limit to 4 CPU cores
```

The `--cpus` flag sets a CFS quota. The container can burst across all physical cores but is throttled to the equivalent of N cores of compute time.

### Memory

```bash
docker run --memory 8192m ...    # 8 GB memory limit
```

The `required_memory_bytes` field is converted to megabytes. When a container exceeds this limit, the Linux OOM killer terminates it (exit code 137).

### GPU

```bash
docker run --gpus "device=0,2" ...    # GPUs 0 and 2
```

GPU IDs from the task's `required_gpus` list are passed via the NVIDIA Container Toolkit. The scheduler on the Host ensures GPU allocations do not conflict across tasks on the same Runner.

### NUMA

NUMA binding is applied inside the container, not at the Docker level:

```bash
numactl --cpunodebind=0 --membind=0 <user_command>
```

This pins the process to a specific NUMA node for memory-locality-sensitive workloads. The NUMA topology is detected at Runner startup and used by the Host scheduler to assign tasks to appropriate nodes.

---

## Network Configuration

Containers connect to one of two Docker networks depending on whether the VXLAN overlay is enabled:

| Mode | Docker Network | Subnet | Cross-Node |
|------|---------------|--------|------------|
| Default | `kohakuriver-net` | 172.30.0.0/16 | No |
| Overlay | `kohakuriver-overlay` | 10.X.0.0/16 | Yes |

In overlay mode, each container can receive a pre-reserved IP address (`--ip 10.1.0.5`) allocated by the Host's IP reservation service. This enables stable, predictable addressing across the cluster.

```bash
docker run --network kohakuriver-overlay --ip 10.1.0.5 ...
```

See the [Networking](../6.%20networking/) section for the full VXLAN overlay architecture.

---

## Mount Points

Every container receives a standard set of bind mounts:

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `{SHARED_DIR}/shared_data` | `/shared` | User workspace (shared across all nodes) |
| `{SHARED_DIR}/logs` | `/kohakuriver-logs` | Task stdout/stderr output files |
| `{LOCAL_TEMP_DIR}` | `/local_temp` | Node-local temporary storage |
| User-defined | User-defined | Additional mounts from `ADDITIONAL_MOUNTS` config |
| Tunnel binary path | `/usr/local/bin/tunnel-client` | Tunnel client binary (read-only, if enabled) |

The working directory inside the container defaults to the task's `working_dir` field, typically a path under `/shared`.

---

## Environment Variables

KohakuRiver injects several environment variables into every container:

| Variable | Value | Purpose |
|----------|-------|---------|
| `KOHAKURIVER_TASK_ID` | Task ID (integer) | Identify the current task |
| `KOHAKURIVER_LOCAL_TEMP_DIR` | Runner's local temp path | Reference node-local storage |
| `KOHAKURIVER_SHARED_DIR` | Runner's shared dir path | Reference shared storage |
| `KOHAKURIVER_TARGET_NUMA_NODE` | NUMA node ID | NUMA binding target (if set) |
| `KOHAKURIVER_TUNNEL_URL` | Runner WebSocket URL | Tunnel client connection endpoint |
| `KOHAKURIVER_CONTAINER_ID` | Container name | Tunnel client identity |
| User-defined `env_vars` | Arbitrary key-value pairs | Custom environment from task submission |

---

## Tunnel Client Integration

When tunnel support is enabled (`TUNNEL_ENABLED = True`), a pre-compiled Rust binary (`tunnel-client`) is injected into every container via a read-only bind mount at `/usr/local/bin/tunnel-client`.

The tunnel client starts as a background daemon before the main process:

```
(nohup /usr/local/bin/tunnel-client \
    --runner-url "$KOHAKURIVER_TUNNEL_URL" \
    --container-id "$KOHAKURIVER_CONTAINER_ID" \
    --log-level info \
    > /tmp/tunnel-client.log 2>&1 &) && sleep 0.1
```

It connects back to the Runner's tunnel server via WebSocket, enabling TCP and UDP port forwarding without Docker port mapping (`-p` flags). This is particularly important for overlay-networked containers where Docker port mapping does not apply.

The tunnel client binary is located via a search path:

1. `{LOCAL_TEMP_DIR}/.kohakuriver/tunnel-client` (local build)
2. `{SHARED_DIR}/bin/tunnel-client` (shared binary)

See the [Tunnel System](../7.%20tunnel-system/) section for the full protocol specification.

---

## Container Lifecycle Operations

Beyond creation, the task executor supports lifecycle operations on running containers:

| Operation | Docker Command | Effect |
|-----------|---------------|--------|
| Kill | `docker kill {name}` | Immediate SIGKILL |
| Pause | `docker pause {name}` | Freeze all processes (SIGSTOP) |
| Resume | `docker unpause {name}` | Unfreeze processes (SIGCONT) |

For kill operations, the task is removed from the Runner's local tracking store **before** the container is killed. This prevents the execution coroutine from reporting a spurious failure status when the container exits with code 137.

### Privileged Mode

When `TASKS_PRIVILEGED = True` in Runner config, containers run with `--privileged`, granting full access to host devices. When disabled (the default), containers receive only `CAP_SYS_NICE` for process priority adjustment.
