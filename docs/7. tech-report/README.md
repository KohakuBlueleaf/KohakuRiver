# KohakuRiver Tech Report

Deep-dive technical documentation for KohakuRiver's major subsystems. Each section covers internal design decisions, protocols, data flows, and implementation details that go beyond the user-facing guides. This is the reference material for contributors, operators debugging production issues, and anyone who needs to understand how the system works under the hood.

KohakuRiver is a three-tier cluster manager: a central **Host** orchestrates distributed **Runners**, which execute workloads inside **Docker containers** and **QEMU/KVM virtual machines**. The sections below document each layer of that stack.

## Documents

| # | Section | Description |
|---|---------|-------------|
| 1 | [Architecture](1.%20architecture/) | System architecture overview: three-tier topology, service boundaries, and inter-component communication |
| 2 | [Task System](2.%20task-system/) | Task lifecycle from submission through scheduling, assignment, execution, and terminal states |
| 3 | [Container System](3.%20container-system/) | Docker container management, image handling, shared-storage sync, and resource isolation |
| 4 | [VPS System](4.%20vps-system/) | Long-running interactive Docker sessions: creation, snapshot, restore, and SSH access |
| 5 | [QEMU Virtualization](5.%20qemu-virtualization/) | QEMU/KVM virtual machine backend: VM lifecycle, disk management, and hardware passthrough |
| 6 | [Networking](6.%20networking/) | VXLAN overlay network design, L3 routing through Host, per-runner NAT, and VM networking |
| 7 | [Tunnel System](7.%20tunnel-system/) | Port forwarding tunnel protocol: binary WebSocket framing, TCP/UDP proxying, and the Rust tunnel client |
| 8 | [Authentication](8.%20authentication/) | Auth system: token issuance, role-based access control, user groups, and API authorization |

## System Architecture

```
                          ┌──────────────────────────┐
                          │      Web Dashboard       │
                          │     (Vue.js + Vite)      │
                          └────────────┬─────────────┘
                                       │ HTTP / WebSocket
                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         Host  (port 8000)                            │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  ┌────────────┐  │
│  │    Task       │  │   Overlay    │  │    IP     │  │    Auth    │  │
│  │  Scheduler    │  │   Manager    │  │ Reserv.   │  │   System   │  │
│  └──────────────┘  └──────────────┘  └───────────┘  └────────────┘  │
│  ┌──────────────┐  ┌──────────────┐                                  │
│  │  SSH Proxy   │  │   Node       │         SQLite (Peewee ORM)      │
│  │  (port 8002) │  │  Registry    │                                  │
│  └──────────────┘  └──────────────┘                                  │
└────────┬──────────────────┬──────────────────────────────────────────┘
         │                  │
         │  VXLAN (UDP 4789)│  HTTP / WebSocket
         │                  │
    ┌────┴──────────────────┴──────────────────────────────────────┐
    │                                                              │
    ▼                                                              ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│        Runner A (port 8001)     │   │        Runner B (port 8001)     │
│                                 │   │                                 │
│  ┌────────────┐ ┌────────────┐  │   │  ┌────────────┐ ┌────────────┐ │
│  │   Task     │ │    VPS     │  │   │  │   Task     │ │    VPS     │ │
│  │  Executor  │ │  Manager   │  │   │  │  Executor  │ │  Manager   │ │
│  └────────────┘ └────────────┘  │   │  └────────────┘ └────────────┘ │
│  ┌────────────┐ ┌────────────┐  │   │  ┌────────────┐ ┌────────────┐ │
│  │  Tunnel    │ │  VXLAN     │  │   │  │  Tunnel    │ │  VXLAN     │ │
│  │  Server    │ │  Agent     │  │   │  │  Server    │ │  Agent     │ │
│  └────────────┘ └────────────┘  │   │  └────────────┘ └────────────┘ │
│                                 │   │                                 │
│  ┌──────────┐  ┌──────────┐    │   │  ┌──────────┐  ┌──────────┐   │
│  │ Docker   │  │  QEMU/   │    │   │  │ Docker   │  │  QEMU/   │   │
│  │Container │  │  KVM VM  │    │   │  │Container │  │  KVM VM  │   │
│  │10.1.x.x  │  │          │    │   │  │10.2.x.x  │  │          │   │
│  └──────────┘  └──────────┘    │   │  └──────────┘  └──────────┘   │
└─────────────────────────────────┘   └─────────────────────────────────┘
         │              │                      │              │
         └──────────────┴──────────────────────┴──────────────┘
                      VXLAN Overlay (10.0.0.0/8)
                   Host acts as central L3 router
```

### Port Summary

| Port | Service | Protocol |
|------|---------|----------|
| 8000 | Host API | HTTP / WebSocket |
| 8001 | Runner API | HTTP / WebSocket |
| 8002 | SSH Proxy | TCP (SSH) |
| 4789 | VXLAN underlay | UDP |

## Reading Order

For a first read-through, the sections are numbered in a recommended order:

1. **Architecture** -- start here for the big picture of how Host, Runners, and workloads fit together.
2. **Task System** -- understand the core scheduling and state machine that drives all workloads.
3. **Container System** -- learn how Docker containers are created, synced, and torn down.
4. **VPS System** -- builds on the container system to add persistent interactive sessions.
5. **QEMU Virtualization** -- the VM backend, an alternative execution environment to Docker.
6. **Networking** -- the VXLAN overlay that connects containers and VMs across nodes.
7. **Tunnel System** -- port forwarding that makes container/VM services reachable externally.
8. **Authentication** -- the auth layer that secures all of the above.

Sections 3-5 can be read independently depending on which workload type you are interested in. Section 6 (Networking) is a prerequisite for fully understanding sections 7 and 8.
