#!/usr/bin/env bash
#
# DEPRECATED: Use 'kohakuriver qemu image create' instead.
#
# Create a QCOW2 base image for KohakuRiver VM VPS.
#
# Usage:
#   ./create-vm-base-image.sh [--name NAME] [--size SIZE] [--ubuntu-version VERSION]
#
# Requirements:
#   - qemu-img, virt-customize (from libguestfs-tools), wget
#
# Output:
#   /var/lib/kohakuriver/vm-images/<NAME>.qcow2
#
echo "WARNING: This script is deprecated. Use 'kohakuriver qemu image create' instead." >&2

set -euo pipefail

# Defaults
IMAGE_NAME="ubuntu-24.04"
DISK_SIZE="50G"
UBUNTU_VERSION="24.04"
IMAGES_DIR="/var/lib/kohakuriver/vm-images"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --name)
            IMAGE_NAME="$2"
            shift 2
            ;;
        --size)
            DISK_SIZE="$2"
            shift 2
            ;;
        --ubuntu-version)
            UBUNTU_VERSION="$2"
            shift 2
            ;;
        --images-dir)
            IMAGES_DIR="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--name NAME] [--size SIZE] [--ubuntu-version VERSION] [--images-dir DIR]"
            echo ""
            echo "Options:"
            echo "  --name NAME            Image name (default: ubuntu-24.04)"
            echo "  --size SIZE            Disk size (default: 50G)"
            echo "  --ubuntu-version VER   Ubuntu version (default: 24.04)"
            echo "  --images-dir DIR       Output directory (default: /var/lib/kohakuriver/vm-images)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

OUTPUT_PATH="${IMAGES_DIR}/${IMAGE_NAME}.qcow2"

echo "=== KohakuRiver VM Base Image Creator ==="
echo "Image name:     ${IMAGE_NAME}"
echo "Disk size:      ${DISK_SIZE}"
echo "Ubuntu version: ${UBUNTU_VERSION}"
echo "Output path:    ${OUTPUT_PATH}"
echo ""

# Check dependencies
for cmd in qemu-img virt-customize wget; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd not found. Install it first."
        case $cmd in
            virt-customize)
                echo "  apt install libguestfs-tools"
                ;;
            qemu-img)
                echo "  apt install qemu-utils"
                ;;
        esac
        exit 1
    fi
done

# Create output directory
mkdir -p "${IMAGES_DIR}"

# Download cloud image if not cached
CLOUD_IMAGE_URL="https://cloud-images.ubuntu.com/releases/${UBUNTU_VERSION}/release/ubuntu-${UBUNTU_VERSION}-server-cloudimg-amd64.img"
CACHE_DIR="/tmp/kohakuriver-vm-cache"
CACHED_IMAGE="${CACHE_DIR}/ubuntu-${UBUNTU_VERSION}-cloudimg.img"

mkdir -p "${CACHE_DIR}"

if [[ ! -f "${CACHED_IMAGE}" ]]; then
    echo "Downloading Ubuntu ${UBUNTU_VERSION} cloud image..."
    wget -q --show-progress -O "${CACHED_IMAGE}" "${CLOUD_IMAGE_URL}"
else
    echo "Using cached cloud image: ${CACHED_IMAGE}"
fi

# Create output image (copy and resize)
echo "Creating base image (${DISK_SIZE})..."
cp "${CACHED_IMAGE}" "${OUTPUT_PATH}"
qemu-img resize "${OUTPUT_PATH}" "${DISK_SIZE}"

# Customize the image
echo "Customizing image..."
virt-customize -a "${OUTPUT_PATH}" \
    --install "python3,python3-pip,openssh-server,curl,wget,net-tools,iputils-ping,cloud-init,qemu-guest-agent" \
    --run-command "systemctl enable ssh" \
    --run-command "systemctl enable qemu-guest-agent" \
    --run-command "sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config" \
    --run-command "sed -i 's/^PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config" \
    --run-command "echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config.d/99-kohakuriver.conf" \
    --run-command "cloud-init clean" \
    --truncate "/etc/machine-id"

echo ""
echo "=== Base image created successfully ==="
echo "Path: ${OUTPUT_PATH}"
echo "Size: $(du -h "${OUTPUT_PATH}" | cut -f1)"
echo ""
echo "To create a GPU-capable image with NVIDIA drivers, run:"
echo "  virt-customize -a ${OUTPUT_PATH} \\"
echo "    --install 'linux-headers-\$(uname -r),build-essential,dkms' \\"
echo "    --run-command 'wget -q https://us.download.nvidia.com/XFree86/Linux-x86_64/550.67/NVIDIA-Linux-x86_64-550.67.run -O /tmp/nvidia.run' \\"
echo "    --run-command 'chmod +x /tmp/nvidia.run && /tmp/nvidia.run --silent --no-kernel-module --no-kernel-module-source' \\"
echo "    --run-command 'rm /tmp/nvidia.run'"
