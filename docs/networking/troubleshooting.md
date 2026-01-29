# Networking Troubleshooting Guide

Common issues and solutions for KohakuRiver networking.

## Quick Diagnostics

Run these commands to gather information for troubleshooting:

### On Host

```bash
# Check overlay status via CLI
kohakuriver node overlay

# Check host dummy interface (should have 10.0.0.1/8)
ip addr show kohaku-host

# List VXLAN interfaces (one per runner)
ip link show | grep vxkr

# Check VXLAN details (VNI, remote IP)
ip -d link show vxkr1

# Check IP forwarding is enabled
cat /proc/sys/net/ipv4/ip_forward
```

### On Runner

```bash
# Check VXLAN interface
ip link show vxlan0

# Check bridge
ip link show kohaku-overlay
ip addr show kohaku-overlay

# Check Docker network
docker network ls | grep overlay
docker network inspect kohakuriver-overlay

# Test connectivity to Host overlay IP
ping 10.0.0.1
```

---

## Common Issues

### Issue: "Overlay not enabled" in status

**Symptoms:**
- `kohakuriver node overlay` shows "Overlay not enabled"
- Containers can't reach other nodes

**Cause:** `OVERLAY_ENABLED` is not set to `True` in config.

**Solution:**

1. Edit Host config (`~/.kohakuriver/host_config.py`):
   ```python
   OVERLAY_ENABLED: bool = True
   ```

2. Edit Runner config (`~/.kohakuriver/runner_config.py`):
   ```python
   OVERLAY_ENABLED: bool = True
   ```

3. Restart services:
   ```bash
   sudo systemctl restart kohakuriver-host
   sudo systemctl restart kohakuriver-runner
   ```

---

### Issue: VXLAN remote shows 127.0.0.1

**Symptoms:**
- `ip -d link show vxkr1` shows `remote 127.0.0.1`
- Cross-node communication fails
- Runners registered but no connectivity

**Cause:** `HOST_REACHABLE_ADDRESS` is not configured correctly in Host config.

**Solution:**

1. Edit Host config (`~/.kohakuriver/host_config.py`):
   ```python
   # Set to the Host's actual IP address that Runners can reach
   HOST_REACHABLE_ADDRESS: str = "192.168.88.53"  # Your Host IP!
   ```

2. Restart Host:
   ```bash
   sudo systemctl restart kohakuriver-host
   ```

3. Restart all Runners (to re-register and recreate VXLAN):
   ```bash
   sudo systemctl restart kohakuriver-runner
   ```

---

### Issue: Runner shows "Inactive" in overlay status

**Symptoms:**
- Runner appears in overlay status but shows "Inactive"
- Runner is actually running and connected

**Cause:** Runner hasn't sent a heartbeat since Host restart, or heartbeat handler isn't updating overlay status.

**Solution:**

1. Wait for next heartbeat (default 5 seconds)
2. If still inactive, restart the runner:
   ```bash
   sudo systemctl restart kohakuriver-runner
   ```

---

### Issue: VXLAN interface not created on Host

**Symptoms:**
- `ip link show | grep vxkr` shows nothing on Host
- Runner registered but no VXLAN tunnel

**Cause:** VXLAN creation failed, likely due to permissions or firewall.

**Solution:**

1. Check Host logs for VXLAN errors:
   ```bash
   journalctl -u kohakuriver-host | grep -i vxlan
   ```

2. Ensure Host is running as root (needed for network interface creation)

3. Verify pyroute2 is installed:
   ```bash
   pip show pyroute2
   ```

4. Ensure UDP 4789 is open:
   ```bash
   sudo iptables -L -n | grep 4789
   ```

---

### Issue: Containers can't ping across nodes

**Symptoms:**
- Container on Runner A can't ping container on Runner B
- Both containers have 10.X.x.x IPs

**Diagnosis:**

From container on Runner A, try pinging in order:
```bash
# 1. Local gateway (should work)
ping 10.1.0.1

# 2. Host overlay IP (tests VXLAN to Host)
ping 10.0.0.1

# 3. Remote container (tests full path)
ping 10.2.0.x
```

- If step 2 fails: VXLAN tunnel from Runner A to Host is broken
- If step 2 works but step 3 fails: Host routing or firewall issue

**Solutions:**

**VXLAN tunnel broken:**
```bash
# On Host, check VXLAN interface for the runner
ip -d link show vxkr1

# Verify:
# - remote IP is correct (Runner's physical IP)
# - local IP is correct (Host's physical IP)
```

**Firewall blocking forwarding:**

Check iptables rules:
```bash
sudo iptables -L FORWARD -n -v --line-numbers | head -10
```

If rules for 10.0.0.0/8 are missing or at bottom:
```bash
# Rules should be at top of FORWARD chain
sudo iptables -I FORWARD 1 -s 10.0.0.0/8 -j ACCEPT
sudo iptables -I FORWARD 2 -d 10.0.0.0/8 -j ACCEPT
```

**firewalld blocking (nftables backend):**

Check if firewalld is running:
```bash
sudo firewall-cmd --state
```

Check vxkr interfaces zone:
```bash
sudo firewall-cmd --get-zone-of-interface=vxkr1
```

If not in trusted zone, add manually:
```bash
sudo firewall-cmd --zone=trusted --add-interface=vxkr1
```

Note: KohakuRiver should do this automatically. If it's not working, check Host logs for firewalld errors.

---

### Issue: Container can't reach Host at 10.0.0.1

**Symptoms:**
- Container can ping other containers
- Container can't ping 10.0.0.1
- `tunnel-client` fails to connect

**Cause:** Host dummy interface doesn't have the overlay IP assigned.

**Solution:**

1. Check Host has kohaku-host interface with IP:
   ```bash
   ip addr show kohaku-host | grep "10.0.0.1"
   ```

2. If missing, restart Host:
   ```bash
   sudo systemctl restart kohakuriver-host
   ```

3. Verify after restart:
   ```bash
   ip addr show kohaku-host
   ```

---

### Issue: Docker network not created on Runner

**Symptoms:**
- `docker network ls | grep overlay` shows nothing
- Containers fail to start with network error

**Cause:** Runner overlay manager failed to create Docker network.

**Solution:**

1. Check if bridge exists:
   ```bash
   ip link show kohaku-overlay
   ```

2. If bridge exists, try creating network manually:
   ```bash
   docker network create \
     --driver bridge \
     --subnet 10.X.0.0/16 \
     --gateway 10.X.0.1 \
     -o com.docker.network.bridge.name=kohaku-overlay \
     kohakuriver-overlay
   ```
   (Replace X with your runner ID)

3. If that fails, check Docker logs:
   ```bash
   journalctl -u docker
   ```

---

### Issue: "No available runner IDs" error

**Symptoms:**
- New runner fails to register
- Host logs show "No available runner IDs"

**Cause:** All 255 runner IDs are allocated and none are inactive for cleanup.

**Solution:**

1. Check current allocations:
   ```bash
   kohakuriver node overlay
   ```

2. Release unused allocations:
   ```bash
   # Release specific runner
   kohakuriver node overlay-release <runner-name>

   # Or cleanup all inactive
   kohakuriver node overlay-cleanup
   ```

3. If runners are still needed, consider if some are duplicates or old names.

---

### Issue: Runner gets different subnet after restart

**Symptoms:**
- Runner had 10.1.0.0/16, now has 10.3.0.0/16
- Existing containers have wrong IPs

**Cause:** Runner registered with different hostname, so got new allocation.

**Solution:**

1. Check hostname hasn't changed:
   ```bash
   hostname
   ```

2. If hostname changed, either:
   - Set hostname back to original
   - Release old allocation and let containers be recreated

3. Existing containers need to be recreated to get new IPs:
   ```bash
   # Stop and restart VPS
   kohakuriver vps stop <task-id>
   kohakuriver vps create --target <runner> ...
   ```

---

### Issue: High latency on overlay network

**Symptoms:**
- Cross-node pings are slow (>10ms on local network)
- Network-heavy workloads perform poorly

**Diagnosis:**

Compare physical vs overlay latency:
```bash
# Physical network (from Runner)
ping <other-node-physical-ip>

# Overlay network (from container)
ping 10.X.0.x
```

Expected overhead: <1ms for VXLAN encapsulation

**Solutions:**

**CPU overload:**
```bash
# Check if Host CPU is saturated
top
```

**MTU issues causing fragmentation:**
```bash
# Test with different packet sizes
ping -M do -s 1400 10.X.0.x  # Should work
ping -M do -s 1450 10.X.0.x  # Might fail if MTU wrong
```

**Network path issues:**
- Ensure Host and Runners are on same switch/subnet
- Check for bandwidth bottlenecks

---

### Issue: Overlay works, but tunnel-client fails

**Symptoms:**
- Containers can ping 10.0.0.1
- `tunnel-client` can't connect

**Cause:** tunnel-client may be trying to use wrong gateway or port.

**Solution:**

1. Verify tunnel-client is using overlay gateway:
   ```bash
   # Inside container
   echo $KOHAKU_GATEWAY  # Should be 10.0.0.1 or similar
   ```

2. Check Host SSH proxy is listening:
   ```bash
   # On Host
   ss -tlnp | grep 8002
   ```

3. Ensure container can reach Host on SSH proxy port:
   ```bash
   # Inside container
   nc -zv 10.0.0.1 8002
   ```

---

### Issue: "admin prohibited filter" ICMP errors

**Symptoms:**
- tcpdump shows packets arriving at Host
- Response is "ICMP host unreachable - admin prohibited filter"

**Cause:** firewalld (using nftables backend) is blocking traffic. iptables rules alone don't help because nftables is evaluated first.

**Solution:**

Add vxkr interfaces to firewalld trusted zone:
```bash
# For each vxkr interface
sudo firewall-cmd --zone=trusted --add-interface=vxkr1
sudo firewall-cmd --zone=trusted --add-interface=vxkr2
```

KohakuRiver should do this automatically. Check Host logs if it's not happening:
```bash
journalctl -u kohakuriver-host | grep -i firewall
```

---

## Log Locations

| Component | Log Location |
|-----------|--------------|
| Host | `journalctl -u kohakuriver-host` or configured log file |
| Runner | `journalctl -u kohakuriver-runner` or configured log file |
| Docker | `journalctl -u docker` |

### Enabling Debug Logs

In config files:
```python
from kohakuriver.models.enums import LogLevel

LOG_LEVEL: LogLevel = LogLevel.DEBUG
```

Then restart the service.

---

## Recovery Procedures

### Full Overlay Reset (Host)

If overlay is corrupted, do a full reset:

```bash
# 1. Stop Host
sudo systemctl stop kohakuriver-host

# 2. Remove all VXLAN interfaces
for iface in $(ip link show | grep vxkr | cut -d: -f2 | cut -d@ -f1 | tr -d ' '); do
    sudo ip link delete $iface 2>/dev/null
done

# 3. Remove host dummy interface
sudo ip link delete kohaku-host 2>/dev/null

# 4. Start Host (will recreate everything)
sudo systemctl start kohakuriver-host

# 5. Restart all Runners
# (on each runner)
sudo systemctl restart kohakuriver-runner
```

### Full Overlay Reset (Runner)

```bash
# 1. Stop Runner
sudo systemctl stop kohakuriver-runner

# 2. Remove Docker network
docker network rm kohakuriver-overlay 2>/dev/null

# 3. Remove VXLAN
sudo ip link delete vxlan0 2>/dev/null

# 4. Remove bridge
sudo ip link delete kohaku-overlay 2>/dev/null

# 5. Start Runner
sudo systemctl start kohakuriver-runner
```

---

## Migration Guide

### Migrating to a Different OVERLAY_SUBNET

When changing `OVERLAY_SUBNET` configuration (e.g., from `10.0.0.0/8/8/16` to `10.128.0.0/12/6/14`), you must manually clean up existing VXLAN interfaces because the IP scheme changes completely.

**Why manual cleanup is required:**
- Existing VXLAN interfaces have IPs from the old scheme
- Kernel routes point to old subnets
- Docker networks use old IP ranges
- Simply restarting services won't clean up stale interfaces

### Step-by-Step Migration

**1. Stop all services (on all nodes):**

```bash
# On Host
sudo systemctl stop kohakuriver-host

# On all Runners
sudo systemctl stop kohakuriver-runner
```

**2. Clean up Host node:**

```bash
# Remove all VXLAN interfaces
for iface in $(ip link show | grep vxkr | cut -d: -f2 | cut -d@ -f1 | tr -d ' '); do
    sudo ip link delete "$iface" 2>/dev/null
    echo "Deleted $iface"
done

# Remove host dummy interface
sudo ip link delete kohaku-host 2>/dev/null

# Remove old iptables rules (if using old 10.0.0.0/8 default)
sudo iptables -D FORWARD -s 10.0.0.0/8 -j ACCEPT 2>/dev/null
sudo iptables -D FORWARD -d 10.0.0.0/8 -j ACCEPT 2>/dev/null

# Verify cleanup
ip link show | grep -E "vxkr|kohaku"  # Should show nothing
```

**3. Clean up each Runner node:**

```bash
# Remove Docker overlay network
docker network rm kohakuriver-overlay 2>/dev/null

# Remove VXLAN interface
sudo ip link delete vxlan0 2>/dev/null

# Remove overlay bridge
sudo ip link delete kohaku-overlay 2>/dev/null

# Remove old iptables/NAT rules
sudo iptables -D FORWARD -s 10.0.0.0/8 -j ACCEPT 2>/dev/null
sudo iptables -D FORWARD -d 10.0.0.0/8 -j ACCEPT 2>/dev/null
sudo iptables -t nat -D POSTROUTING -s 10.0.0.0/8 ! -d 10.0.0.0/8 -j MASQUERADE 2>/dev/null

# Verify cleanup
ip link show | grep -E "vxlan|kohaku"  # Should show nothing
docker network ls | grep overlay  # Should show nothing
```

**4. Update configuration files:**

```bash
# On Host (~/.kohakuriver/host_config.py)
OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"  # New subnet

# On all Runners (~/.kohakuriver/runner_config.py)
OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"  # Must match Host!
```

**5. Restart services:**

```bash
# Start Host first
sudo systemctl start kohakuriver-host

# Then start all Runners
sudo systemctl start kohakuriver-runner
```

**6. Verify new configuration:**

```bash
# On Host
kohakuriver node overlay
ip addr show kohaku-host  # Should show new host IP (e.g., 10.128.0.1)

# On Runner
ip addr show kohaku-overlay  # Should show new gateway IP
docker network inspect kohakuriver-overlay  # Should show new subnet
```

### Quick Cleanup Script

Save this as `cleanup-overlay.sh` and run on each node:

```bash
#!/bin/bash
# Cleanup overlay network for migration
set -e

echo "Stopping services..."
sudo systemctl stop kohakuriver-host 2>/dev/null || true
sudo systemctl stop kohakuriver-runner 2>/dev/null || true

echo "Removing Docker overlay network..."
docker network rm kohakuriver-overlay 2>/dev/null || true

echo "Removing network interfaces..."
for iface in $(ip link show | grep -E "vxkr|vxlan0|kohaku" | cut -d: -f2 | cut -d@ -f1 | tr -d ' '); do
    sudo ip link delete "$iface" 2>/dev/null || true
    echo "  Deleted $iface"
done

echo "Removing iptables rules..."
sudo iptables -D FORWARD -s 10.0.0.0/8 -j ACCEPT 2>/dev/null || true
sudo iptables -D FORWARD -d 10.0.0.0/8 -j ACCEPT 2>/dev/null || true
sudo iptables -t nat -D POSTROUTING -s 10.0.0.0/8 ! -d 10.0.0.0/8 -j MASQUERADE 2>/dev/null || true

echo "Cleanup complete. Update config and restart services."
```

### Impact on Running Containers

**Warning:** Migrating overlay configuration will:
- Disconnect all containers from the overlay network
- Break cross-node container communication
- Require containers to be restarted to get new IPs

For VPS containers, after migration:
```bash
# Stop and restart each VPS to get new overlay IPs
kohakuriver vps stop <task-id>
kohakuriver vps start <task-id>
```

---

## Getting Help

If issues persist:

1. Collect diagnostics:
   ```bash
   # On Host
   kohakuriver node overlay > overlay-status.txt
   ip link show > host-links.txt
   ip addr show > host-addrs.txt
   ip -d link show | grep -A 10 vxkr > vxlan-details.txt
   journalctl -u kohakuriver-host --since "1 hour ago" > host-logs.txt

   # On Runner
   ip link show > runner-links.txt
   docker network inspect kohakuriver-overlay > docker-net.txt 2>&1
   journalctl -u kohakuriver-runner --since "1 hour ago" > runner-logs.txt
   ```

2. Check Host and Runner config files match for:
   - `OVERLAY_VXLAN_ID`
   - `OVERLAY_VXLAN_PORT`
   - `OVERLAY_MTU`

3. Verify physical network connectivity between all nodes on UDP 4789.
