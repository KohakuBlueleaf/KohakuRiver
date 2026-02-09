---
title: Shared Storage
description: Setting up shared storage between host and runner nodes using NFS, Samba, SSHFS, or bind mounts.
icon: i-carbon-data-share
---

# Shared Storage

For the best experience, KohakuRiver recommends a shared filesystem accessible by all cluster nodes. This storage is used for container tarballs, task logs, and user data. The mount path does not need to be identical on every node -- each node configures its own `SHARED_DIR` setting to point to the shared filesystem. However, shared storage is not strictly required -- containers can alternatively be pulled from Docker registries (using the `registry_image` field), and VMs use local disk images. If you only use registry-based containers, you can skip shared storage setup entirely.

## Why Shared Storage?

- **Container distribution** -- Container environment tarballs are stored in `SHARED_DIR/kohakuriver-containers/` and accessed by all runners
- **Task logs** -- stdout/stderr from tasks are written to `SHARED_DIR/logs/`
- **User data** -- The shared directory is mounted at `/shared` inside containers, giving users a common workspace
- **No registry needed** -- Avoids the complexity of running a Docker image registry

## Default Path

The default shared directory is `/mnt/cluster-share`. The mount path does not need to be the same on every node -- each node sets its own `SHARED_DIR` in its config to point to wherever the shared filesystem is mounted. What matters is that all nodes access the same underlying storage.

## NFS Setup

NFS is the most common choice for Linux clusters.

### NFS Server (on one node)

```bash
sudo apt install nfs-kernel-server

# Create the shared directory
sudo mkdir -p /mnt/cluster-share
sudo chown nobody:nogroup /mnt/cluster-share

# Export the directory
echo "/mnt/cluster-share *(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports
sudo exportfs -ra
sudo systemctl restart nfs-kernel-server
```

### NFS Client (on all other nodes)

```bash
sudo apt install nfs-common
sudo mkdir -p /mnt/cluster-share
sudo mount -t nfs server-ip:/mnt/cluster-share /mnt/cluster-share
```

To make permanent, add to `/etc/fstab`:

```
server-ip:/mnt/cluster-share /mnt/cluster-share nfs defaults,_netdev 0 0
```

## Samba/CIFS Setup

For mixed OS environments or Windows compatibility.

### Samba Server

```bash
sudo apt install samba
sudo mkdir -p /mnt/cluster-share
```

Add to `/etc/samba/smb.conf`:

```ini
[cluster-share]
    path = /mnt/cluster-share
    browsable = yes
    writable = yes
    guest ok = no
```

### CIFS Client

```bash
sudo apt install cifs-utils
sudo mkdir -p /mnt/cluster-share
sudo mount -t cifs //server-ip/cluster-share /mnt/cluster-share -o username=user,password=pass
```

## SSHFS Setup

Simple option for small clusters or testing. Lower performance than NFS.

```bash
sudo apt install sshfs
sudo mkdir -p /mnt/cluster-share
sshfs user@server-ip:/mnt/cluster-share /mnt/cluster-share -o allow_other
```

To make permanent, add to `/etc/fstab`:

```
user@server-ip:/mnt/cluster-share /mnt/cluster-share fuse.sshfs _netdev,allow_other,IdentityFile=/home/user/.ssh/id_rsa 0 0
```

## Bind Mounts (Single Machine)

For testing on a single machine where both host and runner run locally:

```bash
sudo mkdir -p /mnt/cluster-share
# No additional setup needed -- the directory is already shared
```

## Directory Structure

KohakuRiver automatically creates these subdirectories:

```
/mnt/cluster-share/
├── kohakuriver-containers/    # Container environment tarballs
│   ├── kohakuriver-base/      # Default environment
│   │   └── kohakuriver-base_<timestamp>.tar.gz
│   └── my-custom-env/
│       └── my-custom-env_<timestamp>.tar.gz
├── logs/                      # Task output logs
│   ├── 1234567890123456/
│   │   ├── stdout.log
│   │   └── stderr.log
│   └── ...
└── bin/                       # Optional: shared binaries
    └── tunnel-client          # Tunnel client binary
```

## Verification

After setting up shared storage, verify on all nodes:

```bash
# Check the path exists and is writable
ls -la /mnt/cluster-share
touch /mnt/cluster-share/test-$(hostname)
ls /mnt/cluster-share/test-*  # Should show files from all nodes
rm /mnt/cluster-share/test-*
```

## Performance Considerations

- **NFS** is recommended for most setups. Use NFSv4 for better performance.
- For GPU training workloads, consider storing large datasets on local SSDs and using shared storage only for code and small files.
- Container tarballs can be large (several GB). The initial tarball sync will take longer over slow network links.
