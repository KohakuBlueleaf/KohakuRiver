# KohakuRiver Networking

Container networking documentation for KohakuRiver clusters.

## Documents

| Document | Description |
|----------|-------------|
| [concept.md](concept.md) | In-depth explanation of overlay network design and traffic flows |
| [overview.md](overview.md) | Architecture summary and component reference |
| [overlay-setup.md](overlay-setup.md) | Step-by-step setup guide |
| [configuration.md](configuration.md) | Complete configuration reference |
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

## Architecture Summary

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Local Network (Physical)                       │
│                                                                      │
│  ┌───────────────┐     ┌───────────────┐     ┌───────────────┐       │
│  │     Host      │     │    Runner1    │     │    Runner2    │       │
│  │  (L3 Router)  │     │               │     │               │       │
│  │               │     │  ┌─────────┐  │     │  ┌─────────┐  │       │
│  │  ┌─────────┐  │     │  │Container│  │     │  │Container│  │       │
│  │  │  vxkr1  │◄─┼─────┼──┤10.1.x.x │  │     │  │10.2.x.x │  │       │
│  │  │  vxkr2  │◄─┼─────┼──┼─────────┼──┼─────┼──┤         │  │       │
│  │  └─────────┘  │     │  └────┬────┘  │     │  └────┬────┘  │       │
│  └───────┬───────┘     └───────│───────┘     └───────│───────┘       │
│          │                     │                     │               │
│          │                     │ NAT                 │ NAT           │
│ ═════════╧═════════════════════╧═════════════════════╧═════════════  │
│                          Internet                                    │
└──────────────────────────────────────────────────────────────────────┘
```

### Traffic Paths

| Traffic Type | Path |
|--------------|------|
| Container ↔ Container (same Runner) | Direct via local bridge |
| Container ↔ Container (cross-node) | Runner → VXLAN → **Host** → VXLAN → Runner |
| Container → Internet | Runner → NAT → Internet (**bypasses Host**) |
| Container → Host services | Runner → VXLAN → Host (10.0.0.1) |

### Key Points

- **Host as L3 Router**: Routes overlay traffic between Runners via VXLAN
- **Runner as NAT Gateway**: Each Runner provides internet access to its containers
- **Automatic Setup**: Firewall rules and NAT configured automatically
- **State Recovery**: VXLAN tunnels persist through restarts
