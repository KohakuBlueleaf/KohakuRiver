# VXLAN Overlay Network Setup Guide

This guide walks you through enabling cross-node container networking on an existing KohakuRiver cluster.

## Prerequisites

- Running KohakuRiver cluster (Host + Runners)
- Root/sudo access on Host and all Runners (for network interface creation)
- Network connectivity between Host and Runners on UDP port 4789

## Quick Start

The overlay network requires minimal configuration:

1. **Set `HOST_REACHABLE_ADDRESS`** in Host config to the Host's actual IP (not `127.0.0.1`)
2. **Open UDP port 4789** between Host and all Runners
3. **Set `OVERLAY_ENABLED = True`** in both Host and Runner configs
4. **Restart services**

KohakuRiver automatically handles:
- VXLAN tunnel creation
- Bridge and routing setup
- iptables rules for overlay traffic forwarding
- firewalld trusted zone configuration (if firewalld is running)

## Step 1: Configure Firewall (UDP Port 4789)

VXLAN uses UDP port 4789. Open this port between Host and all Runners.

### Using iptables

On **Host** and **all Runners**:

```bash
# Allow VXLAN traffic
sudo iptables -A INPUT -p udp --dport 4789 -j ACCEPT
sudo iptables -A OUTPUT -p udp --dport 4789 -j ACCEPT

# Save rules (varies by distribution)
# Debian/Ubuntu:
sudo netfilter-persistent save
# RHEL/CentOS:
sudo service iptables save
```

### Using firewalld

```bash
sudo firewall-cmd --permanent --add-port=4789/udp
sudo firewall-cmd --reload
```

### Using ufw

```bash
sudo ufw allow 4789/udp
```

### Cloud Provider Security Groups

If running on cloud VMs, ensure security groups/network policies allow:
- UDP port 4789 inbound/outbound between all cluster nodes

## Step 2: Update Host Config

Edit `~/.kohakuriver/host_config.py`:

```python
# IMPORTANT: Set this to the Host's actual reachable IP address
# This IP is used by Runners to establish VXLAN tunnels
HOST_REACHABLE_ADDRESS: str = "192.168.88.53"  # Change to your Host IP!

# =============================================================================
# Overlay Network Configuration (VXLAN Hub)
# =============================================================================

OVERLAY_ENABLED: bool = True
OVERLAY_BRIDGE_NAME: str = "kohaku-overlay"
OVERLAY_HOST_IP: str = "10.0.0.1"
OVERLAY_HOST_PREFIX: int = 8
OVERLAY_VXLAN_ID: int = 100
OVERLAY_VXLAN_PORT: int = 4789
OVERLAY_MTU: int = 1450
```

> **Important**: `HOST_REACHABLE_ADDRESS` must be set to the Host's actual IP address that Runners can reach. Do NOT use `127.0.0.1` - this will cause VXLAN tunnels to fail.

## Step 3: Update Runner Configs

Edit `~/.kohakuriver/runner_config.py` on **each Runner**:

```python
# =============================================================================
# Overlay Network Configuration (VXLAN Hub)
# =============================================================================

OVERLAY_ENABLED: bool = True
OVERLAY_NETWORK_NAME: str = "kohakuriver-overlay"
OVERLAY_VXLAN_ID: int = 100
OVERLAY_VXLAN_PORT: int = 4789
OVERLAY_MTU: int = 1450
```

## Step 4: Restart Services

```bash
# On Host
sudo systemctl restart kohakuriver-host

# On each Runner
sudo systemctl restart kohakuriver-runner
```

## Step 5: Verify Setup

### Check Overlay Status

```bash
kohakuriver node overlay
```

Expected output:

```
╭──────────────────── Overlay Network Status ────────────────────╮
│ Host IP: 10.0.0.1/8                                            │
│ Bridge: kohaku-overlay                                         │
│ Total Allocations: 2                                           │
│ Active: 2 | Inactive: 0                                        │
│ Available IDs: 253/255                                         │
╰────────────────────────────────────────────────────────────────╯

          Runner Allocations
┏━━━━━━━━━━━━━━━━┳━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Runner         ┃ ID ┃ Subnet        ┃ Physical IP   ┃ Status ┃
┡━━━━━━━━━━━━━━━━╇━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ runner1        │  1 │ 10.1.0.0/16   │ 192.168.88.20 │ Active │
│ runner2        │  2 │ 10.2.0.0/16   │ 192.168.88.77 │ Active │
└────────────────┴────┴───────────────┴───────────────┴────────┘
```

### Check Network Interfaces

On **Host**:

```bash
# Check VXLAN interfaces (one per runner)
ip link show | grep vxkr

# Check VXLAN details
ip -d link show vxkr1
```

On **Runners**:

```bash
# Check bridge and VXLAN
ip link show kohaku-overlay
ip link show vxlan0

# Check Docker network
docker network ls | grep overlay
```

### Test Cross-Node Connectivity

1. Create containers on different runners:

```bash
kohakuriver vps create --target runner1 --ssh-key none
kohakuriver vps create --target runner2 --ssh-key none
```

2. Connect to first container and test connectivity:

```bash
kohakuriver terminal <task_id_1>

# Inside container:
# Ping Host
ping 10.0.0.1

# Ping Runner gateway
ping 10.1.0.1

# Ping container on runner2 (check its IP first)
ping 10.2.0.x
```

## Automatic Firewall Configuration

KohakuRiver automatically configures firewall rules when the overlay network starts:

### iptables Rules

Both Host and Runner automatically add these rules to the FORWARD chain:

```bash
iptables -I FORWARD 1 -s 10.0.0.0/8 -j ACCEPT
iptables -I FORWARD 2 -d 10.0.0.0/8 -j ACCEPT
```

### firewalld Configuration

If firewalld is running, KohakuRiver automatically adds overlay interfaces to the trusted zone:

- **Host**: `vxkr1`, `vxkr2`, etc. (one per runner)
- **Runner**: `kohaku-overlay`, `vxlan0`

This is done non-permanently (runtime only), so it's automatically reconfigured on each service restart.

## Troubleshooting

### VXLAN Tunnel Not Working

Check VXLAN configuration:

```bash
# On Runner - verify remote points to Host IP
ip -d link show vxlan0 | grep -E "(remote|local)"

# On Host - verify remote points to Runner IP
ip -d link show vxkr1 | grep -E "(remote|local)"
```

If `remote` shows `127.0.0.1`, the `HOST_REACHABLE_ADDRESS` is not configured correctly.

### Cross-Node Ping Fails

1. Check if packets reach the Host:
   ```bash
   # On Host
   sudo tcpdump -i vxkr1 -n icmp
   ```

2. Check firewall rules:
   ```bash
   # On Host
   sudo iptables -L FORWARD -n -v --line-numbers | head -10
   ```

3. If using firewalld, verify interfaces are in trusted zone:
   ```bash
   sudo firewall-cmd --get-zone-of-interface=vxkr1
   ```

### Same-Node Container Communication Fails

Check bridge FDB entries:

```bash
bridge fdb show br kohaku-overlay | grep -v permanent
```

Container MACs should be associated with their veth interfaces, not vxlan0.

## Rollback

To disable overlay networking:

1. Set `OVERLAY_ENABLED = False` in Host and all Runner configs
2. Restart services
3. New containers will use `kohakuriver-net` (172.30.x.x)

Existing overlay containers need to be recreated to use the default network.
