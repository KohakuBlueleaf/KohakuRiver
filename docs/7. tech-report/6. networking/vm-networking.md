# VM Networking

## Motivation

Docker containers receive network connectivity automatically through Docker's built-in bridge driver. When a container joins a Docker network (e.g., `kohaku-overlay` or `kohakuriver-net`), Docker creates a veth pair, attaches one end to the bridge, and configures the container's network namespace. This is transparent to KohakuRiver.

Virtual machines do not have this luxury. A VM runs its own kernel and expects to see a real network interface -- typically a virtio NIC backed by a TAP device on the host. The TAP device must be explicitly created, attached to the correct bridge, and configured with an IP address that the VM's guest OS can use. KohakuRiver's `VMNetworkManager` handles this lifecycle.

### Key Differences from Container Networking

| Aspect | Docker Container | Virtual Machine |
|--------|-----------------|-----------------|
| Interface creation | Automatic (veth pair) | Manual (TAP device) |
| Bridge attachment | Docker daemon | VMNetworkManager via pyroute2 |
| IP assignment | Docker IPAM or overlay | VMNetworkManager + cloud-init |
| Guest configuration | Container inherits host DNS/routes | cloud-init `network-config` |
| Cleanup | Docker removes veth on stop | VMNetworkManager deletes TAP |

---

## Dual-Mode Architecture

VMNetworkManager detects the active networking mode at startup and configures VM networking accordingly. The two modes mirror the container networking modes described in [overview.md](overview.md), but use TAP devices instead of veth pairs.

### Mode Comparison

| Property | Overlay Mode | Standard Mode |
|----------|-------------|---------------|
| Config requirement | `OVERLAY_ENABLED=True` | `OVERLAY_ENABLED=False` (default) |
| Bridge used | `kohaku-overlay` | `kohaku-br0` (created by manager) |
| IP range | Runner's overlay subnet (10.X.0.0/16) | Local pool (10.200.0.0/24) |
| IP allocation | Host API (`IPReservationManager`) | Local sequential allocation |
| Gateway | Overlay gateway (e.g., 10.128.64.1) | 10.200.0.1 (bridge address) |
| Cross-node communication | Yes, via VXLAN | No, single-node only |
| Internet access | Runner NAT (same as containers) | iptables MASQUERADE on `kohaku-br0` |
| Runner URL from VM | `http://{overlay_gateway}:8001` | `http://10.200.0.1:8001` |

### Network Topology

```
OVERLAY MODE                                STANDARD MODE

┌──────────────────────────────┐            ┌──────────────────────────────┐
│           Runner Node        │            │           Runner Node        │
│                              │            │                              │
│  ┌──────────┐  ┌──────────┐  │            │  ┌──────────┐  ┌──────────┐  │
│  │   VM 1   │  │Container │  │            │  │   VM 1   │  │Container │  │
│  │10.1.0.5  │  │10.1.0.2  │  │            │  │10.200.0.2│  │172.30.0.2│  │
│  └────┬─────┘  └────┬─────┘  │            │  └────┬─────┘  └────┬─────┘  │
│    TAP│          veth│        │            │    TAP│          veth│        │
│       │              │        │            │       │              │        │
│  ┌────┴──────────────┴─────┐  │            │  ┌────┴─────┐  ┌────┴─────┐  │
│  │     kohaku-overlay      │  │            │  │kohaku-br0│  │kohakuriver│  │
│  │    (shared bridge)      │  │            │  │10.200.0.1│  │  -net    │  │
│  └───────────┬─────────────┘  │            │  └────┬─────┘  └────┬─────┘  │
│              │                │            │       │              │        │
│         ┌────┴─────┐         │            │    MASQUERADE     Docker NAT  │
│         │  vxlan0  │         │            │       │              │        │
│         └────┬─────┘         │            └───────┼──────────────┼────────┘
│              │               │                    │              │
└──────────────┼───────────────┘              ══════╧══════════════╧═══
               │                                        Internet
         VXLAN tunnel
               │
       ┌───────┴───────┐
       │     Host      │
       │  (L3 Router)  │
       └───────────────┘
```

In overlay mode, VMs and containers share the same bridge and the same IP space. A VM at `10.1.0.5` can reach a container at `10.2.0.3` on another Runner through the Host's VXLAN router, exactly as two containers would.

In standard mode, VMs live on a separate bridge (`kohaku-br0`) from Docker containers (`kohakuriver-net`). They cannot communicate with containers directly and are limited to the local node.

---

## VMNetworkManager Design

`VMNetworkManager` is a class instantiated once per Runner process. It manages the full lifecycle of VM network resources.

### Initialization (`setup()`)

On startup, the manager detects the networking mode:

1. Check `OVERLAY_ENABLED` in runner configuration
2. If overlay is enabled and the `kohaku-overlay` bridge exists:
   - Set mode to `"overlay"`
   - Read the overlay gateway and subnet from runner state
   - No bridge creation needed (overlay bridge already exists)
3. Otherwise:
   - Set mode to `"standard"`
   - Create the NAT bridge `kohaku-br0` if it does not exist
   - Assign `10.200.0.1/24` to the bridge
   - Enable IP forwarding (`net.ipv4.ip_forward = 1`)
   - Add iptables MASQUERADE rule for `10.200.0.0/24`

### Standard Mode Bridge Creation

```
# Equivalent operations performed via pyroute2:

ip link add kohaku-br0 type bridge
ip addr add 10.200.0.1/24 dev kohaku-br0
ip link set kohaku-br0 up
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -s 10.200.0.0/24 ! -d 10.200.0.0/24 -j MASQUERADE
```

---

## TAP Device Creation

Each VM requires a dedicated TAP device. The TAP is created using pyroute2's Netlink interface and attached to the appropriate bridge.

### Creation Steps

1. **Open a TAP file descriptor** with flags `IFF_TAP | IFF_NO_PI`:
   - `IFF_TAP` creates a Layer 2 (Ethernet frame) device, required for VM NICs
   - `IFF_NO_PI` disables the 4-byte packet information header, giving raw Ethernet frames
2. **Name the device** using the pattern `tap-{task_id_short}` (truncated to fit the 15-character Linux interface name limit)
3. **Set the bridge master** to either `kohaku-overlay` or `kohaku-br0`
4. **Bring the interface up**

### pyroute2 Operations

```python
from pyroute2 import IPRoute

ipr = IPRoute()

# 1. Create TAP device (via ioctl on /dev/net/tun)
tap_fd = os.open("/dev/net/tun", os.O_RDWR)
ifr = struct.pack("16sH", tap_name.encode(), IFF_TAP | IFF_NO_PI)
fcntl.ioctl(tap_fd, TUNSETIFF, ifr)

# 2. Attach TAP to bridge
tap_idx = ipr.link_lookup(ifname=tap_name)[0]
bridge_idx = ipr.link_lookup(ifname=bridge_name)[0]
ipr.link("set", index=tap_idx, master=bridge_idx)

# 3. Bring TAP up
ipr.link("set", index=tap_idx, state="up")
```

The TAP file descriptor is passed to the QEMU/KVM process, which uses it as the backend for the VM's virtio-net device.

---

## IP Allocation

### Overlay Mode

IP allocation follows the same path as Docker containers on the overlay network:

1. VMNetworkManager calls the Host's `IPReservationManager` API
2. Host allocates an IP from the Runner's overlay subnet (e.g., `10.1.0.5/16`)
3. A reservation token is returned for later release
4. The gateway is the overlay gateway address (e.g., `10.128.64.1`)

This ensures VMs and containers share a single coordinated IP space with no conflicts.

### Standard Mode

IP allocation is handled locally by the Runner:

1. VMNetworkManager maintains a simple counter starting at `10.200.0.2`
2. Each new VM gets the next available address in `10.200.0.0/24`
3. The gateway is always `10.200.0.1` (the `kohaku-br0` bridge address)
4. No coordination with the Host is needed

### Allocation Summary

```
Overlay Mode:                         Standard Mode:

  Host IPReservationManager             Local Pool
  ┌─────────────────────┐              ┌─────────────────────┐
  │ 10.1.0.1  [container]│              │ 10.200.0.1 [gateway]│
  │ 10.1.0.2  [container]│              │ 10.200.0.2 [vm-A]  │
  │ 10.1.0.3  [vm-A]    │              │ 10.200.0.3 [vm-B]  │
  │ 10.1.0.4  [vm-B]    │              │ 10.200.0.4 [free]  │
  │ ...                  │              │ ...                 │
  └─────────────────────┘              └─────────────────────┘
```

---

## Cloud-Init Network Configuration

VMs cannot configure their own network by inspecting the Docker bridge (as containers do). Instead, KohakuRiver injects network configuration via cloud-init's `network-config` (version 2, Netplan format).

### Generated Configuration

```yaml
network:
  version: 2
  ethernets:
    enp1s0:
      addresses:
        - 10.1.0.5/16          # Allocated VM IP with prefix length
      gateway4: 10.128.64.1    # Overlay gateway (or 10.200.0.1 in standard)
      nameservers:
        addresses:
          - 8.8.8.8
          - 8.8.4.4
      routes:
        - to: default
          via: 10.128.64.1
```

The configuration is written to a cloud-init ISO (NoCloud datasource) and attached to the VM as a CD-ROM drive at boot. The guest OS applies it on first boot.

### DNS Configuration

| Mode | DNS Servers | Source |
|------|------------|--------|
| Overlay | Host-configured or `8.8.8.8`, `8.8.4.4` | Runner config / defaults |
| Standard | `8.8.8.8`, `8.8.4.4` | Hardcoded defaults |

DNS servers are passed through cloud-init's `nameservers` block. The VM resolves external names through these servers, with traffic routed via the gateway and NATed to the internet.

---

## Runner URL Configuration

The VM agent inside the guest needs to communicate with the Runner's API (port 8001). The correct URL depends on the networking mode:

| Mode | `RUNNER_URL` | Why |
|------|-------------|-----|
| Overlay | `http://{overlay_gateway}:8001` | Gateway is the Runner's overlay-facing address |
| Standard | `http://10.200.0.1:8001` | Bridge address is the Runner's NAT bridge address |

This URL is injected into the VM via cloud-init user-data so the agent can register and report status on first boot.

---

## VMNetworkInfo Dataclass

Each call to `create_vm_network()` returns a `VMNetworkInfo` instance containing all parameters needed to launch the VM:

```python
@dataclass
class VMNetworkInfo:
    tap_device: str           # e.g., "tap-a3f8b2c1"
    vm_ip: str                # e.g., "10.1.0.5"
    gateway: str              # e.g., "10.128.64.1"
    bridge_name: str          # e.g., "kohaku-overlay"
    netmask: str              # e.g., "255.255.0.0"
    prefix_len: int           # e.g., 16
    dns_servers: list[str]    # e.g., ["8.8.8.8", "8.8.4.4"]
    mode: str                 # "overlay" or "standard"
    runner_url: str           # e.g., "http://10.128.64.1:8001"
    reservation_token: str    # Token for IP release (overlay only)
```

This dataclass is consumed by:
- **QEMU launcher**: Uses `tap_device` for the NIC backend
- **Cloud-init generator**: Uses `vm_ip`, `gateway`, `prefix_len`, `dns_servers`, `runner_url`
- **Cleanup handler**: Uses `tap_device` and `reservation_token`

---

## Cleanup Process

When a VM is stopped or killed, `cleanup_vm_network(task_id)` releases all network resources:

1. **Delete the TAP device**:
   ```python
   tap_idx = ipr.link_lookup(ifname=tap_name)[0]
   ipr.link("del", index=tap_idx)
   ```
2. **Close the TAP file descriptor** (if still open)
3. **Release the IP reservation**:
   - Overlay mode: Call Host API with the reservation token to free the IP
   - Standard mode: Return the address to the local pool

### Cleanup Order

```
VM shutdown signal
        │
        ▼
  Stop QEMU process
        │
        ▼
  Delete TAP device (pyroute2)
        │
        ▼
  Close TAP file descriptor
        │
        ▼
  Release IP reservation
  (overlay: Host API / standard: local pool)
        │
        ▼
  Remove task network state
```

Cleanup is idempotent. If the TAP device has already been removed (e.g., the Runner restarted), the delete operation is silently skipped. IP reservations in overlay mode have a TTL on the Host side, so leaked reservations are eventually reclaimed.

---

## Failure Handling

| Failure | Impact | Recovery |
|---------|--------|----------|
| TAP creation fails | VM cannot start | Task marked FAILED, no cleanup needed |
| Bridge does not exist | TAP cannot attach | Manager logs error, retries on next `setup()` |
| Host API unreachable (overlay) | No IP allocation | Task stays PENDING until Host recovers |
| IP pool exhausted (standard) | No free addresses | Task marked FAILED with descriptive error |
| TAP delete fails on cleanup | Orphaned interface | Next `setup()` scans for orphaned `tap-*` devices |

---

## Further Reading

- [overview.md](overview.md) -- Networking modes and bridge architecture
- [concept.md](concept.md) -- VXLAN overlay design and traffic routing
- [overlay-setup.md](overlay-setup.md) -- Enabling cross-node networking
- [configuration.md](configuration.md) -- All networking configuration options
