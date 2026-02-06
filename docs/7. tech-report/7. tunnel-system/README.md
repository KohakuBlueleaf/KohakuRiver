# KohakuRiver Tunnel System

Port forwarding and SSH proxying for containers and VPS sessions across cluster nodes.

## Documents

| Document | Description |
|----------|-------------|
| [overview.md](overview.md) | Tunnel architecture, binary WebSocket protocol, multiplexing design, SSH proxy, and CLI usage |

## Quick Reference

### Architecture

```
User CLI / Browser
        |
        | WebSocket (port 8000)
        v
   Host (Tunnel Proxy)
        |
        | WebSocket (port 8001)
        v
   Runner (Tunnel Server)
        |
        | WebSocket (internal)
        v
   Container (Tunnel Client - Rust binary)
        |
        | TCP / UDP
        v
   Target Service (inside container)
```

### Protocol Header (8 bytes, big-endian)

| Field | Size | Format | Description |
|-------|------|--------|-------------|
| Type | 1 byte | `B` | Message type (CONNECT, DATA, CLOSE, ...) |
| Proto | 1 byte | `B` | Protocol (0x00=TCP, 0x01=UDP) |
| ClientID | 4 bytes | `I` (uint32) | Connection multiplexing identifier |
| Port | 2 bytes | `H` (uint16) | Target port in container |

### Key Components

| Component | Path | Role |
|-----------|------|------|
| Tunnel Protocol | `src/kohakuriver/tunnel/protocol.py` | Shared header format, message builders, parsers |
| Tunnel Proxy (Host) | `src/kohakuriver/host/services/tunnel_proxy.py` | Host-side WebSocket relay between CLI and Runner |
| Tunnel Server (Runner) | `src/kohakuriver/runner/services/tunnel_server.py` | Runner-side tunnel management and client routing |
| Tunnel Helper (Runner) | `src/kohakuriver/runner/services/tunnel_helper.py` | Injects tunnel-client binary into containers |
| SSH Proxy (Host) | `src/kohakuriver/ssh_proxy/server.py` | TCP proxy for SSH connections to VPS containers |
| Tunnel Client | `src/kohakuriver-tunnel/` | Rust binary (Tokio + Tungstenite) running inside containers |

### User-Facing Commands

| Command | Purpose |
|---------|---------|
| `kohakuriver forward <task_id> <port>` | Forward a container port to localhost |
| `kohakuriver connect <task_id>` | WebSocket terminal to container |
| `kohakuriver vps connect <task_id>` | SSH to VPS via Host proxy (port 8002) |
