---
title: Overlay Network
description: Setting up the VXLAN overlay network for cross-node container and VM communication.
icon: i-carbon-network-overlay
---

# Overlay Network

KohakuRiver includes an optional VXLAN overlay network that enables containers and VMs on different nodes to communicate directly using private IP addresses.

## How It Works

The overlay uses a hub-and-spoke L3 routed topology:

1. The **host** acts as the central router with a bridge interface
2. Each **runner** gets a unique VXLAN tunnel to the host and its own subnet
3. **Containers and VMs** on each runner are connected to a bridge that routes through the overlay

```
              Hub-and-Spoke VXLAN Topology
              ────────────────────────────

                ┌──────────────────────┐
                │        Host          │
                │                      │
                │  kohaku-overlay      │
                │  bridge: 10.128.0.1  │
                └──────┬───────┬───────┘
                       │       │
           VXLAN 101   │       │  VXLAN 102
           UDP :4789   │       │  UDP :4789
                       │       │
         ┌─────────────▼─┐   ┌─▼───────────────┐
         │   Runner 1    │   │   Runner 2       │
         │               │   │                  │
         │ 10.128.0.0/14 │   │  10.132.0.0/14   │
         │               │   │                  │
         │ ┌───────────┐ │   │  ┌───────────┐   │
         │ │ Docker Net │ │   │  │ Docker Net │  │
         │ └──┬─────┬──┘ │   │  └─────┬─────┘   │
         │    │     │     │   │        │         │
         │ ┌──▼┐  ┌▼──┐  │   │     ┌──▼──┐      │
         │ │C1 │  │C2 │  │   │     │ C3  │      │
         │ │.2 │  │.3 │  │   │     │ .2  │      │
         │ └───┘  └───┘  │   │     └─────┘      │
         └────────────────┘   └──────────────────┘

  Traffic between C1 (10.128.0.2) and C3 (10.132.0.2)
  flows: C1 -> Runner 1 -> VXLAN -> Host -> VXLAN -> Runner 2 -> C3
```

## Enabling the Overlay

### Host Configuration

```python
# In host_config.py
OVERLAY_ENABLED: bool = True
OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"
OVERLAY_VXLAN_ID: int = 100
OVERLAY_VXLAN_PORT: int = 4789
OVERLAY_MTU: int = 1450
```

### Runner Configuration

```python
# In runner_config.py (must match host settings)
OVERLAY_ENABLED: bool = True
OVERLAY_SUBNET: str = "10.128.0.0/12/6/14"
OVERLAY_NETWORK_NAME: str = "kohakuriver-overlay"
OVERLAY_VXLAN_ID: int = 100
OVERLAY_VXLAN_PORT: int = 4789
OVERLAY_MTU: int = 1450
```

## Subnet Configuration Format

The `OVERLAY_SUBNET` uses the format `BASE_IP/NETWORK_PREFIX/NODE_BITS/SUBNET_BITS`:

- `NETWORK_PREFIX` + `NODE_BITS` + `SUBNET_BITS` must equal 32
- `NODE_BITS` determines maximum number of runners (2^NODE_BITS - 1)
- `SUBNET_BITS` determines IPs per runner (2^SUBNET_BITS - 2)

```
  OVERLAY_SUBNET format: BASE_IP / NETWORK_PREFIX / NODE_BITS / SUBNET_BITS
  Example:               10.128.0.0 /  12         /    6     /    14

  ┌──────────────────────────────────────────┐
  │         32-bit IPv4 address              │
  ├──────────────┬──────────┬────────────────┤
  │ NETWORK_PREFIX│NODE_BITS│  SUBNET_BITS   │
  │   (12 bits)  │(6 bits) │  (14 bits)      │
  ├──────────────┼──────────┼────────────────┤
  │  10.128.x.x  │ 0 - 63  │  0 - 16383      │
  │  (fixed)     │(runner#) │  (host IPs)    │
  └──────────────┴──────────┴────────────────┘
```

### Default: `10.128.0.0/12/6/14`

- Range: `10.128.0.0` to `10.191.255.255`
- Max runners: 63
- IPs per runner: ~16,382
- Avoids common `10.0.x.x` ranges

### Alternative: `10.0.0.0/8/8/16`

- Range: full `10.0.0.0/8`
- Max runners: 255
- IPs per runner: ~65,534
- May conflict with existing `10.x.x.x` networks

## Firewall Requirements

Open UDP port 4789 between host and all runners:

```bash
# On all nodes
sudo ufw allow 4789/udp
```

## Managing the Overlay

### Check Overlay Status

```bash
kohakuriver node overlay
```

Shows subnet configuration, host IP, allocations, and active/inactive runner status.

### Release a Runner's Allocation

```bash
kohakuriver node overlay-release <runner-hostname>
```

Disconnects a runner from the overlay. Warning: running containers may lose connectivity.

### Cleanup Inactive Allocations

```bash
kohakuriver node overlay-cleanup
```

Removes VXLAN tunnels for runners that are no longer active.

## IP Reservation

The overlay network supports IP reservation for distributed training scenarios where you need to know a container's IP before launching it.

```bash
# Reserve an IP
kohakuriver node ip-reserve <runner-name> --ttl 300

# Use the token when submitting a task
kohakuriver task submit --ip-token TOKEN -t <runner> -- python train.py

# List reservations
kohakuriver node ip-list

# Release a reservation
kohakuriver node ip-release <token>
```

## Troubleshooting

### Cleanup Scripts

If overlay state becomes inconsistent, use the cleanup scripts:

```bash
# On the host
scripts/cleanup-overlay-host.sh

# On runners
scripts/cleanup-overlay-runner.sh
```

These remove VXLAN interfaces and bridges created by KohakuRiver.
