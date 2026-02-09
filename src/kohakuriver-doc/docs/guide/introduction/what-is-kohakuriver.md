---
title: What is KohakuRiver
description: An overview of KohakuRiver, a self-hosted cluster manager for distributing containerized tasks and launching interactive sessions across compute nodes.
icon: i-carbon-cloud-app
---

# What is KohakuRiver

KohakuRiver is a self-hosted cluster manager designed for distributing containerized tasks and launching persistent interactive sessions (VPS) across compute nodes. It uses Docker containers and QEMU/KVM virtual machines as portable virtual environments. Shared storage can be used to synchronize environments across nodes, but is not required — containers can also be created from registries, and VMs use local disk images.

## Why KohakuRiver?

Tools like Kubernetes and Slurm are designed for **one person or team controlling a large cluster**. They excel at orchestrating workloads for a single administrative entity but struggle when multiple independent teams need to share the same hardware — resource limits are hard to manage, and users often end up fighting for node allocations.

KohakuRiver takes a fundamentally different approach: it is designed for **multiple people and teams sharing a cluster**. Whether you're running a research lab, an R&D team, or a development project, KohakuRiver makes it straightforward to divide a pool of compute resources among a group of independent users, each with their own isolated environments and fair resource access.

## Core Philosophy

- **Multi-tenant resource sharing** -- Built from the ground up for labs, R&D teams, and dev groups where many users share a pool of compute. Fair allocation, isolation, and per-user environments are first-class concerns.
- **Simplicity over complexity** -- A lightweight alternative to Kubernetes or Slurm for small-to-medium compute clusters. No complex orchestration layers; just a host, runners, and containers.
- **Shared storage as an option, not a requirement** -- Nodes can share a common filesystem (NFS, Samba, or SSHFS) for seamless environment synchronization, but it is not mandatory. Containers can also be created from Docker registries, and VMs use local disk images.
- **Docker as a virtual environment** -- Containers are treated as portable environments rather than microservices. You configure an environment once, export it as a tarball, and every node can use it.
- **GPU-aware scheduling** -- First-class support for NVIDIA GPU allocation, NUMA-aware scheduling, and VFIO GPU passthrough for VM workloads.

## Key Features

### Task Execution

Submit one-shot commands that run inside Docker containers on any node in the cluster. Tasks capture stdout/stderr, support resource constraints (CPU cores, memory, GPUs), and report completion status.

### Interactive VPS Sessions

Launch persistent interactive sessions backed by Docker containers or QEMU/KVM virtual machines. VPS instances support SSH access, terminal attach, snapshots, and port forwarding.

### Dual Backend Support

- **Docker containers** for lightweight, fast-starting workloads with shared filesystem access
- **QEMU/KVM VMs** for full isolation with VFIO GPU passthrough, ideal for workloads requiring dedicated GPU access or full OS environments

### Overlay Networking

An optional VXLAN overlay network enables cross-node communication between containers and VMs with L3 routed topology. Each runner gets its own /16 subnet, and the host acts as the central router.

### Web Dashboard and CLI

A Vue.js web dashboard provides visual management of tasks, VPS instances, and cluster health. A comprehensive CLI (Typer-based with Rich formatting) provides full cluster control from the terminal, including a TUI dashboard built with Textual.

### Authentication and Access Control

Role-based access control with five privilege levels: anonymous, viewer, user, operator, and admin. Invitation-based registration, API token management, and task approval workflows.

## Use Cases

- **ML/AI research clusters** -- Distribute training jobs across GPU nodes, launch Jupyter-style development environments
- **Shared compute labs** -- Give team members isolated VPS environments on shared hardware
- **Batch processing** -- Run data processing pipelines across multiple nodes with resource-aware scheduling
- **Development environments** -- Spin up pre-configured development containers with all dependencies installed

## Project Information

KohakuRiver is developed by Shih-Ying Yeh (KohakuBlueLeaf) and is open source. The project repository is at [github.com/KohakuBlueleaf/HakuRiver](https://github.com/KohakuBlueleaf/HakuRiver).

**Tech stack:**

- Backend: Python 3.10+, FastAPI, Uvicorn, Peewee ORM, SQLite
- CLI: Typer, Rich, Textual
- Frontend: Vue.js 3, Vite, Element Plus, Pinia, xterm.js, Plotly.js
- Tunnel: Rust (Tokio, Tungstenite)
- Containers: Docker SDK, QEMU/KVM
