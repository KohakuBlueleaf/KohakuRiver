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

| Component | Location | Purpose |
|-----------|----------|---------|
| `kohaku-host` | Host | Dummy interface with 10.0.0.1/8 for containers to reach Host |
| `vxkr{N}` | Host | VXLAN interface to Runner N, has IP 10.N.0.254/16 |
| `vxlan0` | Runner | VXLAN interface to Host |
| `kohaku-overlay` | Runner | Linux bridge connecting vxlan0 and containers |
| `kohakuriver-overlay` | Runner | Docker network using the bridge |

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
2. Create `kohaku-host` dummy interface with 10.0.0.1/8
3. Recover existing vxkr* interfaces from previous run
4. Add iptables FORWARD rules for overlay traffic
5. Add vxkr* interfaces to firewalld trusted zone (if firewalld running)

### On Runner registration:
1. Host creates vxkr{N} interface with IP 10.N.0.254/16
2. Runner creates vxlan0 interface pointing to Host
3. Runner creates kohaku-overlay bridge with gateway 10.N.0.1
4. Runner creates Docker network using the bridge
5. Runner adds iptables FORWARD rules
6. Runner adds NAT masquerade rule for internet access
7. Runner adds interfaces to firewalld trusted zone (if running)

### Firewall rules added:

**FORWARD chain (Host and Runner):**
```bash
iptables -I FORWARD 1 -s 10.0.0.0/8 -j ACCEPT
iptables -I FORWARD 2 -d 10.0.0.0/8 -j ACCEPT
```

**NAT POSTROUTING (Runner only):**
```bash
iptables -t nat -A POSTROUTING -s 10.0.0.0/8 ! -d 10.0.0.0/8 -j MASQUERADE
```

---

## State Recovery

The overlay network is designed for minimal persistent state:

### Network interfaces ARE the source of truth

- No database stores overlay allocations
- On Host restart, state is recovered from existing vxkr* interfaces
- VNI encodes runner_id: `runner_id = VNI - base_vxlan_id`

### Host restart behavior:

1. Host scans for existing vxkr* interfaces
2. Extracts runner_id from interface name and VNI
3. Creates placeholder allocations (marked inactive)
4. When Runners reconnect, they reclaim their allocation by matching physical IP
5. VXLAN tunnels persist - running containers keep connectivity

### Runner restart behavior:

1. Runner re-registers with Host
2. Host returns same subnet (matched by hostname or physical IP)
3. Runner recreates bridge and Docker network if needed
4. Existing containers on overlay network continue working

---

## Comparison with Default Networking

| Aspect | Default (`kohakuriver-net`) | Overlay (`kohakuriver-overlay`) |
|--------|---------------------------|--------------------------------|
| Cross-node communication | ✗ Not possible | ✓ Full connectivity |
| Container IP scheme | 172.30.x.x (conflicts possible) | 10.X.x.x (unique per runner) |
| Host reachable at | 172.30.0.1 (runner gateway) | 10.0.0.1 (consistent) |
| Internet access | Via Docker NAT | Via Runner NAT |
| Configuration | None required | Enable flag + HOST_REACHABLE_ADDRESS |
| Max runners | Unlimited | 255 |
| Network overhead | None | ~50 bytes/packet |
| Requires root on Host | No | Yes (for VXLAN interfaces) |
