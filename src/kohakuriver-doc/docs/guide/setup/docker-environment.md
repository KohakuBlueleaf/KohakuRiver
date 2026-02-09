---
title: Docker Environment
description: Setting up Docker, base images, GPU runtime, and container environments for KohakuRiver.
icon: i-carbon-container-software
---

# Docker Environment

Docker is the primary container runtime for KohakuRiver tasks and VPS instances.

## Docker Installation

Install Docker Engine on all runner nodes:

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Verify Docker is working:

```bash
docker run hello-world
```

## NVIDIA Container Toolkit

For GPU support, install the NVIDIA Container Toolkit:

```bash
# Add NVIDIA repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify GPU access in containers:

```bash
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

## Container Environment Workflow

KohakuRiver uses a tarball-based approach for container environments instead of a registry.

### 1. Create a Container on the Host

```bash
kohakuriver docker container create python:3.11 my-ml-env
```

### 2. Enter the Container and Install Packages

```bash
kohakuriver docker container shell my-ml-env
```

Inside the container:

```bash
pip install torch transformers datasets
apt install -y vim htop
exit
```

### 3. Export as a Tarball

```bash
kohakuriver docker tar create my-ml-env
```

This saves the container as a tarball in the shared storage directory (`SHARED_DIR/kohakuriver-containers/my-ml-env/`).

### 4. Use in Tasks

```bash
kohakuriver task submit -t mynode --container my-ml-env -- python /shared/train.py
```

Runners automatically import the tarball into their local Docker when a task references the container name.

## Managing Container Environments

### List Images

```bash
kohakuriver docker images
```

Shows all KohakuRiver container images (tagged as `kohakuriver/<name>:base`).

### List Containers

```bash
kohakuriver docker container list
```

Shows environment containers on the host with their status.

### List Tarballs

```bash
kohakuriver docker tar list
```

Shows available tarballs with version history and sizes.

### Delete Resources

```bash
kohakuriver docker delete <image-name>
kohakuriver docker container delete <container-name>
kohakuriver docker tar delete <tarball-name>
```

### Migrate Legacy Containers

```bash
kohakuriver docker container migrate <old-name>
```

Renames a container to the `kohakuriver-env-<name>` naming convention.

## Using Registry Images Directly

Instead of the tarball workflow, you can use Docker Hub or other registry images directly:

```bash
kohakuriver task submit -t mynode --image ubuntu:22.04 -- apt list
kohakuriver vps create --image pytorch/pytorch:latest
```

The runner will pull the image if it is not cached locally.

## Docker Network

Each runner creates a Docker bridge network for containers:

- **Default network**: `kohakuriver-net` (subnet `172.30.0.0/16`, gateway `172.30.0.1`)
- **Overlay network**: `kohakuriver-overlay` (when overlay is enabled)

Containers on the same runner can communicate via container name. Cross-node communication requires the overlay network.
