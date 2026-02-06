#!/bin/bash
# Cleanup all VXLAN overlay interfaces on the HOST node.
# Run this AFTER stopping the host service.
# Usage: sudo bash scripts/cleanup-overlay-host.sh

set -e

echo "=== KohakuRiver Host Overlay Cleanup ==="

# Remove all vxkr* VXLAN interfaces
for iface in $(ip -o link show type vxlan | awk -F': ' '{print $2}' | grep '^vxkr'); do
    echo "Removing VXLAN interface: $iface"
    ip link del "$iface" 2>/dev/null || true
done

# Remove kohaku-host dummy interface
if ip link show kohaku-host &>/dev/null; then
    echo "Removing dummy interface: kohaku-host"
    ip link del kohaku-host 2>/dev/null || true
fi

# Clean up iptables rules for overlay CIDR
for cidr in "10.128.0.0/12" "10.0.0.0/8"; do
    iptables -D FORWARD -s "$cidr" -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -d "$cidr" -j ACCEPT 2>/dev/null || true
done

echo "=== Host overlay cleanup complete ==="
echo "You can now restart the host service."
