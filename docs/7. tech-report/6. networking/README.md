# KohakuRiver Networking

Container and VM networking documentation for KohakuRiver clusters.

## Documents

| Document | Description |
|----------|-------------|
| [concept.md](concept.md) | In-depth explanation of overlay network design and traffic flows |
| [overview.md](overview.md) | Architecture summary and component reference |
| [overlay-setup.md](overlay-setup.md) | Step-by-step setup guide |
| [configuration.md](configuration.md) | Complete configuration reference |
| [public-ip-wireguard.md](public-ip-wireguard.md) | Assign real public IPs to containers via WireGuard tunnel to a BGP router |
| [vm-networking.md](vm-networking.md) | VM TAP networking, dual-mode bridge attachment, and IP allocation |
| [troubleshooting.md](troubleshooting.md) | Common issues and solutions |

## Quick Start

### Default Networking (No Setup Required)

Each Runner uses an isolated Docker bridge network:
- Network: `kohakuriver-net` (172.30.0.0/16)
- Containers on the same Runner can communicate
- Containers on different Runners are **isolated**

### Cross-Node Networking (VXLAN Overlay)

Enable container communication across all nodes with minimal setup:

1. **Set `HOST_REACHABLE_ADDRESS`** in Host config to Host's actual IP
2. **Open UDP port 4789** between Host and all Runners
3. **Set `OVERLAY_ENABLED = True`** in Host and Runner configs
4. **Restart** Host and Runners

KohakuRiver automatically handles VXLAN tunnels, IP allocation, routing, and firewall rules.

See [overlay-setup.md](overlay-setup.md) for detailed instructions.

### Multi-Overlay Networks (Optional)

Run multiple overlay networks simultaneously — each with its own subnet, VXLAN, and NAT policy. Containers can attach to one or more. Common use case: a private network for internal traffic + a public network with real public IPs via BGP/WireGuard.

See [configuration.md](configuration.md#multi-overlay-network-configuration) for the `OVERLAY_NETWORKS` config.

For assigning real public IPs to containers (via BGP + WireGuard tunnel), see [public-ip-wireguard.md](public-ip-wireguard.md).

## Architecture Summary

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Local Network (Physical)                       │
│                                                                      │
│  ┌───────────────┐     ┌───────────────────────┐     ┌────────────┐  │
│  │     Host      │     │       Runner1         │     │  Runner2   │  │
│  │  (L3 Router)  │     │                       │     │            │  │
│  │               │     │  ┌─────────┐ ┌─────┐  │     │ ┌────────┐ │  │
│  │  ┌─────────┐  │     │  │Container│ │ VM  │  │     │ │Container│ │  │
│  │  │  vxkr1  │◄─┼─────┼──┤10.1.0.2 │ │10.1.│  │     │ │10.2.0.2│ │  │
│  │  │  vxkr2  │◄─┼─────┼──┼─────────┼─┤0.5  │  │     │ │        │ │  │
│  │  └─────────┘  │     │  └───┬─────┘ └──┬──┘  │     │ └───┬────┘ │  │
│  └───────┬───────┘     │    veth       TAP     │     └─────│──────┘  │
│          │              │      │          │      │           │        │
│          │              │  ┌───┴──────────┴───┐  │           │        │
│          │              │  │  kohaku-overlay   │  │           │        │
│          │              │  └────────┬─────────┘  │           │        │
│          │              └──────────│───────────┘           │        │
│          │                         │ NAT                    │ NAT    │
│ ═════════╧═════════════════════════╧════════════════════════╧══════  │
│                          Internet                                    │
└──────────────────────────────────────────────────────────────────────┘
```

VMs attach to the same overlay bridge as containers via TAP devices, sharing the overlay IP space and cross-node routing. See [vm-networking.md](vm-networking.md) for details on TAP creation and dual-mode networking.

### Traffic Paths

| Traffic Type | Path |
|--------------|------|
| Container ↔ Container (same Runner) | Direct via local bridge |
| Container ↔ Container (cross-node) | Runner → VXLAN → **Host** → VXLAN → Runner |
| VM ↔ Container (same Runner, overlay) | Direct via shared `kohaku-overlay` bridge |
| VM ↔ Container (cross-node, overlay) | Runner → VXLAN → **Host** → VXLAN → Runner |
| Container → Internet | Runner → NAT → Internet (**bypasses Host**) |
| VM → Internet | Runner → NAT → Internet (**bypasses Host**) |
| Container → Host services | Runner → VXLAN → Host (10.0.0.1) |

### Key Points

- **Host as L3 Router**: Routes overlay traffic between Runners via VXLAN
- **Runner as NAT Gateway**: Each Runner provides internet access to its containers and VMs
- **Automatic Setup**: Firewall rules and NAT configured automatically
- **State Recovery**: VXLAN tunnels persist through restarts
- **VM TAP Networking**: VMs use TAP devices attached to the same bridge as containers, with IP allocation coordinated through the same pool
