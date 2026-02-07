#!/bin/bash
# Test VFIO bind/unbind on a specific GPU
# Usage: sudo bash scripts/test-vfio-bind.sh <PCI_ADDRESS>
# Example: sudo bash scripts/test-vfio-bind.sh 0000:82:00.0
#
# This script tests the full cycle:
#   nvidia -> vfio-pci -> nvidia
# with timeout-aware sysfs writes and explicit bind fallbacks.
#
# Prerequisites:
#   - nvidia_drm.modeset=0 (see docs/2. admin-guides/6. qemu-setup.md Step 4)
#   - VFIO modules loaded

set -uo pipefail

SYSFS_TIMEOUT=5

if [ $# -lt 1 ]; then
    echo "Usage: $0 <PCI_ADDRESS>"
    echo ""
    echo "Available NVIDIA GPUs:"
    for dev_path in /sys/bus/pci/devices/*; do
        dev=$(basename "$dev_path")
        vendor=$(cat "$dev_path/vendor" 2>/dev/null || echo "")
        [ "$vendor" = "0x10de" ] || continue
        class=$(cat "$dev_path/class" 2>/dev/null || echo "")
        case "$class" in 0x0300*|0x0302*) ;; *) continue ;; esac
        driver="none"
        [ -L "$dev_path/driver" ] && driver=$(basename "$(readlink "$dev_path/driver")")
        desc=$(lspci -s "$dev" 2>/dev/null | cut -d: -f3- | sed 's/^ //')
        echo "  $dev  [$driver]  $desc"
    done
    exit 1
fi

PCI="$1"
DEV_PATH="/sys/bus/pci/devices/$PCI"

if [ ! -d "$DEV_PATH" ]; then
    echo "ERROR: PCI device $PCI not found"
    exit 1
fi

sysfs_write() {
    local path="$1"
    local value="$2"
    ( echo "$value" > "$path" ) &
    local pid=$!
    local i=0
    local max=$((SYSFS_TIMEOUT * 10))  # poll every 0.1s
    while [ $i -lt $max ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" 2>/dev/null
            return 0
        fi
        sleep 0.1
        i=$((i + 1))
    done
    echo "  (write to $path timed out after ${SYSFS_TIMEOUT}s)"
    return 1
}

get_driver() {
    if [ -L "$DEV_PATH/driver" ]; then
        basename "$(readlink "$DEV_PATH/driver")"
    else
        echo "none"
    fi
}

echo "=== VFIO Bind/Unbind Test for $PCI ==="
echo "  nvidia_drm.modeset = $(cat /sys/module/nvidia_drm/parameters/modeset 2>/dev/null || echo 'N/A (module not loaded)')"
echo "  nvidia-persistenced = $(systemctl is-active nvidia-persistenced 2>/dev/null || echo 'unknown')"
echo ""

ORIG_DRIVER=$(get_driver)
echo "Current driver: $ORIG_DRIVER"

if [ "$ORIG_DRIVER" = "vfio-pci" ]; then
    echo "Already on vfio-pci, skipping bind phase -- will test unbind only."
else
    # === Phase 1: Bind to vfio-pci ===
    echo ""
    echo "--- Phase 1: Bind $PCI to vfio-pci ---"

    if [ "$ORIG_DRIVER" = "nvidia" ]; then
        echo "Stopping nvidia-persistenced..."
        systemctl stop nvidia-persistenced 2>/dev/null || true
        sleep 1
    fi

    if [ "$ORIG_DRIVER" != "none" ]; then
        echo "Unbinding from $ORIG_DRIVER..."
        sysfs_write "$DEV_PATH/driver/unbind" "$PCI" || true

        drv=$(get_driver)
        if [ "$drv" = "none" ]; then
            echo "  Unbind OK (driver: none)"
        else
            echo "  Unbind result: driver=$drv"
            if [ "$drv" = "$ORIG_DRIVER" ]; then
                echo "  ERROR: still bound to $ORIG_DRIVER -- aborting"
                systemctl start nvidia-persistenced 2>/dev/null || true
                exit 1
            fi
        fi
    fi

    echo "Setting driver_override to vfio-pci..."
    sysfs_write "$DEV_PATH/driver_override" "vfio-pci" || true

    echo "Probing via drivers_probe..."
    sysfs_write "/sys/bus/pci/drivers_probe" "$PCI" || true

    drv=$(get_driver)
    if [ "$drv" != "vfio-pci" ]; then
        echo "  drivers_probe did not bind (driver: $drv), trying explicit vfio-pci/bind..."
        sysfs_write "/sys/bus/pci/drivers/vfio-pci/bind" "$PCI" || true
        drv=$(get_driver)
    fi

    echo "Driver after bind: $drv"
    if [ "$drv" = "vfio-pci" ]; then
        echo "  PASS: bound to vfio-pci"
    else
        echo "  FAIL: expected vfio-pci, got $drv"
        systemctl start nvidia-persistenced 2>/dev/null || true
        exit 1
    fi

    # Restart persistenced so remaining GPUs keep persistence mode
    echo "Restarting nvidia-persistenced (for remaining GPUs)..."
    systemctl start nvidia-persistenced 2>/dev/null || true

    echo ""
    echo "Waiting 3s before unbind test..."
    sleep 3
fi

# === Phase 2: Unbind from vfio-pci and restore ===
echo ""
echo "--- Phase 2: Unbind $PCI from vfio-pci and restore ---"

echo "Unbinding from vfio-pci..."
sysfs_write "/sys/bus/pci/drivers/vfio-pci/unbind" "$PCI" || true

drv=$(get_driver)
if [ "$drv" = "vfio-pci" ]; then
    echo "  WARNING: still on vfio-pci after unbind write"
else
    echo "  Unbind OK (driver: $drv)"
fi

echo "Clearing driver_override..."
sysfs_write "$DEV_PATH/driver_override" "" || true

echo "Reprobing via drivers_probe..."
sysfs_write "/sys/bus/pci/drivers_probe" "$PCI" || true

drv=$(get_driver)
if [ "$drv" != "nvidia" ]; then
    echo "  drivers_probe did not restore nvidia (driver: $drv), trying explicit nvidia/bind..."
    sysfs_write "/sys/bus/pci/drivers/nvidia/bind" "$PCI" || true
    drv=$(get_driver)
fi

echo "Driver after restore: $drv"
if [ "$drv" = "nvidia" ]; then
    echo "  PASS: restored to nvidia"
elif [ "$drv" = "none" ]; then
    echo "  WARN: no driver bound -- may need nvidia-persistenced restart"
else
    echo "  INFO: bound to $drv (expected nvidia)"
fi

echo ""
echo "Restarting nvidia-persistenced..."
systemctl restart nvidia-persistenced 2>/dev/null || true

echo ""
echo "=== Final status ==="
echo "Driver: $(get_driver)"
nvidia-smi -i "$PCI" -L 2>/dev/null || echo "nvidia-smi cannot see $PCI"
echo ""
echo "Test complete."
