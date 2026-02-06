#!/bin/bash
# Recover stuck VFIO GPUs back to nvidia driver and clean up orphaned VM resources
# Usage: sudo bash scripts/recover-vfio.sh
#
# Handles three cases:
# 1. GPUs still bound to vfio-pci driver
# 2. GPUs unbound from vfio but driver_override still set (no driver at all)
# 3. Orphaned QEMU processes, TAP devices, NAT bridge

set -euo pipefail

echo "=== Killing any remaining QEMU VMs ==="
QEMU_PIDS=$(pgrep -f qemu-system || true)
if [ -n "$QEMU_PIDS" ]; then
    for pid in $QEMU_PIDS; do
        echo "Killing QEMU process $pid"
        kill -9 "$pid" 2>/dev/null || true
    done
    sleep 2
else
    echo "No QEMU processes found"
fi

echo ""
echo "=== Phase 1: Unbind devices still on vfio-pci ==="
for dev in $(ls /sys/bus/pci/drivers/vfio-pci/ 2>/dev/null | grep ':'); do
    echo "Unbinding $dev from vfio-pci..."
    echo "$dev" > /sys/bus/pci/drivers/vfio-pci/unbind || true
    echo "Clearing driver_override for $dev..."
    echo "" > /sys/bus/pci/devices/$dev/driver_override || true
    echo "Reprobing $dev..."
    echo "$dev" > /sys/bus/pci/drivers_probe || true
    echo "  Done: $dev"
done

echo ""
echo "=== Phase 2: Recover NVIDIA GPUs with no driver (stuck driver_override) ==="
# Find all NVIDIA GPU PCI devices (class 0x0302xx or 0x0300xx)
for dev_path in /sys/bus/pci/devices/*; do
    dev=$(basename "$dev_path")
    # Skip non-NVIDIA
    vendor=$(cat "$dev_path/vendor" 2>/dev/null || echo "")
    [ "$vendor" = "0x10de" ] || continue

    # Check PCI class - 0x03xxxx = display controller
    class=$(cat "$dev_path/class" 2>/dev/null || echo "")
    case "$class" in
        0x0300*|0x0302*) ;;  # VGA or 3D controller
        *) continue ;;
    esac

    # Check if already has a working driver
    if [ -L "$dev_path/driver" ]; then
        current=$(basename "$(readlink "$dev_path/driver")")
        if [ "$current" = "nvidia" ]; then
            continue  # Already on nvidia, skip
        fi
        echo "  $dev currently on: $current"
    else
        echo "  $dev has NO driver"
    fi

    # Clear override and reprobe
    echo "  Clearing driver_override for $dev..."
    echo "" > "$dev_path/driver_override" 2>/dev/null || true
    echo "  Reprobing $dev..."
    echo "$dev" > /sys/bus/pci/drivers_probe 2>/dev/null || true

    # Verify
    if [ -L "$dev_path/driver" ]; then
        new_driver=$(basename "$(readlink "$dev_path/driver")")
        echo "  Recovered: $dev -> $new_driver"
    else
        echo "  WARNING: $dev still has no driver!"
    fi
done

echo ""
echo "=== Cleaning up leftover TAP devices ==="
for tap in $(ip -o link show 2>/dev/null | grep -oP 'tap-\S+(?=:)' || true); do
    echo "Deleting TAP: $tap"
    ip link del "$tap" 2>/dev/null || true
done

echo ""
echo "=== Cleaning up VM NAT bridge (kohaku-br0) ==="
if ip link show kohaku-br0 &>/dev/null; then
    echo "Removing kohaku-br0 (standard/NAT mode bridge, not used in overlay mode)"
    ip link set kohaku-br0 down 2>/dev/null || true
    ip link del kohaku-br0 2>/dev/null || true
else
    echo "kohaku-br0 not found (expected if using overlay mode)"
fi

echo ""
echo "=== Cleaning up QMP sockets ==="
rm -f /tmp/kohakuriver-qmp-*.sock 2>/dev/null || true

echo ""
echo "=== Current NVIDIA GPU status ==="
echo "lspci:"
lspci -nnk 2>/dev/null | grep -A2 "NVIDIA" || true
echo ""
echo "nvidia-smi:"
nvidia-smi -L 2>/dev/null || echo "nvidia-smi not available or failed"

echo ""
echo "Done. Restart the runner to re-register GPUs."
