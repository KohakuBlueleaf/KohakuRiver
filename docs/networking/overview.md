# Networking Architecture Overview

For detailed concepts and traffic flow explanations, see [concept.md](concept.md).

## Networking Modes

KohakuRiver supports two networking modes:

| Mode | Cross-Node | Setup Required | Container IPs |
|------|------------|----------------|---------------|
| **Default** | ✗ Isolated | None | 172.30.x.x |
| **VXLAN Overlay** | ✓ Connected | Enable flag + Host IP | 10.X.x.x |

---

## Default Networking

Each Runner creates an isolated Docker bridge network:

```
┌──────────────────────────────────────────────────┐
│                   Runner Node                    │
│                                                  │
│    ┌────────────┐              ┌────────────┐    │
│    │ Container1 │              │ Container2 │    │
│    │ 172.30.0.2 │              │ 172.30.0.3 │    │
│    └─────┬──────┘              └──────┬─────┘    │
│          │                            │          │
│    ┌─────┴────────────────────────────┴─────┐    │
│    │          kohakuriver-net               │    │
│    │          172.30.0.0/16                 │    │
│    │          Gateway: 172.30.0.1           │    │
│    └────────────────────────────────────────┘    │
│                                                  │
└──────────────────────────────────────────────────┘
```

- **Subnet**: 172.30.0.0/16 (configurable)
- **Gateway**: 172.30.0.1 (Runner reachable here)
- **Cross-Node**: Not possible

---

## VXLAN Overlay Networking

### Hub-and-Spoke Topology

```
┌───────────────────────────────────────────────────────────────────────┐
│                        Local Network (Physical)                       │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                            Host                                 │  │
│  │                       (L3 Router)                               │  │
│  │                                                                 │  │
│  │     ┌──────────────┐              ┌──────────────┐              │  │
│  │     │    vxkr1     │              │    vxkr2     │              │  │
│  │     │ 10.1.0.254   │              │ 10.2.0.254   │              │  │
│  │     │  VNI=101     │              │  VNI=102     │              │  │
│  │     └──────┬───────┘              └───────┬──────┘              │  │
│  │            │                              │                     │  │
│  │     ┌──────┴──────────────────────────────┴──────┐              │  │
│  │     │              kohaku-host                   │              │  │
│  │     │              10.0.0.1/8                    │              │  │
│  │     │         (dummy interface)                  │              │  │
│  │     └────────────────────────────────────────────┘              │  │
│  │                                                                 │  │
│  └─────────────────────────┬─────────────────┬─────────────────────┘  │
│                            │                 │                        │
│                     VXLAN (UDP:4789)   VXLAN (UDP:4789)               │
│                            │                 │                        │
│  ┌─────────────────────────┴───┐   ┌────────┴─────────────────────┐   │
│  │          Runner1            │   │           Runner2            │   │
│  │                             │   │                              │   │
│  │  ┌───────────────────────┐  │   │  ┌───────────────────────┐   │   │
│  │  │        vxlan0         │  │   │  │        vxlan0         │   │   │
│  │  └───────────┬───────────┘  │   │  └───────────┬───────────┘   │   │
│  │              │              │   │              │               │   │
│  │  ┌───────────┴───────────┐  │   │  ┌───────────┴───────────┐   │   │
│  │  │    kohaku-overlay     │  │   │  │    kohaku-overlay     │   │   │
│  │  │    Gateway: 10.1.0.1  │  │   │  │   Gateway: 10.2.0.1   │   │   │
│  │  └───────────┬───────────┘  │   │  └───────────┬───────────┘   │   │
│  │              │              │   │              │               │   │
│  │  ┌───────────┴───────────┐  │   │  ┌───────────┴───────────┐   │   │
│  │  │     Containers        │  │   │  │      Containers       │   │   │
│  │  │  10.1.0.2 - 10.1.     │  │   │  │  10.2.0.2 - 10.2.     │   │   │
│  │  │     255.254           │  │   │  │      255.254          │   │   │
│  │  └───────────────────────┘  │   │  └───────────────────────┘   │   │
│  │                             │   │                              │   │
│  └─────────────────────────────┘   └──────────────────────────────┘   │
│                                                                       │
│ ════════════════════════════════════════════════════════════════════  │
│                              Internet                                 │
│            (Runners provide NAT access - bypasses Host)               │
└───────────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Location | IP Address | Purpose |
|-----------|----------|------------|---------|
| `kohaku-host` | Host | 10.0.0.1/8 | Containers reach Host services here |
| `vxkr{N}` | Host | 10.N.0.254/16 | VXLAN endpoint to Runner N |
| `vxlan0` | Runner | - | VXLAN endpoint to Host |
| `kohaku-overlay` | Runner | 10.N.0.1/16 | Bridge connecting containers |
| `kohakuriver-overlay` | Runner | - | Docker network on the bridge |

### IP Allocation

| Entity | IP Range |
|--------|----------|
| Host (for containers) | 10.0.0.1 |
| Host on Runner N's VXLAN | 10.N.0.254 |
| Runner N gateway | 10.N.0.1 |
| Runner N containers | 10.N.0.2 - 10.N.255.254 (excluding .254) |

- Each Runner gets a /16 subnet (~65,532 container IPs)
- Up to 255 Runners supported

### VXLAN Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Base VNI | 100 | VXLAN Network Identifier base |
| Runner VNI | 100 + runner_id | Unique VNI per runner |
| UDP Port | 4789 | Standard VXLAN port |
| MTU | 1450 | 1500 - 50 bytes overhead |

---

## Traffic Flows

### Cross-Node Container Traffic

```
Container A (10.1.0.2)  ──►  Runner1  ──VXLAN──►  Host  ──VXLAN──►  Runner2  ──►  Container B (10.2.0.5)
```

1. Container A sends packet to 10.2.0.5
2. Runner1 encapsulates in VXLAN (VNI=101) → Host
3. Host routes via kernel: 10.2.0.0/16 → vxkr2
4. Host encapsulates in VXLAN (VNI=102) → Runner2
5. Runner2 delivers to Container B

### Container to Internet

```
Container (10.1.0.2)  ──►  Runner1 (NAT)  ──►  Internet
                           (bypasses Host)
```

Each Runner provides internet access via NAT masquerading.

### Container to Host Services

```
Container (10.1.0.2)  ──►  Runner1  ──VXLAN──►  Host (10.0.0.1)
```

---

## Automatic Firewall Configuration

### iptables Rules (Host and Runner)

```bash
iptables -I FORWARD 1 -s 10.0.0.0/8 -j ACCEPT
iptables -I FORWARD 2 -d 10.0.0.0/8 -j ACCEPT
```

### NAT for Internet Access (Runner only)

```bash
iptables -t nat -A POSTROUTING -s 10.0.0.0/8 ! -d 10.0.0.0/8 -j MASQUERADE
```

### firewalld Integration

If firewalld is running, overlay interfaces are added to the trusted zone:
- **Host**: `vxkr1`, `vxkr2`, etc.
- **Runner**: `kohaku-overlay`, `vxlan0`

---

## State Management

- **Network interfaces are the source of truth** - no database needed
- Host recovers state from existing vxkr* interfaces on restart
- Runners reclaim their subnet by hostname or physical IP
- VXLAN tunnels persist through restarts

---

## Quick Comparison

| Feature | Default | Overlay |
|---------|---------|---------|
| Cross-node communication | ✗ | ✓ |
| Configuration required | None | Enable + Host IP |
| Network overhead | None | ~50 bytes/packet |
| Container IP scheme | 172.30.x.x | 10.X.x.x |
| Host reachable at | 172.30.0.1 | 10.0.0.1 |
| Internet access | Docker NAT | Runner NAT |
| Max runners | Unlimited | 255 |
