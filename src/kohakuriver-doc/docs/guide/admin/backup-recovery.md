---
title: Backup & Recovery
description: Backing up and restoring KohakuRiver cluster state.
icon: i-carbon-data-backup
---

# Backup & Recovery

KohakuRiver stores its state in a SQLite database. Shared storage is optional but recommended -- when configured, it holds environment tarballs and task logs. This guide covers backup strategies and recovery procedures.

## What to Back Up

### Host Database

The SQLite database contains all cluster state:

- Task records (submissions, status, history)
- Node registrations
- User accounts and sessions (when auth enabled)
- Overlay network allocations
- IP reservations

Default location: `SHARED_DIR/kohakuriver.db` (configurable via `DB_FILE` in host config).

### Configuration Files

```
~/.kohakuriver/
  host_config.py          # Host configuration
  runner_config.py        # Runner configuration
  session                 # CLI auth token
```

### Shared Storage

```
SHARED_DIR/
  environments/           # Container environment tarballs
  logs/                   # Task output logs
  kohakuriver.db          # Database (if using default path)
```

### Runner-Local Data

On each runner node:

```
VM_IMAGES_DIR/            # Base VM images
VM_INSTANCES_DIR/         # Active VM disk images
LOCAL_TEMP_DIR/           # Temporary files
```

Docker images and snapshots are stored in Docker's local storage on each runner.

## Backup Procedures

### Database Backup

```bash
# Simple file copy (stop host first for consistency)
cp SHARED_DIR/kohakuriver.db SHARED_DIR/kohakuriver.db.backup

# SQLite online backup (no downtime)
sqlite3 SHARED_DIR/kohakuriver.db ".backup '/path/to/backup.db'"
```

For automated backups, use a cron job:

```bash
# Daily backup with timestamp
0 2 * * * sqlite3 /cluster-share/kohakuriver.db ".backup '/backups/kohakuriver-$(date +\%Y\%m\%d).db'"
```

### Configuration Backup

```bash
# Copy config directory
cp -r ~/.kohakuriver/ /backups/kohakuriver-config/
```

### Environment Tarballs

Environment tarballs in `SHARED_DIR/environments/` are already on shared storage. If your shared storage has its own backup mechanism (e.g., ZFS snapshots, NFS snapshots), this is covered automatically.

For additional safety:

```bash
# List environments
kohakuriver docker tar list

# Backup environments directory
rsync -av SHARED_DIR/environments/ /backups/environments/
```

### VM Base Images

```bash
# On each runner node
rsync -av ~/.kohakuriver/vm-images/ /backups/vm-images/
```

## Recovery Procedures

### Restore Database

```bash
# Stop the host
sudo systemctl stop kohakuriver-host

# Replace database
cp /backups/kohakuriver.db SHARED_DIR/kohakuriver.db

# Start the host
sudo systemctl start kohakuriver-host
```

On restart, the host reads the restored database. Runners will re-register and reconcile their running task states via heartbeats.

### Restore Configuration

```bash
cp -r /backups/kohakuriver-config/ ~/.kohakuriver/
sudo systemctl restart kohakuriver-host
```

### Recover from Host Failure

If the host machine fails completely:

1. Provision a new host machine
2. Install KohakuRiver: `pip install kohakuriver`
3. Restore configuration files
4. Restore the database to shared storage
5. Start the host: `kohakuriver host`
6. Runners will automatically reconnect (ensure `HOST_REACHABLE_ADDRESS` points to the new host)

### Recover from Runner Failure

If a runner node fails:

1. Running tasks on the node are marked as `lost` after heartbeat timeout
2. Provision a replacement node
3. Install KohakuRiver and Docker
4. Copy or recreate the runner configuration
5. Start the runner: `kohakuriver runner`
6. The runner registers as a new (or returning) node

VPS instances on the failed runner cannot be recovered unless the runner's local disk (Docker volumes, VM disk images) is intact.

### Recover Lost Tasks

Tasks marked as `lost` cannot be automatically restarted. To resubmit:

```bash
# Check lost tasks
kohakuriver task list -s lost

# Resubmit on a different node
kohakuriver task submit -t other-node -- <original command>
```

## Disaster Recovery Checklist

- [ ] Database is backed up regularly (daily recommended)
- [ ] Configuration files are version-controlled or backed up
- [ ] Environment tarballs are on redundant storage
- [ ] VM base images are backed up separately
- [ ] `HOST_REACHABLE_ADDRESS` can be updated if host IP changes
- [ ] Recovery procedure is documented and tested

## Related Topics

- [Host Configuration](../setup/host-configuration.md) -- Config reference
- [Shared Storage](../setup/shared-storage.md) -- Storage setup
- [Troubleshooting](troubleshooting.md) -- Common issues
