# Architecture

System architecture documentation for KohakuRiver's three-tier cluster management platform.

## Documents

| Document | Description |
|----------|-------------|
| [overview.md](overview.md) | Comprehensive architecture overview: components, communication, data model, startup sequence, and design decisions |
| data-flow.md | Task lifecycle data flows, status transitions, and inter-component messaging (planned) |

## Architecture at a Glance

```
                              Clients
                     (CLI / Web Dashboard / API)
                                |
                     REST API + WebSocket + SSH
                                |
        ┌───────────────────────┴───────────────────────┐
        |                    Host                        |
        |               (Port 8000/8002)                 |
        |                                                |
        |  ┌─────────────┐ ┌──────────────┐ ┌────────┐  |
        |  |   Task      | |   Overlay    | |  Auth  |  |
        |  |  Scheduler  | |   Manager    | | System |  |
        |  └─────────────┘ └──────────────┘ └────────┘  |
        |  ┌─────────────┐ ┌──────────────┐ ┌────────┐  |
        |  |    Node     | |     IP       | |  SSH   |  |
        |  |   Manager   | |  Reservation | |  Proxy |  |
        |  └─────────────┘ └──────────────┘ └────────┘  |
        |                                                |
        |            SQLite (Peewee ORM)                 |
        └───────────┬────────────────┬──────────────────┘
                    |                |
           HTTP + VXLAN        HTTP + VXLAN
                    |                |
     ┌──────────────┴──┐      ┌─────┴──────────────┐
     |    Runner 1      |      |    Runner 2        |
     |   (Port 8001)    |      |   (Port 8001)      |
     |                  |      |                     |
     | ┌──────────────┐ |      | ┌────────────────┐  |
     | | Task Executor| |      | |  VPS Manager   |  |
     | └──────────────┘ |      | └────────────────┘  |
     | ┌──────────────┐ |      | ┌────────────────┐  |
     | | VM VPS Mgr   | |      | | Tunnel Server  |  |
     | └──────────────┘ |      | └────────────────┘  |
     | ┌──────────────┐ |      | ┌────────────────┐  |
     | |Resource Mon. | |      | |  Overlay Agent |  |
     | └──────────────┘ |      | └────────────────┘  |
     |                  |      |                     |
     | ┌────┐ ┌────┐   |      | ┌────┐ ┌────┐      |
     | |Ctr1| |VM 1|   |      | |Ctr2| |Ctr3|      |
     | └────┘ └────┘   |      | └────┘ └────┘      |
     └─────────────────┘      └─────────────────────┘
```

### Key Points

- **Host** is the single orchestration server -- all client requests flow through it
- **Runners** are stateless executors that register with the Host on startup
- **Containers/VMs** are isolated workloads managed by Docker or QEMU/KVM on each Runner
- Communication between Host and Runners uses HTTP REST; cross-node container traffic uses VXLAN overlay
- All state lives in a single SQLite database on the Host; Runners keep only ephemeral local state
