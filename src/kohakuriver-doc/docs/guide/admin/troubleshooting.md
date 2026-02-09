---
title: Troubleshooting
description: Common issues and solutions for KohakuRiver clusters.
icon: i-carbon-debug
---

# Troubleshooting

Common issues and their solutions when operating a KohakuRiver cluster.

## Connection Issues

### Runner Cannot Connect to Host

**Symptom**: Runner logs show connection refused or timeout when registering.

**Solutions**:

1. Verify the host is running: `curl http://host:8000/api/health`
2. Check `HOST_ADDRESS` in runner config points to the correct host
3. Ensure port 8000 is not blocked by firewall
4. Verify `HOST_REACHABLE_ADDRESS` in host config is accessible from the runner's network

### CLI Cannot Reach Host

**Symptom**: CLI commands return connection errors.

**Solutions**:

1. Check host address: `kohakuriver config show`
2. Set the correct address: `export KOHAKURIVER_HOST=http://host:8000`
3. Test connectivity: `curl http://host:8000/api/health`

### SSH Connection Fails

**Symptom**: `kohakuriver ssh <task_id>` times out or is refused.

**Solutions**:

1. Verify VPS is running: `kohakuriver vps status <task_id>`
2. Check SSH is enabled (task has an `ssh_port` value)
3. Verify port 8002 is accessible on the host
4. Check SSH server is running inside the container: `kohakuriver terminal exec <task_id> -- service ssh status`
5. Verify SSH key was injected: `kohakuriver terminal exec <task_id> -- cat /root/.ssh/authorized_keys`

## Task Issues

### Task Stuck in "assigning"

**Symptom**: Task remains in `assigning` state and never becomes `running`.

**Causes and solutions**:

1. **Runner offline**: Check runner status with `kohakuriver node status <hostname>`
2. **Runner cannot reach host**: The runner must be able to receive requests from the host
3. **Docker pull failure**: If using a registry image, the runner may be stuck pulling. Check runner logs.
4. **Resource exhaustion**: The runner node may be out of disk space or memory

After 3x heartbeat interval without runner confirmation, the task is automatically marked as `failed`.

### Task Fails Immediately

**Symptom**: Task goes from `assigning` to `failed` with an error message.

**Common causes**:

- Container image not found (check `--container` or `--image` name)
- Command not found in the container
- Insufficient resources on the node
- GPU index out of range
- Permission denied (if running as non-root in the container)

Check the error message:

```bash
kohakuriver task status <task_id>
```

### Task Killed by OOM

**Symptom**: Task status is `killed_oom`.

**Solutions**:

1. Increase memory allocation: `-m 16G` or larger
2. Check actual memory usage before the kill (task logs may show the peak)
3. Optimize the workload to use less memory
4. Use swap (not recommended for performance-sensitive tasks)

### Task Output Missing

**Symptom**: `kohakuriver task logs <task_id>` shows empty output.

**Solutions**:

1. Check the task actually produced output
2. If shared storage is configured, verify it is mounted on the runner: the runner writes logs to `SHARED_DIR/logs/<task_id>/`
3. Check file permissions on the storage directory
4. If the task is still running, try `-f` flag for live follow

## Node Issues

### Node Shows Offline

**Symptom**: Node is marked `offline` in node list.

**Solutions**:

1. Check runner process is running on the node
2. Verify network connectivity between runner and host
3. Check runner logs for errors
4. Restart the runner: `sudo systemctl restart kohakuriver-runner`

### GPU Not Detected

**Symptom**: Node status shows no GPUs.

**Solutions**:

1. Install GPU monitoring: `pip install "kohakuriver[gpu]"`
2. Verify NVIDIA drivers: `nvidia-smi`
3. Restart the runner after installing `nvidia-ml-py`

### Incorrect Resource Counts

**Symptom**: Node reports wrong number of cores or memory.

The runner detects resources automatically on startup. If the hardware changed, restart the runner to re-detect.

## VPS Issues

### Docker VPS Container Exits

**Symptom**: Docker VPS goes to `failed` shortly after creation.

**Solutions**:

1. The container's entrypoint must stay running (e.g., an SSH server or shell)
2. Check container logs for crash output
3. Verify the container environment has required services installed

### VM VPS Fails to Boot

**Symptom**: QEMU VM VPS goes to `failed`.

**Solutions**:

1. Check QEMU availability: `kohakuriver qemu check`
2. Verify base image exists: `kohakuriver qemu image list`
3. Check KVM is enabled: `ls /dev/kvm`
4. Check runner logs for QEMU error output
5. Verify sufficient RAM for the VM allocation

### GPU Not Visible in VM

**Solutions**:

1. Verify IOMMU: `kohakuriver qemu check`
2. Check IOMMU groups: `find /sys/kernel/iommu_groups -type l`
3. Enable ACS override if GPUs share IOMMU groups
4. Ensure the GPU is not in use by another task or the host X server

### VFIO Bind Fails (Xorg Holding GPUs)

**Symptom**: VM creation fails with "No such device" or VFIO bind timeout. `sudo fuser /dev/nvidia*` shows Xorg holding all GPUs.

**Cause**: Xorg auto-adds all GPUs by default, even on nodes using an ASPEED BMC (AST2400/2500) for display. This keeps `/dev/nvidia*` file descriptors open, blocking VFIO unbinding.

**Solution**: Disable Xorg GPU auto-detection:

```bash
sudo mkdir -p /etc/X11/xorg.conf.d
echo 'Section "ServerFlags"
    Option "AutoAddGPU" "false"
EndSection' | sudo tee /etc/X11/xorg.conf.d/01-no-auto-gpu.conf
sudo systemctl restart gdm   # or lightdm/sddm
```

See [GPU Passthrough setup](../setup/gpu-passthrough.md) for details.

### VMs Killed When Runner Restarts

**Symptom**: Running QEMU VMs die when the runner service is restarted.

**Cause**: systemd's default `KillMode=control-group` kills all processes in the service's cgroup, including daemonized QEMU processes.

**Solution**: Ensure `KillMode=process` is set in the runner service file:

```bash
# Check current setting
grep KillMode /etc/systemd/system/kohakuriver-runner.service

# If missing, add to [Service] section:
#   KillMode=process
sudo systemctl daemon-reload
sudo systemctl restart kohakuriver-runner
```

See [Systemd Services](../setup/systemd-services.md) for the full service configuration.

## Overlay Network Issues

### Containers Cannot Communicate Across Nodes

**Solutions**:

1. Verify overlay is enabled on host and runners
2. Check VXLAN interface: `ip link show kohaku-overlay` (on runner nodes)
3. Verify firewall allows UDP port 4789
4. Check overlay subnet allocation: `kohakuriver node overlay <hostname>`
5. Test basic connectivity: `ping <container_ip>` from the host

### IP Reservation Failures

**Solutions**:

1. Check available IPs: `kohakuriver node ip-available <hostname>`
2. Expired reservations are cleaned up automatically
3. Release unused reservations: `kohakuriver node ip-release <hostname> --token <token>`

## Authentication Issues

### Login Fails

**Solutions**:

1. Verify `AUTH_ENABLED = True` on the host
2. Check username and password
3. Try the API directly: `curl -X POST http://host:8000/api/auth/login -d '{"username":"...","password":"..."}'`
4. For first-time setup, use `ADMIN_REGISTER_SECRET` to create the admin account

### Session Expired

**Symptom**: API calls return 401 after some time.

**Solution**: Log in again. Sessions expire after `SESSION_EXPIRE_HOURS` (default: 24).

```bash
kohakuriver auth logout
kohakuriver auth login
```

## Checking Logs

### Host Logs

```bash
journalctl -u kohakuriver-host -f
```

### Runner Logs

```bash
journalctl -u kohakuriver-runner -f
```

KohakuRiver uses Loguru for logging. Log levels can be adjusted in the configuration.

## Related Topics

- [Backup & Recovery](backup-recovery.md) -- Recovery procedures
- [Monitoring](../tasks/monitoring.md) -- Monitoring tools
- [Security Hardening](../setup/security-hardening.md) -- Security setup
