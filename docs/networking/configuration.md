# Networking Configuration Reference

Complete reference for all networking-related configuration options.

## Configuration Files

KohakuRiver uses KohakuEngine-style Python configuration files:

| File | Purpose |
|------|---------|
| `~/.kohakuriver/host_config.py` | Host server configuration |
| `~/.kohakuriver/runner_config.py` | Runner agent configuration |

---

## Host Configuration

### Critical Setting: HOST_REACHABLE_ADDRESS

**This is the most important setting for overlay networking.**

```python
# IMPORTANT: Set this to the Host's actual IP address that Runners can reach
# Do NOT use 127.0.0.1 - this will cause VXLAN tunnels to fail
HOST_REACHABLE_ADDRESS: str = "192.168.88.53"  # Your Host's IP!
```

This IP is used as the `local` address for VXLAN tunnels. If set incorrectly, Runners will try to connect to the wrong address.

### Default Network Settings

When overlay is disabled (default), the Host has no network-specific settings. Runners manage their own Docker bridge networks.

### Overlay Network Settings

Add these to `~/.kohakuriver/host_config.py`:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `HOST_REACHABLE_ADDRESS` | str | `"127.0.0.1"` | **Must set to Host's actual IP!** |
| `OVERLAY_ENABLED` | bool | `False` | Enable VXLAN overlay networking |
| `OVERLAY_BRIDGE_NAME` | str | `"kohaku-overlay"` | Name for VXLAN interfaces (prefix) |
| `OVERLAY_HOST_IP` | str | `"10.0.0.1"` | Host's IP on overlay network |
| `OVERLAY_HOST_PREFIX` | int | `8` | Network prefix for host IP |
| `OVERLAY_VXLAN_ID` | int | `100` | Base VXLAN ID (runners get 100+id) |
| `OVERLAY_VXLAN_PORT` | int | `4789` | UDP port for VXLAN traffic |
| `OVERLAY_MTU` | int | `1450` | MTU for overlay network |

### Host Config Example

```python
# =============================================================================
# CRITICAL: Host Reachable Address
# =============================================================================

# IMPORTANT: Set this to the Host's actual IP address that Runners can reach
# This is used for VXLAN tunnel local binding
# Do NOT use 127.0.0.1 or localhost - VXLAN tunnels will fail!
HOST_REACHABLE_ADDRESS: str = "192.168.88.53"

# =============================================================================
# Overlay Network Configuration
# =============================================================================

# Enable VXLAN overlay network for cross-node container communication
# When disabled, containers use isolated per-node bridge networks
OVERLAY_ENABLED: bool = True

# Bridge name (used for interface naming - vxkr1, vxkr2, etc.)
OVERLAY_BRIDGE_NAME: str = "kohaku-overlay"

# Host's IP address on the overlay network (containers reach Host here)
OVERLAY_HOST_IP: str = "10.0.0.1"

# Network prefix for Host's overlay IP (covers all runner subnets)
OVERLAY_HOST_PREFIX: int = 8

# Base VXLAN ID (each runner gets base_id + runner_id)
OVERLAY_VXLAN_ID: int = 100

# VXLAN UDP port (must be open in firewall between Host and Runners)
OVERLAY_VXLAN_PORT: int = 4789

# MTU for overlay network (1500 - 50 bytes VXLAN overhead)
OVERLAY_MTU: int = 1450
```

---

## Runner Configuration

### Default Network Settings

Add these to `~/.kohakuriver/runner_config.py` (used when overlay is disabled):

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `DOCKER_NETWORK_NAME` | str | `"kohakuriver-net"` | Docker network for containers |
| `DOCKER_NETWORK_SUBNET` | str | `"172.30.0.0/16"` | Subnet for default network |
| `DOCKER_NETWORK_GATEWAY` | str | `"172.30.0.1"` | Gateway (Runner reachable here) |

### Overlay Network Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `OVERLAY_ENABLED` | bool | `False` | Enable VXLAN overlay networking |
| `OVERLAY_NETWORK_NAME` | str | `"kohakuriver-overlay"` | Docker network for overlay |
| `OVERLAY_VXLAN_ID` | int | `100` | Base VXLAN ID (must match Host) |
| `OVERLAY_VXLAN_PORT` | int | `4789` | UDP port (must match Host) |
| `OVERLAY_MTU` | int | `1450` | MTU (must match Host) |

### Runner Config Example

```python
# =============================================================================
# Docker Network Configuration (Default - used when overlay disabled)
# =============================================================================

DOCKER_NETWORK_NAME: str = "kohakuriver-net"
DOCKER_NETWORK_SUBNET: str = "172.30.0.0/16"
DOCKER_NETWORK_GATEWAY: str = "172.30.0.1"

# =============================================================================
# Overlay Network Configuration
# =============================================================================

# Enable VXLAN overlay network for cross-node container communication
# Must match Host's OVERLAY_ENABLED setting
OVERLAY_ENABLED: bool = True

# Docker network name for overlay (used when overlay is enabled)
OVERLAY_NETWORK_NAME: str = "kohakuriver-overlay"

# Base VXLAN ID (must match Host's OVERLAY_VXLAN_ID)
OVERLAY_VXLAN_ID: int = 100

# VXLAN UDP port (must match Host's OVERLAY_VXLAN_PORT)
OVERLAY_VXLAN_PORT: int = 4789

# MTU for overlay network (must match Host's OVERLAY_MTU)
OVERLAY_MTU: int = 1450
```

---

## Settings That Must Match

These settings MUST be identical on Host and all Runners:

| Setting | Why |
|---------|-----|
| `OVERLAY_VXLAN_ID` | VXLAN tunnels won't connect if VNI base differs |
| `OVERLAY_VXLAN_PORT` | Packets won't reach correct port |
| `OVERLAY_MTU` | MTU mismatch causes fragmentation/drops |

---

## IP Address Allocation

### Overlay IP Scheme

| Entity | IP Range | Description |
|--------|----------|-------------|
| Host (dummy) | 10.0.0.1/8 | Consistent IP for containers to reach Host |
| Host on Runner 1's VXLAN | 10.1.0.254 | Host's IP on vxkr1 interface |
| Host on Runner N's VXLAN | 10.N.0.254 | Host's IP on vxkrN interface |
| Runner 1 gateway | 10.1.0.1 | Gateway on Runner 1's bridge |
| Runner 1 containers | 10.1.0.2 - 10.1.255.254 | Container IPs (excluding 10.1.0.254) |
| Runner N containers | 10.N.0.2 - 10.N.255.254 | Container IPs (excluding 10.N.0.254) |

Each runner gets:
- A /16 subnet (65,532 usable container IPs)
- Gateway at 10.X.0.1
- Host reachable at 10.X.0.254
- Containers from 10.X.0.2 to 10.X.255.254 (excluding 10.X.0.254)

### Runner ID Assignment

- Runner IDs range from 1-255 (max 255 runners)
- IDs are assigned in order on first registration
- **Preserved on reconnection**: Runner gets same ID/subnet when reconnecting
- **LRU cleanup**: Only freed when pool is exhausted (all 255 used)

### VXLAN ID Calculation

```
VXLAN_VNI = OVERLAY_VXLAN_ID + RUNNER_ID
```

Example with `OVERLAY_VXLAN_ID = 100`:
- Runner 1: VNI 101
- Runner 2: VNI 102
- Runner N: VNI 100+N

---

## Network Requirements

### Firewall Rules (Manual)

VXLAN uses UDP port 4789. This must be open between Host and all Runners:

**iptables:**
```bash
sudo iptables -A INPUT -p udp --dport 4789 -j ACCEPT
sudo iptables -A OUTPUT -p udp --dport 4789 -j ACCEPT
```

**firewalld:**
```bash
sudo firewall-cmd --permanent --add-port=4789/udp
sudo firewall-cmd --reload
```

**ufw:**
```bash
sudo ufw allow 4789/udp
```

**Cloud Security Groups:**
- Allow UDP 4789 inbound/outbound between all cluster nodes

### Automatic Firewall Configuration

KohakuRiver automatically configures these rules when overlay starts:

**iptables FORWARD (on Host and Runner):**
```bash
iptables -I FORWARD 1 -s 10.0.0.0/8 -j ACCEPT
iptables -I FORWARD 2 -d 10.0.0.0/8 -j ACCEPT
```

**iptables NAT (on Runner only):**
```bash
iptables -t nat -A POSTROUTING -s 10.0.0.0/8 ! -d 10.0.0.0/8 -j MASQUERADE
```
This enables containers to access external networks (internet).

**firewalld (if running):**
- Host: `vxkr*` interfaces added to trusted zone
- Runner: `kohaku-overlay`, `vxlan0` added to trusted zone

This is done non-permanently, so rules are re-applied on each service restart.

### Bandwidth Overhead

VXLAN adds ~50 bytes per packet:
- 8 bytes VXLAN header
- 8 bytes UDP header
- 20 bytes outer IP header
- 14 bytes outer Ethernet header

For high-throughput workloads with jumbo frames:
```python
# If physical network supports MTU 9000
OVERLAY_MTU: int = 8950
```

### Latency

VXLAN adds minimal latency (<1ms typically):
- Encapsulation/decapsulation happens in kernel
- Traffic routes through Host via kernel IP forwarding

For latency-sensitive workloads:
- Place Host on same switch as Runners
- Ensure low-latency network between nodes

---

## Runtime Behavior

### Network Selection

Containers automatically use the correct network:

| Overlay Enabled | Overlay Configured | Network Used |
|-----------------|-------------------|--------------|
| False | - | `kohakuriver-net` (172.30.x.x) |
| True | No (failed setup) | `kohakuriver-net` (172.30.x.x) |
| True | Yes | `kohakuriver-overlay` (10.X.x.x) |

### Gateway Selection

| Mode | Gateway IP | Used For |
|------|------------|----------|
| Default | 172.30.0.1 | Container → Runner communication |
| Overlay | 10.X.0.1 | Container → Runner (via bridge) |
| Overlay | 10.0.0.1 | Container → Host (for tunnel-client) |

---

## Checking Status

### CLI

```bash
# View overlay network status
kohakuriver node overlay

# View specific runner's allocation
kohakuriver node overlay | grep runner-name
```

### Host Interfaces

```bash
# Check host dummy interface
ip link show kohaku-host
ip addr show kohaku-host

# List VXLAN interfaces (one per runner)
ip link show | grep vxkr

# Check specific VXLAN details
ip -d link show vxkr1
```

### Runner Interfaces

```bash
# Check overlay bridge and VXLAN
ip link show kohaku-overlay
ip link show vxlan0

# Check Docker network
docker network ls | grep overlay
docker network inspect kohakuriver-overlay
```

---

## Advanced Configuration

### Custom IP Scheme

To use a different IP scheme (e.g., 172.16.x.x):

**Host:**
```python
OVERLAY_HOST_IP: str = "172.16.0.1"
OVERLAY_HOST_PREFIX: int = 12  # Covers 172.16.0.0/12
```

Note: The runner subnet calculation (10.{runner_id}.0.0/16) is currently hardcoded. Custom schemes require code changes.

### High Availability Considerations

The current design uses Host as single hub:
- Host failure breaks cross-node container communication
- Containers on same runner can still communicate
- Runner → Host connectivity required for new allocations

For HA requirements, consider:
- Running Host on highly available infrastructure
- Fast Host restart (state recovered from interfaces)
