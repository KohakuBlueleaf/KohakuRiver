#!/bin/bash
# Cleanup all VXLAN overlay and bridge interfaces on a RUNNER node.
# Run this AFTER stopping the runner service.
# Usage: sudo bash scripts/cleanup-overlay-runner.sh

set -e

echo "=== KohakuRiver Runner Overlay Cleanup ==="

# Remove Docker overlay network
if docker network inspect kohakuriver-overlay &>/dev/null; then
    echo "Removing Docker network: kohakuriver-overlay"
    # Disconnect any containers first
    for cid in $(docker network inspect kohakuriver-overlay -f '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null); do
        echo "  Disconnecting container: $cid"
        docker network disconnect -f kohakuriver-overlay "$cid" 2>/dev/null || true
    done
    docker network rm kohakuriver-overlay 2>/dev/null || true
fi

# Remove vxlan0 interface
if ip link show vxlan0 &>/dev/null; then
    echo "Removing VXLAN interface: vxlan0"
    ip link del vxlan0 2>/dev/null || true
fi

# Remove kohaku-overlay bridge
if ip link show kohaku-overlay &>/dev/null; then
    echo "Removing bridge: kohaku-overlay"
    ip link set kohaku-overlay down 2>/dev/null || true
    ip link del kohaku-overlay 2>/dev/null || true
fi

# Remove kohaku-br0 NAT bridge (VM standard mode)
if ip link show kohaku-br0 &>/dev/null; then
    echo "Removing NAT bridge: kohaku-br0"
    ip link set kohaku-br0 down 2>/dev/null || true
    ip link del kohaku-br0 2>/dev/null || true
fi

# Remove any leftover TAP devices
for tap in $(ip -o link show type tun | awk -F': ' '{print $2}' | grep '^tap-'); do
    echo "Removing TAP device: $tap"
    ip link del "$tap" 2>/dev/null || true
done

# Clean up iptables rules for overlay CIDR
for cidr in "10.128.0.0/12" "10.0.0.0/8"; do
    iptables -D FORWARD -s "$cidr" -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -d "$cidr" -j ACCEPT 2>/dev/null || true
    iptables -t nat -D POSTROUTING -s "$cidr" ! -d "$cidr" -j MASQUERADE 2>/dev/null || true
done

# Clean up overlay routes
for cidr in "10.128.0.0/12" "10.0.0.0/8"; do
    ip route del "$cidr" 2>/dev/null || true
done

echo "=== Runner overlay cleanup complete ==="
echo "You can now restart the runner service."
