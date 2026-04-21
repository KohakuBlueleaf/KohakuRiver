# Public IP via WireGuard + BGP

Assign real public IPs to containers without requiring each Runner to have its own public IP allocation or be on the same L2 as the BGP router.

## Scenario

You have:
- A remote **BGP router** (e.g., VyOS) that announces a public IP range (e.g., `203.0.113.0/24`)
- A **KohakuRiver cluster** (Host + Runners) on a private/internal network (e.g., `10.10.10.0/24`)
- You want containers to get real public IPs from that range

Without this setup, only the BGP router itself can use those public IPs. This guide shows how to route a slice of that public range (e.g., `203.0.113.128/26`) to your cluster so containers can receive inbound connections on real public IPs.

---

## Architecture

```
Internet
    │
    ▼
┌──────────────────┐
│  BGP Router      │  announces 203.0.113.0/24 to ISP
│  (VyOS)          │  has static route: 203.0.113.128/26 via wg0
│  public IP       │
└────────┬─────────┘
         │ WireGuard tunnel (UDP 51234)
         │ tunnel IP: 172.16.1.1 ─── 172.16.1.3
         ▼
┌──────────────────┐
│  KohakuRiver     │  wg0 tunnel, policy routing:
│  Host            │    from 203.0.113.128/26 → wg0 → VyOS
│  10.10.10.201    │    to   203.0.113.128/26 → vx1_1 (VXLAN)
└────────┬─────────┘
         │ VXLAN (UDP 4789, VNI 201) on existing internal network
         ▼
┌──────────────────┐
│  Runner          │  kohaku-public bridge (203.0.113.129/26)
│  10.10.10.202    │  policy routing for public subnet
│                  │
│  ┌────────────┐  │
│  │ Container  │  │  203.0.113.130 (real public IP, not NATed)
│  └────────────┘  │
└──────────────────┘
```

**Key properties:**

- Only the **Host** talks to the BGP router (one WireGuard tunnel)
- **Runners don't need public IPs** or direct BGP connectivity
- Existing VXLAN overlay carries public subnet traffic from Host to Runner
- Container's source IP stays as its public IP (no NAT, so BGP return path works)

---

## Traffic Flow

### Inbound (internet → container)

```
Internet user (1.2.3.4)
    │ packet dst=203.0.113.130
    ▼
BGP router receives via AS
    │ static route: 203.0.113.128/26 via 172.16.1.3
    ▼ WireGuard (encrypted)
Host's wg0
    │ kernel routing: 203.0.113.128/26 dev vx1_1
    ▼ VXLAN (VNI 201)
Runner's vxlan-public → kohaku-public bridge
    │ L2 switching
    ▼
Container 203.0.113.130
```

### Outbound (container → internet)

```
Container (203.0.113.130)
    │ default gateway: 203.0.113.129 (runner bridge)
    ▼
Runner policy route: from 203.0.113.128/26 → default via 203.0.113.190 (Host on VXLAN)
    │ VXLAN encapsulation
    ▼
Host's vx1_1 receives (src=203.0.113.130, dst=internet)
    │ policy rule: from 203.0.113.128/26 → table 200
    │ table 200: default via 172.16.1.1 dev wg0
    ▼ WireGuard (encrypted)
BGP router → Internet
```

**Source IP is preserved the whole way.** No NAT = reverse path works correctly.

---

## Setup

### Prerequisites

- KohakuRiver multi-overlay already working (private overlay OK)
- BGP router (VyOS) with public IP announced to ISP
- UDP port for WireGuard reachable both ways

### Step 1: WireGuard on BGP Router (VyOS)

Generate keys:

```bash
configure
run generate wireguard named-keypairs kohakuriver-host
run show wireguard named-keypairs kohakuriver-host public-key
# Save this, you'll need it for Host config
```

Set up interface + peer:

```bash
set interfaces wireguard wg0 address '172.16.1.1/24'
set interfaces wireguard wg0 port '51234'
set interfaces wireguard wg0 private-key kohakuriver-host

set interfaces wireguard wg0 peer host public-key '<HOST_PUBLIC_KEY>'
set interfaces wireguard wg0 peer host allowed-ips '172.16.1.3/32'
set interfaces wireguard wg0 peer host allowed-ips '203.0.113.128/26'

# Route the public subnet slice to the host via tunnel
set protocols static route 203.0.113.128/26 next-hop 172.16.1.3

commit
save
```

### Step 2: WireGuard on Host

Install and generate keys:

```bash
sudo apt install wireguard
sudo bash -c 'wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key'
sudo chmod 600 /etc/wireguard/private.key
sudo cat /etc/wireguard/public.key
# Give this to VyOS
```

Write `/etc/wireguard/wg0.conf`:

```ini
[Interface]
PrivateKey = <HOST_PRIVATE_KEY>
Address = 172.16.1.3/24
ListenPort = 51234
Table = off       # Don't let WireGuard hijack default route

[Peer]
PublicKey = <VYOS_PUBLIC_KEY>
Endpoint = <VYOS_PUBLIC_IP>:51234
AllowedIPs = 0.0.0.0/0  # Accept all source IPs (BGP forwards internet traffic)
PersistentKeepalive = 25
```

**Why `AllowedIPs = 0.0.0.0/0`:** WireGuard uses `AllowedIPs` as both a route and ACL. With inbound traffic from BGP router, the source IPs are random internet users, so we must accept any source. Using `Table = off` prevents WireGuard from auto-adding a default route that would capture all host traffic.

Start the tunnel:

```bash
sudo wg-quick up wg0
sudo systemctl enable wg-quick@wg0

# Verify
sudo wg show       # Should show handshake
ping 172.16.1.1    # Should reach VyOS
```

### Step 3: Configure Multi-Overlay on KohakuRiver

In `~/.kohakuriver/host_config.py`:

```python
OVERLAY_ENABLED: bool = True

OVERLAY_NETWORKS: list[dict] = [
    {"name": "private", "subnet": "10.128.0.0/12/6/14", "vxlan_id_base": 100, "masquerade": True},
    {"name": "public", "subnet": "203.0.113.128/26", "vxlan_id_base": 200, "masquerade": False},
]
```

The public network uses `masquerade=False` — KohakuRiver automatically sets up policy routing on the Runner so outbound traffic from public subnet goes back to the Host via VXLAN (for onward WireGuard transit).

Restart Host (as root — needs to create VXLAN interfaces):

```bash
sudo $(which kohakuriver.host) --config /home/as6325400/.kohakuriver/host_config.py
```

Restart Runners (also as root).

Verify overlay is up:

```bash
curl http://localhost:8000/api/overlay/status
# Should show "networks": ["private", "public"]
```

### Step 4: Host Policy Routing for Outbound

KohakuRiver handles Runner-side policy routing automatically, but the **Host** needs manual policy routing to send public subnet traffic back through WireGuard:

```bash
# Rule 1: overlay-local destinations use main table (so VXLAN reply works)
sudo ip rule add to 203.0.113.128/26 table main priority 100

# Rule 2: traffic from public subnet defaults via WireGuard
sudo ip route add default via 172.16.1.1 dev wg0 table 200
sudo ip rule add from 203.0.113.128/26 table 200 priority 200
```

To make this persistent across reboots, add to systemd or the WireGuard config's `PostUp`:

```ini
[Interface]
# ... existing settings ...
PostUp = ip rule add to 203.0.113.128/26 table main priority 100
PostUp = ip route add default via 172.16.1.1 dev wg0 table 200
PostUp = ip rule add from 203.0.113.128/26 table 200 priority 200
PostDown = ip rule del to 203.0.113.128/26 table main priority 100 || true
PostDown = ip route del default via 172.16.1.1 dev wg0 table 200 || true
PostDown = ip rule del from 203.0.113.128/26 table 200 priority 200 || true
```

### Step 5: Test

Create a VPS with public IP:

```bash
curl -X POST http://localhost:8000/api/vps/create \
  -H "Content-Type: application/json" \
  -d '{"network_names": ["public"], "ssh_key_mode": "disabled"}'
```

Inside the container:

```bash
ip a                # should have 203.0.113.X
ping 8.8.8.8        # outbound works
# From outside:
ping 203.0.113.X  # inbound works
```

---

## Dual-NIC Recommended

For production, use **dual-network containers**:

```bash
curl -X POST http://localhost:8000/api/vps/create \
  -d '{"network_names": ["private", "public"], ...}'
```

Why:
- `private` (first, default gateway) → outbound via fast Runner-local NAT (no WireGuard hop)
- `public` (second) → receives inbound connections on real public IP

This keeps inbound bandwidth on the public path (small, bounded by external senders) while outbound package downloads, image pulls etc. go through the Runner's own internet connection (fast).

See [concept.md](concept.md) for dual-NIC architecture details.

---

## Why This Works

### Routing Conflict Prevention

WireGuard's `AllowedIPs` is both a route and ACL. Naively setting `AllowedIPs = 203.0.113.128/26` causes the Host to route **all** traffic for that subnet via wg0 — including traffic that should go over VXLAN to the Runner. This creates a loop (WireGuard delivers the packet to the host, but the host's route sends it right back into wg0).

Solution: `Table = off` disables automatic route addition. The Host then uses:
- Connected route on `vx1_1` (VXLAN interface with `203.0.113.190/26`) for Host → Runner
- Policy routing table 200 for container outbound → WireGuard

### No NAT

`masquerade=False` on the public overlay keeps the container's source IP intact. This is essential because:
- BGP announces `203.0.113.0/24` — the internet knows how to route responses for this range
- If we NATed to the Host's IP, responses would go to the Host (not via BGP) and the connection would break

### Only Host Needs the Tunnel

All Runners automatically route public subnet traffic via VXLAN to the Host. The Host is the single WireGuard endpoint. Adding Runners doesn't require adding WireGuard peers on the BGP router.

---

## Troubleshooting

### Host routing conflict (wg0 vs vx1_1)

Symptom: `ip route get 203.0.113.129` shows `dev wg0` instead of `dev vx1_1`.

Cause: `AllowedIPs` in WireGuard config still contains the public subnet, which auto-adds a route via wg0.

Fix: Use `AllowedIPs = 0.0.0.0/0` + `Table = off`.

### Container reaches host (.190) but not 8.8.8.8

Check:
1. `ip route show table 200` on Host — should have `default via 172.16.1.1 dev wg0`
2. `ip rule show` — should have rules priority 100 and 200 for public subnet
3. `sudo wg show` — should show active handshake

### Redirect Host messages in ping

```
From 203.0.113.129 icmp_seq=1 Redirect Host(New nexthop: 203.0.113.190)
```

This is normal — Runner kernel is telling Container "talk to .190 directly" because .190 (Host on VXLAN) is in the same /26 as the container. The ping still works; it's just a kernel optimization hint.

### BGP router doesn't forward to Host

Check VyOS:

```bash
show configuration commands | grep 203.0.113.128/26
# Must have: set protocols static route 203.0.113.128/26 next-hop 172.16.1.3
```

Also verify the public range is announced:

```bash
show ip bgp neighbors <upstream> advertised-routes
```

### Source IP visible to external services

Test from inside container:

```bash
curl ifconfig.me  # Should show your public IP (203.0.113.X), NOT the BGP router's IP
```

If it shows the BGP router's IP, `masquerade=True` is wrongly set on the public overlay, or VyOS is doing NAT.

---

## Security Considerations

- **Firewall the container.** It has a real public IP — services listening on it are exposed to the internet. Use iptables inside the container or on the Runner bridge.
- **Rate-limit WireGuard.** The Host's WireGuard endpoint is the single point of ingress for all public IP traffic. Consider rate-limiting if DDoS is a concern.
- **Rotate WireGuard keys periodically.**
- **Restrict BGP peer's `allowed-ips` to only the public range actually used** — don't use `0.0.0.0/0` on the VyOS side unless necessary.
