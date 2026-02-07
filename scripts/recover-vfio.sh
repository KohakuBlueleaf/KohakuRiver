#!/bin/bash
# Recover stuck VFIO GPUs back to nvidia driver and clean up orphaned VM resources
# Usage: sudo bash scripts/recover-vfio.sh
#
# Handles three cases:
# 1. GPUs still bound to vfio-pci driver
# 2. GPUs unbound from vfio but driver_override still set (no driver at all)
# 3. Orphaned QEMU processes, TAP devices, NAT bridge
#
# Consumer NVIDIA cards: sysfs writes (unbind, driver_override, drivers_probe)
# can hang indefinitely even after succeeding. We use background writes with
# timeouts to avoid getting stuck.

set -uo pipefail

SYSFS_TIMEOUT=5  # seconds to wait for each sysfs write

# Write to a sysfs file with a timeout.
# Consumer NVIDIA cards can hang on sysfs writes even after the operation
# succeeds. Run the write in background, wait up to SYSFS_TIMEOUT seconds,
# then proceed regardless — caller should verify the result.
sysfs_write() {
    local path="$1"
    local value="$2"
    # Run write in background subshell
    ( echo "$value" > "$path" ) &
    local pid=$!
    local i=0
    local max=$((SYSFS_TIMEOUT * 10))  # poll every 0.1s
    while [ $i -lt $max ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" 2>/dev/null
            return 0  # completed
        fi
        sleep 0.1
        i=$((i + 1))
    done
    # Timed out — write is hung but may have succeeded
    echo "    (sysfs write to $path timed out after ${SYSFS_TIMEOUT}s — checking result)"
    return 1
}

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
echo "=== Stopping nvidia-persistenced ==="
systemctl stop nvidia-persistenced 2>/dev/null || true
sleep 1

echo ""
echo "=== Phase 1: Unbind devices still on vfio-pci ==="
for dev in $(ls /sys/bus/pci/drivers/vfio-pci/ 2>/dev/null | grep ':'); do
    echo "Unbinding $dev from vfio-pci..."
    sysfs_write "/sys/bus/pci/drivers/vfio-pci/unbind" "$dev" || true

    # Verify unbind
    if [ -L "/sys/bus/pci/devices/$dev/driver" ]; then
        cur=$(basename "$(readlink "/sys/bus/pci/devices/$dev/driver")")
        if [ "$cur" = "vfio-pci" ]; then
            echo "  WARNING: $dev still bound to vfio-pci after unbind"
            continue
        fi
    fi

    echo "  Clearing driver_override for $dev..."
    sysfs_write "/sys/bus/pci/devices/$dev/driver_override" "" || true
    echo "  Reprobing $dev..."
    sysfs_write "/sys/bus/pci/drivers_probe" "$dev" || true

    # Fallback: explicit nvidia/bind if probe didn't work
    if [ ! -L "/sys/bus/pci/devices/$dev/driver" ]; then
        echo "  drivers_probe did not bind, trying explicit nvidia/bind..."
        sysfs_write "/sys/bus/pci/drivers/nvidia/bind" "$dev" || true
    fi
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
    sysfs_write "$dev_path/driver_override" "" || true
    echo "  Reprobing $dev..."
    sysfs_write "/sys/bus/pci/drivers_probe" "$dev" || true

    # Fallback: explicit nvidia/bind if probe didn't work
    if [ ! -L "$dev_path/driver" ]; then
        echo "  drivers_probe did not bind, trying explicit nvidia/bind..."
        sysfs_write "/sys/bus/pci/drivers/nvidia/bind" "$dev" || true
    fi

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
echo "=== Restarting nvidia-persistenced ==="
systemctl restart nvidia-persistenced 2>/dev/null || true

echo ""
echo "=== Current NVIDIA GPU status ==="
echo "lspci:"
lspci -nnk 2>/dev/null | grep -A2 "NVIDIA" || true
echo ""
echo "nvidia-smi:"
nvidia-smi -L 2>/dev/null || echo "nvidia-smi not available or failed"

echo ""
echo "Done. Restart the runner to re-register GPUs."
