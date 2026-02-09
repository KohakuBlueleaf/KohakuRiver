---
title: Glossary
description: Definitions of key terms and concepts used throughout KohakuRiver.
icon: i-carbon-book
---

# Glossary

## Core Concepts

### Host

The central orchestration server that manages the cluster. Runs on port 8000 and coordinates task scheduling, node management, and authentication. There is exactly one host per cluster.

### Runner

An agent process running on each compute node (port 8001). Runners register with the host, send periodic heartbeats, and execute tasks in Docker containers or QEMU VMs.

### Task

A unit of work submitted to the cluster. Tasks have a unique snowflake ID and track their lifecycle from submission through completion. There are two types: **command** tasks and **VPS** tasks.

### Command Task

A one-shot task that executes a command inside a Docker container, captures stdout/stderr to log files, and reports an exit code upon completion.

### VPS (Virtual Private Server)

A long-running interactive session backed by either a Docker container or a QEMU/KVM virtual machine. VPS instances support SSH access, terminal attach, snapshots, and port forwarding.

### Container Environment

A pre-configured Docker image used to run tasks. Environments can be distributed as tarballs via shared storage (created on the host, customized interactively, exported, and automatically imported by runners) or pulled directly from a Docker registry using the `registry_image` field.

### Batch

A group of tasks submitted together. Tasks in a batch share a `batch_id` and can target different nodes. Useful for distributed workloads where the same command runs on multiple nodes.

## Networking

### Overlay Network

An optional VXLAN-based L3 network that enables containers and VMs on different runner nodes to communicate directly using private IP addresses. The host acts as the central router.

### VXLAN (Virtual Extensible LAN)

The tunneling protocol used for the overlay network. Each runner gets a unique VXLAN device connecting it to the host. UDP port 4789 is used by default.

### Tunnel

A WebSocket-based port forwarding system that allows accessing TCP/UDP services running inside containers without exposing ports on the host network. Uses an 8-byte binary header protocol with message types for connect, data, close, and error.

### SSH Proxy

A service running on the host (port 8002) that proxies SSH connections to VPS containers on any runner node. Clients connect to the proxy, which routes the connection to the correct runner based on task ID.

### IP Reservation

A mechanism for pre-allocating overlay IP addresses before task submission. Useful for distributed training where the master node's IP must be known before launching worker tasks.

## Resource Management

### NUMA (Non-Uniform Memory Access)

Hardware topology where CPU cores are grouped into NUMA nodes with local memory. KohakuRiver supports NUMA-aware task placement, pinning tasks to specific NUMA nodes for optimal memory access patterns.

### GPU Allocation

The system tracks GPU availability per node and allocates specific GPUs to tasks using the NVIDIA Container Toolkit `--gpus` flag. GPUs are identified by their index on each node.

### VFIO (Virtual Function I/O)

A Linux framework for passing PCI devices (typically GPUs) directly to virtual machines. Used by KohakuRiver's QEMU backend for GPU passthrough.

### IOMMU (Input/Output Memory Management Unit)

Hardware feature required for VFIO GPU passthrough. Groups PCI devices for safe isolation. KohakuRiver supports ACS override to split shared IOMMU groups.

### ACS Override

A technique to split IOMMU groups on server hardware where GPUs share groups due to PCIe switches. Requires kernel parameter `pcie_acs_override=downstream,multifunction` and runtime `setpci` commands.

## Authentication

### User Roles

A hierarchy of five privilege levels:

- **anony** -- Anonymous/unauthenticated access
- **viewer** -- Read-only access to cluster status
- **user** -- Can submit tasks (may require approval)
- **operator** -- Can manage VPS, approve tasks, manage users
- **admin** -- Full system access

### API Token

A bearer token for programmatic access to the host API. Stored as SHA3-512 hashes; the plaintext token is shown only once at creation time.

### Invitation

A token-based registration system. New users can only register using a valid invitation token created by an operator or admin.

### Group

An organizational unit for users with optional resource quotas. Users can belong to multiple groups.

## VPS Concepts

### SSH Key Mode

The method used to configure SSH access for a VPS:

- **disabled** -- No SSH server; access only via terminal attach (fastest startup)
- **none** -- SSH enabled with passwordless root login
- **upload** -- SSH enabled with a user-provided public key
- **generate** -- SSH enabled with a server-generated keypair (private key returned to client)

### Snapshot

A saved state of a Docker VPS container preserved as a Docker image. Snapshots can be created manually or automatically when stopping a VPS. They enable restoring a VPS to a previous state.

### VPS Backend

The virtualization technology used to run a VPS:

- **docker** -- Docker container (default, lightweight)
- **qemu** -- QEMU/KVM virtual machine (full isolation, GPU passthrough)

## Infrastructure

### Shared Storage

A filesystem accessible by all cluster nodes (host and runners), typically via NFS, Samba, or SSHFS. The mount path does not need to be the same on every node -- each node configures its own `SHARED_DIR` setting to point to the shared filesystem. Used for container tarballs, task logs, and user data accessible from any node. Shared storage is recommended for the simplest setup but is optional -- containers can also be pulled from Docker registries, and VMs use local disk images.

### Cloud-init

An industry-standard system for VM initialization. KohakuRiver uses cloud-init to provision QEMU VMs with networking, SSH keys, an embedded agent, and optionally NVIDIA drivers.

### KohakuVault

A SQLite-based key-value store used by runners for local state tracking. Stores runner-side task state and metadata.

### Snowflake ID

A 64-bit globally unique, time-ordered identifier used for task IDs. Generated without coordination between nodes.
