# KohakuRiver VPS System

Long-running interactive Docker sessions with SSH access, snapshots, and terminal integration. This section covers VPS creation, access modes, snapshot management, and lifecycle operations.

## Documents

| Document | Description |
|----------|-------------|
| [overview.md](overview.md) | VPS architecture: creation flow, SSH modes, snapshot system, lifecycle management, recovery, and terminal access |

## Quick Reference

### VPS vs Command Tasks

| Aspect | Command Task | VPS Session |
|--------|-------------|-------------|
| Container name | `kohakuriver-task-{id}` | `kohakuriver-vps-{id}` |
| Docker restart policy | `--rm` (auto-remove) | `--restart unless-stopped` |
| Execution mode | Run command, capture output, exit | Keep running indefinitely |
| Access | None (output via shared storage) | SSH, WebSocket TTY, or both |
| Snapshots | Not supported | Commit container state to image |
| Port forwarding | Via tunnel client | SSH port mapping + tunnel client |

### SSH Key Modes

| Mode | SSH Server | Authentication | Use Case |
|------|-----------|---------------|----------|
| `disabled` | Not installed | N/A (TTY-only) | Lightweight sessions, no SSH overhead |
| `none` | Installed | Passwordless root | Quick access, development environments |
| `generate` | Installed | Generated keypair | Secure access, keys returned to user |
| `upload` | Installed | User-provided public key | Bring-your-own-key access |

### Snapshot Naming

```
kohakuriver-snapshot/vps-{task_id}:{unix_timestamp}

Example: kohakuriver-snapshot/vps-42:1706000000
```

### Key Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTO_SNAPSHOT_ON_STOP` | `True` | Create snapshot before stopping VPS |
| `MAX_SNAPSHOTS_PER_VPS` | `3` | Maximum snapshots kept per VPS |
| `AUTO_RESTORE_ON_CREATE` | `True` | Restore from latest snapshot when re-creating |

### Key Source Files

| File | Purpose |
|------|---------|
| `runner/services/vps_manager.py` | VPS creation, snapshots, lifecycle operations |
| `runner/endpoints/terminal.py` | WebSocket TTY terminal access |
| `runner/background/startup_check.py` | VPS recovery after runner restart |
| `docker/naming.py` | Snapshot and container naming conventions |
