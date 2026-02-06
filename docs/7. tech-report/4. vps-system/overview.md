# VPS System Overview

A VPS (Virtual Private Server) in KohakuRiver is a long-running interactive Docker container that persists across user sessions. Unlike command tasks which execute and exit, a VPS stays running indefinitely, providing SSH access, WebSocket-based terminal access, snapshot-based state preservation, and port forwarding.

---

## VPS Concept

The VPS model bridges the gap between ephemeral batch containers and full virtual machines. Users get a persistent workspace that:

- Survives disconnection (the container keeps running)
- Can be accessed via SSH or browser-based terminal
- Preserves state through snapshots (committed Docker images)
- Shares the same resource isolation model as command tasks (CPU, memory, GPU, NUMA)
- Recovers automatically if the Runner process restarts

```
┌────────────────────────────────────────────────────────────┐
│                    VPS Container                            │
│                  (kohakuriver-vps-42)                       │
│                                                            │
│  ┌──────────┐  ┌────────────────┐  ┌───────────────────┐  │
│  │  sshd    │  │ tunnel-client  │  │  User processes   │  │
│  │ (port 22)│  │ (background)   │  │  (interactive)    │  │
│  └────┬─────┘  └───────┬────────┘  └───────────────────┘  │
│       │                │                                   │
│       │    ┌───────────┴───────────┐                       │
│       │    │ /shared (workspace)   │                       │
│       │    │ /local_temp           │                       │
│       │    └───────────────────────┘                       │
└───────┼────────────────┼───────────────────────────────────┘
        │                │
   SSH (mapped port)   WebSocket tunnel
        │                │
   ┌────┴────────────────┴────┐
   │        Runner            │
   │  ┌──────────────────┐    │
   │  │  Tunnel Server   │    │
   │  │  Terminal WS     │    │
   │  └──────────────────┘    │
   └──────────────────────────┘
```

---

## VPS Creation Flow

VPS creation is a multi-step process handled by `create_vps()` in the VPS manager:

```
API Request (/api/vps/submit)
        │
        ▼
┌───────────────────────────┐
│ 1. Check for snapshots    │  If AUTO_RESTORE_ON_CREATE and
│    to restore from        │──snapshot exists, use snapshot
└───────────┬───────────────┘  image instead of base image
            │
            ▼
┌───────────────────────────┐
│ 2. Ensure Docker image    │  Sync from shared storage or
│    is available            │  pull from registry
└───────────┬───────────────┘  (skipped if restoring snapshot)
            │
            ▼
┌───────────────────────────┐
│ 3. Build mount list       │  /shared, /local_temp,
│                           │  ADDITIONAL_MOUNTS, tunnel binary
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ 4. Build docker run cmd   │  Image, network, SSH setup,
│                           │  resources, tunnel wrapper
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ 5. Execute docker run -d  │  Container starts in background
│                           │  (--restart unless-stopped)
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ 6. Find SSH port mapping  │  docker port {name} 22
│    (if SSH enabled)       │  Retries up to 5 times
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ 7. Store state and report │  Add to task_store, report
│    running to Host        │  status with SSH port
└───────────────────────────┘
```

### Docker Run Flags

The VPS container is created with different flags than command tasks:

| Flag | Value | Rationale |
|------|-------|-----------|
| `--restart` | `unless-stopped` | Survive Docker daemon restarts |
| `-d` | (detached) | Run in background, Runner does not wait |
| `-p 0:22` | Dynamic SSH port | Docker assigns available host port (SSH modes only) |
| `--network` | `kohakuriver-overlay` or `kohakuriver-net` | Same network as command tasks |

Unlike command tasks (which use `--rm` and block until exit), VPS containers run detached with an automatic restart policy.

---

## SSH Access Modes

The `ssh_key_mode` parameter controls how SSH is configured inside the VPS container. OpenSSH is installed at container creation time using the appropriate package manager (auto-detected from the image name).

### Mode Comparison

| Mode | `ssh_key_mode` | SSH Installed | Port Mapping | Authentication | Container Process |
|------|---------------|---------------|-------------|----------------|-------------------|
| TTY-only | `disabled` | No | None | N/A | `tail -f /dev/null` |
| Passwordless | `none` | Yes | `-p 0:22` | Empty root password | `sshd -D -e` |
| Generated key | `generate` | Yes | `-p 0:22` | Auto-generated keypair | `sshd -D -e` |
| Uploaded key | `upload` | Yes | `-p 0:22` | User-provided public key | `sshd -D -e` |

### Package Manager Detection

The SSH installation command varies by base image:

| Image Pattern | Package Manager | Install Command |
|--------------|----------------|-----------------|
| `ubuntu`, `debian` | apt | `apt update && apt install -y openssh-server` |
| `alpine` | apk | `apk update && apk add --no-cache openssh` |
| `fedora` | dnf | `dnf install -y openssh-server` |
| `centos`, `rhel`, `rocky`, `alma` | yum | `yum install -y openssh-server` |
| `opensuse`, `suse` | zypper | `zypper refresh && zypper install -y openssh` |
| `arch` | pacman | `pacman -Syu --noconfirm openssh` |

### SSH Port Discovery

Docker dynamically assigns a host port for the container's port 22. After container creation, the Runner queries the mapping:

```bash
$ docker port kohakuriver-vps-42 22
0.0.0.0:32792
[::]:32792
```

The first line is parsed to extract port 32792. This port is reported to the Host, which stores it for SSH proxy routing. If the port cannot be discovered (up to 5 retries with 0.5s delay), the VPS continues operating in TTY-only mode.

---

## Snapshot System

Snapshots preserve the complete filesystem state of a VPS container by committing it to a Docker image. This enables state recovery after container stops or Runner restarts.

### Snapshot Mechanism

```
create_snapshot(task_id)
        │
        ▼
┌───────────────────────────┐
│ Get running container     │  client.containers.get(name)
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ Commit container to image │  container.commit(
│ with pause=True           │    repository="kohakuriver-snapshot/vps-42",
│                           │    tag="1706000000",
└───────────┬───────────────┘    pause=True)
            │
            ▼
┌───────────────────────────┐
│ Cleanup old snapshots     │  Keep MAX_SNAPSHOTS_PER_VPS
│ if limit exceeded         │  (default: 3), remove oldest
└───────────────────────────┘
```

### Naming Convention

Snapshots follow a strict naming pattern:

```
Repository:  kohakuriver-snapshot/vps-{task_id}
Tag:         {unix_timestamp}
Full:        kohakuriver-snapshot/vps-{task_id}:{unix_timestamp}

Example:     kohakuriver-snapshot/vps-42:1706000000
```

### Pause During Commit

The `pause=True` parameter freezes all container processes during the commit operation. This ensures filesystem consistency -- without pausing, active writes could produce a corrupted snapshot. The pause is brief (typically under a second for small filesystem deltas) and processes resume automatically after the commit.

### Automatic Snapshot Cleanup

When `MAX_SNAPSHOTS_PER_VPS` is set (default: 3), old snapshots are automatically removed after each new snapshot. Snapshots are sorted by timestamp (newest first), and those beyond the limit are deleted:

```
Snapshots for VPS 42 (MAX=3):
  kohakuriver-snapshot/vps-42:1706300000  [keep]
  kohakuriver-snapshot/vps-42:1706200000  [keep]
  kohakuriver-snapshot/vps-42:1706100000  [keep]
  kohakuriver-snapshot/vps-42:1706000000  [delete]
```

### Snapshot Operations

| Operation | Function | Description |
|-----------|----------|-------------|
| Create | `create_snapshot(task_id)` | Commit container, return image tag |
| List | `list_snapshots(task_id)` | All snapshots sorted newest first |
| Latest | `get_latest_snapshot(task_id)` | Most recent snapshot tag |
| Delete one | `delete_snapshot(task_id, timestamp)` | Remove specific snapshot |
| Delete all | `delete_all_snapshots(task_id)` | Remove all snapshots for a VPS |
| Cleanup | `cleanup_old_snapshots(task_id, keep)` | Remove oldest beyond keep limit |

---

## VPS Lifecycle Management

### State Transitions

```
                  create_vps()
                      │
                      ▼
               ┌─────────────┐
               │   RUNNING    │◄──────────────────────┐
               └──────┬──────┘                        │
                      │                               │
          ┌───────────┼───────────┐                   │
          │           │           │                   │
          ▼           ▼           ▼                   │
    ┌──────────┐ ┌─────────┐ ┌─────────┐     ┌──────┴──────┐
    │ stop_vps │ │pause_vps│ │  LOST   │     │ resume_vps  │
    └────┬─────┘ └────┬────┘ └────┬────┘     └─────────────┘
         │            │           │                   ▲
         │            ▼           │                   │
         │      ┌──────────┐     │  Runner restart   │
         │      │  PAUSED  │─────┼──────────────────►│
         │      └──────────┘     │  (recovery)       │
         │                       │                    │
         ▼                       ▼                    │
    ┌──────────┐          ┌──────────┐               │
    │ STOPPED  │          │  Host    │───────────────┘
    └──────────┘          │  re-marks│  (on next heartbeat)
                          │  RUNNING │
                          └──────────┘
```

### Operations

| Operation | Docker Commands | Snapshot | Host Report |
|-----------|----------------|----------|-------------|
| **Stop** | `docker stop` then `docker rm` | Auto-snapshot if `AUTO_SNAPSHOT_ON_STOP` | `stopped` |
| **Pause** | `docker pause` | None | `paused` |
| **Resume** | `docker unpause` | None | `running` |
| **Kill** | `docker kill` | None | `killed` |

### Stop with Auto-Snapshot

When `AUTO_SNAPSHOT_ON_STOP = True` (default), stopping a VPS first creates a snapshot of the container state, then stops and removes the container. This allows the VPS to be re-created later from its last state:

```python
# Simplified stop_vps flow:
if should_snapshot:
    create_snapshot(task_id, message="Auto-snapshot on stop")
docker stop {container_name}
docker rm {container_name}
task_store.remove_task(task_id)
```

### Restore on Create

When `AUTO_RESTORE_ON_CREATE = True` (default), creating a VPS first checks for existing snapshots. If a snapshot exists for the same task ID, it is used as the base image instead of the original container image:

```
Image priority:
  1. Latest snapshot (if AUTO_RESTORE_ON_CREATE and snapshot exists)
  2. Registry image (if registry_image specified)
  3. Base image from shared storage (kohakuriver/{name}:base)
```

---

## VPS Recovery on Runner Restart

When a Runner process restarts, VPS containers may still be running (thanks to `--restart unless-stopped`). The startup check reconciles the Runner's in-memory state with actual Docker state:

### Recovery Flow

```
startup_check()
        │
        ▼
┌───────────────────────────┐
│ List all running Docker   │  docker ps (kohakuriver-* only)
│ containers                │
└───────────┬───────────────┘
            │
      ┌─────┴─────┐
      │            │
      ▼            ▼
 Tracked        Not tracked
 in store       (orphan)
      │            │
      ▼            ▼
┌──────────┐  ┌──────────────┐
│ Tracked  │  │ VPS orphan?  │
│ container│  │              │
│ missing? │  │ Yes: recover │──► Add to store, report RUNNING
│          │  │ No:  cleanup │──► docker stop + docker rm
│ Yes:     │  └──────────────┘
│ report   │
│ STOPPED  │
│          │
│ No (VPS):│
│ recover  │──► Find SSH port, report RUNNING to Host
│ SSH port │
└──────────┘
```

### Recovery Categories

| Scenario | Container State | Store State | Action |
|----------|----------------|-------------|--------|
| Normal VPS | Running | Tracked | Recover SSH port, report RUNNING |
| Orphan VPS | Running | Not tracked | Add to store, report RUNNING |
| Missing VPS | Not running | Tracked | Report STOPPED, remove from store |
| Orphan task | Running | Not tracked | Stop and remove container |

During Host downtime, the Host may have marked VPS tasks as `LOST`. When the Runner recovers and reports them as `RUNNING`, the Host transitions them back to active status.

---

## TTY Terminal Access

Every VPS (regardless of SSH mode) supports WebSocket-based terminal access. This provides a browser-accessible shell without SSH.

### Terminal Architecture

```
┌──────────────┐     WebSocket      ┌──────────────┐     docker exec     ┌─────────────┐
│  Web Browser │◄──────────────────►│     Host     │◄──────────────────►│   Runner    │
│  (xterm.js)  │  {type, data}      │  (WS proxy)  │  {type, data}      │             │
└──────────────┘                    └──────────────┘                    │  ┌─────────┐│
                                                                       │  │Container ││
                                                                       │  │ docker   ││
                                                                       │  │ exec     ││
                                                                       │  │ /bin/bash││
                                                                       │  └─────────┘│
                                                                       └─────────────┘
```

### WebSocket Protocol

Messages are JSON-encoded with two types:

**Client to Runner:**

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"input"` | Terminal keystroke data |
| `data` | string | UTF-8 encoded input |
| `type` | `"resize"` | Terminal size change |
| `rows` | int | New row count |
| `cols` | int | New column count |

**Runner to Client:**

| Field | Type | Description |
|-------|------|-------------|
| `type` | `"output"` | Terminal output data |
| `data` | string | UTF-8 decoded container output |
| `type` | `"error"` | Error message |
| `data` | string | Error description |

### Docker Exec Session

The terminal endpoint creates a `docker exec` session with TTY enabled:

1. Resolve task ID to container name via local task store
2. Detect available shell (`/bin/bash` preferred, falls back to `/bin/sh`)
3. Create exec instance with stdin, stdout, stderr, and TTY
4. Start exec and obtain raw socket
5. Run bidirectional I/O loop (WebSocket <-> Docker socket)
6. On disconnect: kill exec process and all child processes

### Process Cleanup

When the WebSocket disconnects, the terminal endpoint kills the exec process tree to prevent orphaned shells:

```
1. Inspect exec to get PID
2. Send SIGHUP to process group (kill -1 -{pid})
3. Wait 100ms for graceful shutdown
4. Send SIGKILL to process group (kill -9 -{pid})
```

---

## Port Forwarding Integration

VPS containers integrate with the tunnel system for port forwarding. The tunnel client binary runs as a background daemon alongside the SSH server (or `tail -f /dev/null` in TTY-only mode):

```bash
# VPS startup command (with SSH and tunnel):
(nohup /usr/local/bin/tunnel-client \
    --runner-url "$KOHAKURIVER_TUNNEL_URL" \
    --container-id "$KOHAKURIVER_CONTAINER_ID" \
    --log-level info > /tmp/tunnel-client.log 2>&1 &) \
&& sleep 0.1 \
&& apt update && apt install -y openssh-server \
&& ... \
&& /usr/sbin/sshd -D -e
```

For VPS containers, `use_exec=False` when wrapping with the tunnel client, since the main process (sshd or tail) must stay running as PID 1 in the shell. This differs from command tasks where `exec` replaces the shell.

See the [Tunnel System](../7.%20tunnel-system/) section for protocol details and the [Container System](../3.%20container-system/overview.md) for the tunnel mount mechanism.
