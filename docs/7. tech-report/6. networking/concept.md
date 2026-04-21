# Overlay Network Concepts

## Motivation

### The Problem

In a typical KohakuRiver cluster, containers run on different Runner nodes. By default, each Runner has its own isolated Docker network (`kohakuriver-net` with subnet `172.30.0.0/16`). This creates a problem:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Local Network (e.g., 192.168.88.0/24)          │
│                                                                         │
│  ┌─────────────┐       ┌─────────────┐       ┌─────────────┐            │
│  │    Host     │       │   Runner1   │       │   Runner2   │            │
│  │192.168.88.53│       │192.168.88.20│       │192.168.88.77│            │
│  └─────────────┘       └──────┬──────┘       └──────┬──────┘            │
│                               │                     │                   │
│                        ┌──────┴──────┐       ┌──────┴──────┐            │
│                        │ Container A │       │ Container B │            │
│                        │ 172.30.0.2  │       │ 172.30.0.2  │  ← Same IP!│
│                        └─────────────┘       └─────────────┘            │
│                                                                         │
│                            ✗ Cannot communicate ✗                      │
└─────────────────────────────────────────────────────────────────────────┘
```

**Problems with isolated networks:**
- Containers on different Runners cannot communicate directly
- IP addresses can conflict (both runners use 172.30.0.0/16)
- No way for Container A to reach Container B without complex port mapping

### The Solution: VXLAN Overlay Network

The overlay network creates a unified virtual network spanning all nodes:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Local Network (e.g., 192.168.88.0/24)          │
│                                                                         │
│  ┌─────────────┐       ┌─────────────┐       ┌─────────────┐            │
│  │    Host     │       │   Runner1   │       │   Runner2   │            │
│  │192.168.88.53│       │192.168.88.20│       │192.168.88.77│            │
│  │             │       │             │       │             │            │
│  │ ┌─────────┐ │       │ ┌─────────┐ │       │ ┌─────────┐ │            │
│  │ │vxkr1    │◄├───────┼─┤ vxlan0  │ │       │ │ vxlan0  │ │            │
│  │ │vxkr2    │◄├───────┼─┼─────────┼─┼───────┼─┤         │ │            │
│  │ └─────────┘ │       │ └────┬────┘ │       │ └────┬────┘ │            │
│  └─────────────┘       └──────┼──────┘       └──────┼──────┘            │
│                               │                     │                   │
│                        ┌──────┴──────┐       ┌──────┴──────┐            │
│                        │ Container A │       │ Container B │            │
│                        │  10.1.0.2   │◄─────►│  10.2.0.2   │            │
│                        └─────────────┘       └─────────────┘            │
│                                                                         │
│                            ✓ Can communicate! ✓                        │
└─────────────────────────────────────────────────────────────────────────┘
```

**Benefits:**
- Each Runner gets a unique subnet (10.1.0.0/16, 10.2.0.0/16, etc.)
- Containers can communicate across nodes using overlay IPs
- Host is reachable at a consistent IP (10.0.0.1) from all containers

---

## Architecture

### Hub-and-Spoke L3 Routing

The overlay uses a **hub-and-spoke topology** with the Host as the central router:

```
                                    ┌─────────────────────┐
                                    │        Host         │
                                    │   (Central Router)  │
                                    │                     │
                                    │  ┌───────────────┐  │
                                    │  │  kohaku-host  │  │
                                    │  │   10.0.0.1/8  │  │
                                    │  └───────────────┘  │
                                    │                     │
                                    │  ┌─────┐   ┌─────┐  │
                                    │  │vxkr1│   │vxkr2│  │
                                    │  │10.1.│   │10.2.│  │
                                    │  │0.254│   │0.254│  │
                                    │  └──┬──┘   └──┬──┘  │
                                    └─────┼────────┼──────┘
                                          │        │
                          ┌───────────────┘        └───────────────┐
                          │ VXLAN (VNI=101)         VXLAN (VNI=102)│
                          │ UDP:4789                      UDP:4789 │
                          │                                        │
                    ┌─────┴─────┐                          ┌───────┴───┐
                    │  Runner1  │                          │  Runner2  │
                    │           │                          │           │
                    │ ┌───────┐ │                          │ ┌───────┐ │
                    │ │vxlan0 │ │                          │ │vxlan0 │ │
                    │ └───┬───┘ │                          │ └───┬───┘ │
                    │     │     │                          │     │     │
                    │ ┌───┴───┐ │                          │ ┌───┴───┐ │
                    │ │kohaku-│ │                          │ │kohaku-│ │
                    │ │overlay│ │                          │ │overlay│ │
                    │ │10.1.  │ │                          │ │10.2.  │ │
                    │ │ 0.1   │ │                          │ │ 0.1   │ │
                    │ └───┬───┘ │                          │ └───┬───┘ │
                    │     │     │                          │     │     │
                    │ ┌───┴───┐ │                          │ ┌───┴───┐ │
                    │ │Contai-│ │                          │ │Contai-│ │
                    │ │ners   │ │                          │ │ners   │ │
                    │ │10.1.  │ │                          │ │10.2.  │ │
                    │ │0.2-254│ │                          │ │0.2-254│ │
                    │ └───────┘ │                          │ └───────┘ │
                    └───────────┘                          └───────────┘
```

### Key Components

**Single-overlay mode** (legacy `OVERLAY_ENABLED` with no `OVERLAY_NETWORKS`):

| Component | Location | Purpose |
|-----------|----------|---------|
| `kohaku-host` | Host | Dummy interface with 10.0.0.1/8 for containers to reach Host |
| `vxkr{N}` | Host | VXLAN interface to Runner N, has IP 10.N.0.254/16 |
| `vxlan0` | Runner | VXLAN interface to Host |
| `kohaku-overlay` | Runner | Linux bridge connecting vxlan0 and containers |
| `kohakuriver-overlay` | Runner | Docker network using the bridge |

**Multi-overlay mode** (`OVERLAY_NETWORKS` list config) — each network gets its own set of interfaces named by network name and index:

| Component | Location | Example (first network "private", Runner 1) |
|-----------|----------|---------------------------------------------|
| `kohaku-host` | Host | Shared dummy interface (one for all networks) |
| `vx{net_idx}_{runner_id}` | Host | `vx0_1` — VXLAN prefix encodes network index in base36 |
| `vxlan-{name}` | Runner | `vxlan-private` (truncated to 15 chars) |
| `kohaku-{name}` | Runner | `kohaku-private` — Linux bridge |
| `kohakuriver-{name}` | Runner | `kohakuriver-private` — Docker network |

With two networks (e.g., `private` and `public`) and two runners, you get VXLAN devices `vx0_1`, `vx0_2` (private network, runners 1-2) and `vx1_1`, `vx1_2` (public network). VNIs are `vxlan_id_base + runner_id`, so each network needs a non-overlapping `vxlan_id_base`.

See [configuration.md](configuration.md#multi-overlay-network-configuration) for config details.

### IP Address Scheme

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Overlay Network: 10.0.0.0/8                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Host:         10.0.0.1/8  (on kohaku-host dummy interface)             │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ Runner 1 Subnet: 10.1.0.0/16                                    │   │
│   │   • Gateway (bridge):     10.1.0.1                              │   │
│   │   • Host reachable at:    10.1.0.254                            │   │
│   │   • Container IPs:        10.1.0.2 - 10.1.255.254               │   │
│   │                           (excluding 10.1.0.254)                │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ Runner 2 Subnet: 10.2.0.0/16                                    │   │
│   │   • Gateway (bridge):     10.2.0.1                              │   │
│   │   • Host reachable at:    10.2.0.254                            │   │
│   │   • Container IPs:        10.2.0.2 - 10.2.255.254               │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ... up to 255 Runners (10.255.0.0/16)                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Traffic Flows

### 1. Container to Container (Same Runner)

Traffic stays local on the Runner's bridge:

```
Container A (10.1.0.2)                    Container B (10.1.0.3)
       │                                         ▲
       │                                         │
       └────────► kohaku-overlay bridge ─────────┘
                    (10.1.0.1)
```

### 2. Container to Container (Different Runners)

Traffic goes through Host as L3 router:

```
Container A                                              Container B
(10.1.0.2)                                               (10.2.0.5)
    │                                                        ▲
    ▼                                                        │
┌────────┐    VXLAN     ┌────────┐     VXLAN     ┌──────────┐
│Runner1 │─────────────►│  Host  │──────────────►│ Runner2  │
│        │   VNI=101    │        │    VNI=102    │          │
└────────┘              └────────┘               └──────────┘
                             │
                     Kernel IP routing:
                     10.2.0.0/16 → vxkr2
```

**Step by step:**
1. Container A sends packet to 10.2.0.5
2. Runner1 bridge routes to gateway → VXLAN encapsulation → Host
3. Host receives on vxkr1 (10.1.0.254)
4. Host kernel routes: destination 10.2.0.0/16 is via vxkr2
5. Host sends via vxkr2 → VXLAN encapsulation → Runner2
6. Runner2 decapsulates, bridge delivers to Container B

### 3. Container to Host Services

Container reaches Host at 10.0.0.1:

```
Container (10.1.0.2)
    │
    │  dst: 10.0.0.1
    ▼
┌────────┐    VXLAN     ┌────────────────────┐
│Runner1 │─────────────►│       Host         │
│        │   VNI=101    │                    │
└────────┘              │  vxkr1 receives    │
                        │         │          │
                        │         ▼          │
                        │  kohaku-host       │
                        │  (10.0.0.1/8)      │
                        │         │          │
                        │         ▼          │
                        │  Local services    │
                        │  (SSH proxy, etc)  │
                        └────────────────────┘
```

### 4. Container to Internet (External Network)

Traffic goes directly through Runner's physical NIC (NOT through Host):

```
                                    ┌─────────────────┐
                                    │    Internet     │
                                    │  (External)     │
                                    └────────▲────────┘
                                             │
═══════════════════════════════════════════════════════════════
                         Local Network       │
                                             │ NAT (masquerade)
                                             │
┌────────┐                           ┌───────┴────────┐
│  Host  │                           │    Runner1     │
│        │   (not involved)          │                │
└────────┘                           │  Physical NIC  │
                                     │ 192.168.88.20  │
                                     └───────▲────────┘
                                             │
                                     ┌───────┴────────┐
                                     │   Container    │
                                     │   10.1.0.2     │
                                     │                │
                                     │ ping 8.8.8.8   │
                                     └────────────────┘
```

**Key point**: Each Runner provides internet access to its own containers via NAT. External traffic does NOT route through Host.

**NAT rule on Runner:**
```bash
iptables -t nat -A POSTROUTING -s 10.0.0.0/8 ! -d 10.0.0.0/8 -j MASQUERADE
```

This masquerades overlay traffic (10.0.0.0/8) going to non-overlay destinations.

---

## Multi-Overlay Networks

A KohakuRiver cluster can run **multiple overlay networks in parallel**, each with its own subnet, VXLAN tunnels, and NAT policy. Containers can attach to one or more networks simultaneously, giving them multiple IPs — one per attached network.

### Why Multi-Overlay?

Common scenarios:

- **Private + Public split**: one network with NATed private IPs (e.g., `10.128.0.0/12`) for internal traffic, and another with real public IPs (e.g., `163.227.172.128/26` via BGP/WireGuard) for inbound connections.
- **Tenant isolation**: separate networks for staging vs. production workloads sharing the same cluster.
- **Traffic policy separation**: e.g., one network bypasses NAT for performance-critical paths.

### Dual-NIC Container

A container attached to two networks gets two interfaces:

```
┌─────────────────────────────────────────────┐
│             Container                       │
│                                             │
│   eth0: 10.128.64.2 (private)               │
│     └── default gateway: 10.128.64.1        │
│     └── outbound → NAT → internet           │
│                                             │
│   eth1: 163.227.172.130 (public)            │
│     └── no default gateway                  │
│     └── inbound only (external reaches here)│
└─────────────────────────────────────────────┘
```

Behavior:
- **Outbound** (e.g., `apt install`, `docker pull`, `wget`): default route on eth0 → private gateway → Runner NAT → Internet. Traffic never touches the public network.
- **Inbound** (e.g., external SSH, HTTP to the container): reaches eth1 via the public overlay. The return path on the same connection goes out eth1 (kernel matches by connection tracking).

The first network in `network_names` is the primary and owns the default route. Additional networks only provide IP addresses for reachability.

### Attaching a Container to Multiple Networks

**CLI:**
```bash
kohakuriver task submit -n private -n public -- python server.py
kohakuriver vps create --network private --network public --ssh
```

**API:**
```json
{"network_names": ["private", "public"], ...}
```

Internally, the Runner runs `docker run --network kohakuriver-private ...` for the primary network, then `docker network connect kohakuriver-public <container>` to attach each additional network.

---

## Masquerade Modes

Each overlay network has a `masquerade` flag controlling how outbound traffic is NATed on the Runner.

### `masquerade: True` — Private Networks

Used for subnets that aren't routable on the internet (`10.x.x.x`, `192.168.x.x`, etc.).

```
Container (10.128.64.2) → Runner bridge (10.128.64.1)
                          ↓
                          MASQUERADE: src changed to Runner's IP
                          ↓
                          Runner's default NIC → Internet
```

Required because the internet doesn't route back to private IPs. NAT masquerade rewrites the source IP so responses return to the Runner, which reverses the NAT and forwards back to the container.

**iptables rule:**
```bash
iptables -t nat -A POSTROUTING -s 10.128.0.0/12 ! -d 10.128.0.0/12 -j MASQUERADE
```

### `masquerade: False` — Public Networks

Used for subnets that **are** routable on the internet (real public IPs via BGP, or any range with external return path).

```
Container (163.227.172.130) → Runner bridge (163.227.172.129)
                              ↓
                              No NAT — source IP preserved
                              ↓
                              Runner policy route: from public subnet → back to Host via VXLAN
                              ↓
                              Host → WireGuard → BGP router → Internet
```

NAT would break inbound connections: external users dial the container's public IP, but NATed responses would come back from the Runner's internal IP → mismatch → connection dropped.

**Policy routing on Runner** (auto-configured when `masquerade: False`):
```bash
# Default route for non-masquerade network: goes back to Host via VXLAN
ip route add default via <host_ip_on_runner_subnet> table <N>
ip rule add from <public_subnet> table <N>
```

This ensures container outbound traffic takes the path that matches the BGP return path, keeping the source IP legitimate.

See [public-ip-wireguard.md](public-ip-wireguard.md) for the full public-IP-via-BGP setup.

### Choosing the Right Mode

| Network Type | `masquerade` | Reason |
|--------------|--------------|--------|
| Internal RFC1918 (10.x, 172.16.x, 192.168.x) | `True` | Not routable on internet; NAT required for outbound |
| Real public IPs with BGP announcement | `False` | Routable; NAT would break inbound connection tracking |
| Carrier-grade NAT / translated ranges | Depends | If upstream handles NAT, use `False`; else `True` |

---

## VXLAN Encapsulation

VXLAN (Virtual Extensible LAN) encapsulates Layer 2 frames in UDP packets:

```
Original packet from container:
┌─────────────────────────────────────────────────────────┐
│ Ethernet │    IP Header     │  TCP/UDP  │    Payload    │
│  Header  │ src: 10.1.0.2    │  Header   │               │
│          │ dst: 10.2.0.5    │           │               │
└─────────────────────────────────────────────────────────┘

After VXLAN encapsulation:
┌────────────────────────────────────────────────────────────────────────┐
│ Outer    │ Outer IP Header  │  UDP   │ VXLAN │     Original Packet     │
│ Ethernet │ src:192.168.88.20│ Header │Header │   (as shown above)      │
│ Header   │ dst:192.168.88.53│dst:4789│VNI=101│                         │
└────────────────────────────────────────────────────────────────────────┘
           └─────────────────────────────────┘
                    ~50 bytes overhead
```

**VXLAN parameters:**
- **VNI (VXLAN Network Identifier)**: 100 + runner_id (e.g., 101, 102, ...)
- **UDP Port**: 4789 (standard VXLAN port)
- **MTU**: 1450 (1500 - 50 bytes overhead)

---

## Automatic Configuration

KohakuRiver automatically handles:

### On Host startup:
1. Enable IP forwarding (`net.ipv4.ip_forward=1`)
2. Create `kohaku-host` dummy interface with the host overlay IP
3. For each configured overlay network, recover existing VXLAN interfaces from previous run
4. Add iptables FORWARD rules for each overlay subnet
5. Add VXLAN interfaces to firewalld trusted zone (if firewalld running)

### On Runner registration:
1. For each overlay network, Host creates a VXLAN interface pointing to Runner
2. Runner creates VXLAN interface pointing to Host (one per overlay)
3. Runner creates bridge per overlay with the runner's gateway IP
4. Runner creates Docker network per overlay using the bridge
5. Runner adds iptables FORWARD rules per overlay CIDR
6. For overlays with `masquerade: True`, Runner adds NAT masquerade rule
7. For overlays with `masquerade: False`, Runner adds policy routing (see [Masquerade Modes](#masquerade-modes))
8. Runner adds interfaces to firewalld trusted zone (if running)

### Firewall rules added (per overlay subnet):

**FORWARD chain (Host and Runner):**
```bash
iptables -I FORWARD 1 -s <OVERLAY_CIDR> -j ACCEPT
iptables -I FORWARD 2 -d <OVERLAY_CIDR> -j ACCEPT
```

**NAT POSTROUTING (Runner only, `masquerade: True` networks):**
```bash
iptables -t nat -A POSTROUTING -s <OVERLAY_CIDR> ! -d <OVERLAY_CIDR> -j MASQUERADE
```

**Policy routing (Runner only, `masquerade: False` networks):**
```bash
ip route replace default via <host_ip_on_runner_subnet> table <N>
ip rule add from <OVERLAY_CIDR> table <N>
```

---

## State Recovery

The overlay network is designed for minimal persistent state:

### Network interfaces ARE the source of truth

- No database stores overlay allocations
- On Host restart, state is recovered from existing VXLAN interfaces (one network at a time)
- VNI encodes runner_id: `runner_id = VNI - vxlan_id_base`
- In multi-overlay, each network's VXLAN prefix (`vxkr`, `vx0`, `vx1`, ...) distinguishes them

### Host restart behavior:

1. For each configured overlay, Host scans for VXLAN interfaces matching that network's prefix
2. Extracts runner_id from interface name and VNI
3. Creates placeholder allocations (marked inactive)
4. When Runners reconnect, they reclaim their allocation by matching physical IP
5. VXLAN tunnels persist - running containers keep connectivity

### VXLAN config drift detection

If a VXLAN interface exists but its **VNI, remote IP, or local IP** differs from the current configuration (e.g., `HOST_REACHABLE_ADDRESS` changed), KohakuRiver automatically deletes and recreates the interface with the correct parameters. This handles the common case where the Host's reachable address changes and old VXLANs need to be refreshed.

### Runner restart behavior:

1. Runner re-registers with Host
2. Host returns same subnet (matched by hostname or physical IP)
3. Runner recreates bridge and Docker network if needed
4. Existing containers on overlay network continue working

---

## Comparison of Modes

| Aspect | Default (`kohakuriver-net`) | Single Overlay | Multi-Overlay |
|--------|---------------------------|----------------|---------------|
| Cross-node communication | ✗ Not possible | ✓ One shared network | ✓ Multiple networks |
| Container IP scheme | 172.30.x.x (conflicts possible) | 10.X.x.x (unique per runner) | One subnet per network (flexible) |
| Multiple NICs per container | ✗ | ✗ (one overlay only) | ✓ (attach to multiple) |
| Public IP support | ✗ | ✗ | ✓ (`masquerade: False` networks) |
| Internet access | Via Docker NAT | Via Runner NAT | Per-network (NAT or preserve) |
| Configuration | None | `OVERLAY_ENABLED` + subnet | `OVERLAY_NETWORKS` list |
| Max runners per network | Unlimited | Up to node-bits (63 default) | Up to node-bits per network |
| Network overhead | None | ~50 bytes/packet | ~50 bytes/packet (per VXLAN) |
| Requires root on Host | No | Yes (for VXLAN interfaces) | Yes |

**Upgrade path:** single-overlay is the default when you enable `OVERLAY_ENABLED` without `OVERLAY_NETWORKS`. To migrate to multi-overlay, add the `OVERLAY_NETWORKS` list — existing containers keep working under the synthesized `"default"` network name while you transition.
