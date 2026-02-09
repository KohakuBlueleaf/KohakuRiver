---
title: Overlay Network Management
description: Managing the VXLAN overlay network for container and VM connectivity.
icon: i-carbon-network-overlay
---

# Overlay Network Management

The VXLAN overlay network provides L3 connectivity between containers and VMs across all nodes in the cluster. The host acts as the central router in a hub-and-spoke topology.

## Architecture

```
                 Hub-and-Spoke Overlay Topology
                 ──────────────────────────────

  ┌────────────────────────────────────────────────────┐
  │               Host (Central Router)                │
  │                                                    │
  │   VXLAN Interface: 10.128.0.1                      │
  │   kohaku-overlay bridge                            │
  │        │                        │                  │
  │   ┌────┴───────┐         ┌──────┴──────┐           │
  │   │ VXLAN tun  │         │ VXLAN tun   │           │
  │   │  -> Node 1 │         │  -> Node 2  │           │
  │   └────┬───────┘         └──────┬──────┘           │
  └────────┼────────────────────────┼──────────────────┘
           │  UDP :4789             │  UDP :4789
           │                        │
  ┌────────▼─────────────┐  ┌───────▼─────────────────┐
  │  Runner Node 1       │  │  Runner Node 2          │
  │  VXLAN Agent         │  │  VXLAN Agent            │
  │  Subnet: 10.128.0/14 │  │  Subnet: 10.132.0/14   │
  │                      │  │                         │
  │  ┌────────────────┐  │  │  ┌────────────────────┐ │
  │  │  Docker Bridge  │  │  │  │  Docker Bridge      │ │
  │  │ (kohaku-overlay)│  │  │  │ (kohaku-overlay)    │ │
  │  └──┬─────────┬───┘  │  │  └──┬──────────┬──────┘ │
  │     │         │       │  │     │          │        │
  │  ┌──▼───┐ ┌──▼───┐   │  │  ┌──▼───┐  ┌───▼───┐   │
  │  │ C:A  │ │ C:B  │   │  │  │ C:C  │  │ VM:D  │   │
  │  │.0.2  │ │.0.3  │   │  │  │.0.2  │  │.0.10  │   │
  │  └──────┘ └──────┘   │  │  └──────┘  └───────┘   │
  └───────────────────────┘  └─────────────────────────┘
```

Each runner node gets a dedicated subnet from the overlay range. The host routes traffic between node subnets.

## Enabling the Overlay

### Host Configuration

```python
# host_config.py
OVERLAY_ENABLED = True
OVERLAY_SUBNET = "10.128.0.0/12/6/14"
```

### Runner Configuration

```python
# runner_config.py
OVERLAY_ENABLED = True
OVERLAY_SUBNET = "10.128.0.0/12/6/14"  # Must match host
OVERLAY_NETWORK_NAME = "kohaku-overlay"
OVERLAY_VXLAN_ID = 100
OVERLAY_VXLAN_PORT = 4789
OVERLAY_MTU = 1450
```

The host assigns each runner a unique subnet when it registers.

## Checking Overlay Status

### Per Node

```bash
kohakuriver node overlay <hostname>
```

Shows:

- Assigned subnet
- VXLAN interface status
- Connected containers and their IPs

### All Nodes

The cluster summary includes overlay status:

```bash
kohakuriver node summary
```

## IP Management

### Container IPs

Containers on the overlay network automatically receive IPs from their node's subnet. The runner's Docker network is configured to use the overlay subnet.

### IP Reservation

For distributed training, reserve IPs before launching tasks:

```bash
# Reserve an IP
kohakuriver node ip-reserve <hostname> --ttl 300

# View reservations
kohakuriver node ip-list <hostname>

# Check available IPs
kohakuriver node ip-available <hostname>

# Release a reservation
kohakuriver node ip-release <hostname> --token <token>

# Get reservation info
kohakuriver node ip-info <hostname> --token <token>
```

IP reservations have a TTL (time-to-live). If a task is not launched with the reserved IP within the TTL, the reservation expires automatically.

### IP Pool Statistics

```bash
curl http://host:8000/api/overlay/ip/stats
```

Returns:

- Total IPs in the pool
- Allocated IPs
- Reserved IPs
- Available IPs

## Subnet Allocation

The host overlay manager allocates subnets to runners. With the default `10.128.0.0/12/6/14` configuration:

| Runner    | Subnet          | Usable Addresses |
| --------- | --------------- | ---------------- |
| Runner 1  | `10.128.0.0/14` | ~16,382          |
| Runner 2  | `10.132.0.0/14` | ~16,382          |
| Runner 3  | `10.136.0.0/14` | ~16,382          |
| ...       | ...             | ...              |
| Runner 63 | `10.188.0.0/14` | ~16,382          |

### Releasing Subnets

If a node is permanently removed:

```bash
kohakuriver node overlay-release <hostname>
```

This frees the subnet for reassignment to a new node.

### Cleanup Stale Entries

Remove overlay entries for nodes that no longer exist:

```bash
kohakuriver node overlay-cleanup
```

## Routing

The host routes traffic between runner subnets. All inter-node traffic flows through the host.

```
  Cross-Node Packet Flow
  ──────────────────────

  Container A                                      Container C
  (10.128.0.2)                                     (10.132.0.2)
  on Runner 1                                      on Runner 2
       │                                                ▲
       │ 1. Packet dst: 10.132.0.2                           │
       ▼                                                     │
  ┌──────────┐                                    ┌──────────┐
  │ Runner 1 │   2. VXLAN        3. VXLAN         │ Runner 2 │
  │ VXLAN    │──────────>┌──────┐──────────>      │ VXLAN    │
  │ Agent    │  encap    │ Host │  encap          │ Agent    │
  └──────────┘           │Router│                 └──────────┘
                         └───────────────────────────────────┘
                    Routes based on
                    destination subnet
```

This simplifies routing but makes the host a potential bottleneck for cross-node traffic.

## VXLAN Configuration

| Setting              | Default | Description                                                                      |
| -------------------- | ------- | -------------------------------------------------------------------------------- |
| `OVERLAY_VXLAN_ID`   | `100`   | VXLAN Network Identifier (VNI)                                                   |
| `OVERLAY_VXLAN_PORT` | `4789`  | UDP port for VXLAN encapsulation                                                 |
| `OVERLAY_MTU`        | `1450`  | MTU for the overlay interface (lower than physical to account for encapsulation) |

## Troubleshooting

### Containers Cannot Reach Other Nodes

- Verify overlay is enabled on both host and runner
- Check VXLAN interface exists: `ip link show kohaku-overlay`
- Verify routing table includes overlay subnets
- Check firewall allows UDP port 4789

### IP Assignment Failures

- Check available IPs: `kohakuriver node ip-available <hostname>`
- Verify subnet allocation: `kohakuriver node overlay <hostname>`
- Check for IP conflicts in the reservation pool

### Performance Issues

- Inter-node traffic through the host may bottleneck on host network bandwidth
- MTU misconfiguration causes fragmentation; ensure `OVERLAY_MTU` accounts for VXLAN overhead (50 bytes)
- Consider `jumbo frames` on physical network if supported

## Related Topics

- [Overlay Network Setup](../setup/overlay-network.md) -- Initial configuration
- [Node CLI](../cli/node.md) -- CLI commands
- [Task Scheduling](../tasks/scheduling.md) -- IP reservation for distributed tasks
