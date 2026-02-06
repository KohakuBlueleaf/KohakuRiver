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
| `OVERLAY_SUBNET` | str | `"10.128.0.0/12/6/14"` | Subnet configuration (see below) |
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

# Overlay subnet configuration
# Format: BASE_IP/NETWORK_PREFIX/NODE_BITS/SUBNET_BITS (must sum to 32)
# Default uses 10.128-143.x.x range to avoid conflicts with common networks
OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"

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
| `OVERLAY_SUBNET` | str | `"10.128.0.0/12/6/14"` | Subnet config (must match Host) |
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

# Overlay subnet configuration (must match Host's OVERLAY_SUBNET)
# Format: BASE_IP/NETWORK_PREFIX/NODE_BITS/SUBNET_BITS (must sum to 32)
OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"

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
| `OVERLAY_SUBNET` | IP addressing must be consistent across cluster |
| `OVERLAY_VXLAN_ID` | VXLAN tunnels won't connect if VNI base differs |
| `OVERLAY_VXLAN_PORT` | Packets won't reach correct port |
| `OVERLAY_MTU` | MTU mismatch causes fragmentation/drops |

---

## IP Address Allocation

### OVERLAY_SUBNET Format

The `OVERLAY_SUBNET` setting controls how IPs are allocated:

```
BASE_IP/NETWORK_PREFIX/NODE_BITS/SUBNET_BITS
```

- **NETWORK_PREFIX + NODE_BITS + SUBNET_BITS = 32** (must sum to 32)
- **NETWORK_PREFIX**: Fixed bits defining the overlay network
- **NODE_BITS**: Bits for runner/node identification (determines max runners)
- **SUBNET_BITS**: Bits for container IPs within each runner

### Default: `10.128.0.0/12/6/14`

Uses the 10.128.x.x - 10.143.x.x range to avoid conflicts with common private networks.

| Entity | IP Range | Description |
|--------|----------|-------------|
| Network range | 10.128.0.0 - 10.143.255.255 | /12 prefix |
| Host (dummy) | 10.128.0.1/12 | Consistent IP for containers to reach Host |
| Max runners | 63 | 6 bits = 2^6 - 1 |
| IPs per runner | 16,380 | 14 bits = 2^14 - 4 reserved |
| Runner 1 subnet | 10.128.64.0/18 | gateway 10.128.64.1, host 10.128.64.254 |
| Runner 2 subnet | 10.128.128.0/18 | gateway 10.128.128.1, host 10.128.128.254 |

Each runner gets:
- A /18 subnet (~16,380 usable container IPs)
- Gateway at first IP + 1 (e.g., 10.128.64.1)
- Host reachable at .254 offset (e.g., 10.128.64.254)

### Alternative: `10.0.0.0/8/8/16`

Full 10.x.x.x range with more runners and IPs:

| Entity | IP Range | Description |
|--------|----------|-------------|
| Network range | 10.0.0.0 - 10.255.255.255 | /8 prefix |
| Max runners | 255 | 8 bits = 2^8 - 1 |
| IPs per runner | 65,532 | 16 bits = 2^16 - 4 reserved |
| Host | 10.0.0.1 | First IP in network |
| Runner 1 subnet | 10.1.0.0/16 | gateway 10.1.0.1, host 10.1.0.254 |
| Runner N subnet | 10.N.0.0/16 | gateway 10.N.0.1, host 10.N.0.254 |

### Runner ID Assignment

- Runner IDs range from 1 to max_runners (based on NODE_BITS)
- Default max: 63 runners (6 bits = 2^6 - 1)
- IDs are assigned in order on first registration
- **Preserved on reconnection**: Runner gets same ID/subnet when reconnecting
- **LRU cleanup**: Only freed when pool is exhausted

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

KohakuRiver automatically configures these rules when overlay starts.
The `OVERLAY_CIDR` is derived from `OVERLAY_SUBNET` (e.g., `10.0.0.0/8` for default).

**iptables FORWARD (on Host and Runner):**
```bash
iptables -I FORWARD 1 -s OVERLAY_CIDR -j ACCEPT
iptables -I FORWARD 2 -d OVERLAY_CIDR -j ACCEPT
```

**iptables NAT (on Runner only):**
```bash
iptables -t nat -A POSTROUTING -s OVERLAY_CIDR ! -d OVERLAY_CIDR -j MASQUERADE
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

Use `OVERLAY_SUBNET` to customize the IP addressing scheme. The format is:
```
BASE_IP/NETWORK_PREFIX/NODE_BITS/SUBNET_BITS
```

**Example: Use 172.16.x.x range:**
```python
# Host and Runner config (must match!)
OVERLAY_SUBNET: str = "172.16.0.0/12/8/12"
```

This gives:
- Network: 172.16.0.0/12 (172.16.0.0 - 172.31.255.255)
- Max runners: 255 (8 bits)
- IPs per runner: 4,092 (12 bits)
- Host: 172.16.0.1
- Runner 1: 172.16.16.0/20, gateway 172.16.16.1

**Example: Smaller network for testing:**
```python
OVERLAY_SUBNET: str = "192.168.0.0/16/8/8"
```

This gives:
- Network: 192.168.0.0/16 (192.168.0.0 - 192.168.255.255)
- Max runners: 255 (8 bits)
- IPs per runner: 252 (8 bits)
- Host: 192.168.0.1
- Runner 1: 192.168.1.0/24, gateway 192.168.1.1

### High Availability Considerations

The current design uses Host as single hub:
- Host failure breaks cross-node container communication
- Containers on same runner can still communicate
- Runner → Host connectivity required for new allocations

For HA requirements, consider:
- Running Host on highly available infrastructure
- Fast Host restart (state recovered from interfaces)
