# Tunnel System Overview

## Why a Tunnel System

Docker's standard port mapping (`-p host:container`) has significant limitations in a multi-node cluster environment:

1. **Port conflicts**: Multiple containers cannot bind the same host port. With dozens of containers per node, managing port allocations becomes complex and error-prone.
2. **Static binding**: Ports must be declared at container creation time. Users cannot expose new services from a running container without recreating it.
3. **No cross-node transparency**: Users need to know which Runner node a task is on, then connect to that node's IP and mapped port. This leaks infrastructure details.

KohakuRiver's tunnel system solves all three problems by providing dynamic, on-demand port forwarding through a single WebSocket channel per container. Users address tasks by ID, not by node IP and port number. The Host acts as a single entry point for all forwarded traffic, regardless of which Runner actually hosts the container.

---

## Architecture

```
                                                          Container
                                                     ┌──────────────────┐
                                                     │                  │
User CLI / Browser                                   │  ┌────────────┐  │
┌──────────────┐     ┌──────────────┐     ┌──────────────┐ tunnel-  │  │
│              │ WS  │              │ WS  │  Tunnel   │  │  client   │  │
│  Local Port  ├────►│  Host:8000   ├────►│  Server   ├──┤  (Rust)   │  │
│  Listener    │     │  Tunnel      │     │  (Runner) │  └─────┬─────┘  │
│              │◄────┤  Proxy       │◄────┤           │◄──     │        │
└──────────────┘     └──────────────┘     └──────────────┘  TCP/UDP    │
                                                     │     Connection   │
                                                     │        │        │
                                                     │  ┌─────▼─────┐  │
                                                     │  │  Target   │  │
                                                     │  │  Service  │  │
                                                     │  │ (e.g. :80)│  │
                                                     │  └───────────┘  │
                                                     └──────────────────┘
```

The tunnel chain consists of four components:

| Component | Location | Implementation | Role |
|-----------|----------|----------------|------|
| Local Port Listener | User machine | CLI (Python) | Accepts local TCP connections, wraps in protocol messages |
| Tunnel Proxy | Host (port 8000) | `tunnel_proxy.py` | Relays WebSocket frames between CLI and Runner |
| Tunnel Server | Runner (port 8001) | `tunnel_server.py` | Manages `ContainerTunnel` instances, routes by `client_id` |
| Tunnel Client | Inside container | `kohakuriver-tunnel` (Rust) | Connects to target service, relays data back through tunnel |

---

## Binary Protocol Specification

All tunnel traffic uses a binary WebSocket protocol with an 8-byte header followed by a variable-length payload.

### Header Format

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     Type      |     Proto     |           ClientID            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       ClientID (cont.)        |             Port              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Payload ...                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

Struct format string: `>BBIH` (big-endian, 8 bytes total).

| Offset | Field | Size | Type | Description |
|--------|-------|------|------|-------------|
| 0 | Type | 1 byte | uint8 | Message type |
| 1 | Proto | 1 byte | uint8 | Protocol type |
| 2 | ClientID | 4 bytes | uint32 | Connection identifier for multiplexing |
| 6 | Port | 2 bytes | uint16 | Target port number (used in CONNECT) |
| 8+ | Payload | variable | bytes | Data payload |

### Message Types

| Value | Name | Direction | Description |
|-------|------|-----------|-------------|
| 0x01 | MSG_CONNECT | Server -> Client | Request tunnel client to open connection to `port` |
| 0x02 | MSG_CONNECTED | Client -> Server | Connection established successfully |
| 0x03 | MSG_DATA | Bidirectional | Relay application data |
| 0x04 | MSG_CLOSE | Bidirectional | Close the connection identified by `client_id` |
| 0x05 | MSG_ERROR | Client -> Server | Connection failed (payload contains error string) |
| 0x06 | MSG_PING | Server -> Client | Keepalive ping |
| 0x07 | MSG_PONG | Client -> Server | Keepalive pong |

"Server" refers to the Runner's tunnel server; "Client" refers to the container's tunnel client.

### Protocol Types

| Value | Name | Description |
|-------|------|-------------|
| 0x00 | PROTO_TCP | TCP connection |
| 0x01 | PROTO_UDP | UDP datagram forwarding |

---

## Multiplexing Design

A single WebSocket connection exists between each container's tunnel client and the Runner's tunnel server. Multiple user port-forward sessions share this single WebSocket, distinguished by `client_id`.

```
User A (forward :8080) ─┐                          ┌─ TCP conn to :8080
                         │   Single WebSocket       │
User B (forward :8080) ──┼── Container Tunnel ──────┼─ TCP conn to :8080
                         │   (Runner <-> Container) │
User C (forward :3000) ──┘                          └─ TCP conn to :3000
```

### ContainerTunnel Class

Each container with an active tunnel is represented by a `ContainerTunnel` instance on the Runner:

```
ContainerTunnel
├── container_id: str           # Docker container identifier
├── ws: WebSocket               # Persistent WS to container's tunnel-client
├── _next_client_id: int        # Monotonically increasing counter
├── _lock: asyncio.Lock         # Thread-safe client_id allocation
└── _user_connections: dict     # client_id -> user WebSocket
```

Key operations:

- **`allocate_client_id()`**: Returns a unique integer under lock. Each new user connection gets a fresh `client_id`.
- **`register_user_connection(client_id, user_ws)`**: Maps a `client_id` to the user's WebSocket so responses from the container can be routed back.
- **`unregister_user_connection(client_id)`**: Removes the mapping on connection close.
- **`handle_container_message(data)`**: Parses the header, dispatches to the correct user WebSocket by `client_id`.

### TunnelServer Singleton

The `TunnelServer` manages all `ContainerTunnel` instances on a Runner:

```
TunnelServer
└── _tunnels: dict[str, ContainerTunnel]   # container_id -> tunnel
```

When a container's tunnel-client connects to `/ws/tunnel/{container_id}`, a new `ContainerTunnel` is created. When the WebSocket closes, the tunnel is unregistered.

---

## Connection Lifecycle

A complete port forward from user to container service follows this sequence:

```
CLI                Host Proxy           Runner Server        Tunnel Client
 |                     |                     |                     |
 |--- WS Connect ----->|                     |                     |
 |                     |--- WS Connect ----->|                     |
 |                     |                     |-- (already connected)|
 |                     |<--- "CONNECTED" ----|                     |
 |<--- "CONNECTED" ----|                     |                     |
 |                     |                     |                     |
 |--- MSG_CONNECT ---->|--- MSG_CONNECT ---->|--- MSG_CONNECT ---->|
 |    (client_id=1,    |                     |                     |
 |     port=8080)      |                     |  (opens TCP to :8080)
 |                     |                     |                     |
 |                     |<-- MSG_CONNECTED ---|<-- MSG_CONNECTED ---|
 |<-- MSG_CONNECTED ---|                     |                     |
 |                     |                     |                     |
 |--- MSG_DATA ------->|--- MSG_DATA ------->|--- MSG_DATA ------->|
 |    (client_id=1)    |                     |  (writes to TCP)    |
 |                     |                     |                     |
 |                     |<--- MSG_DATA -------|<--- MSG_DATA -------|
 |<--- MSG_DATA -------|    (client_id=1)    |  (reads from TCP)   |
 |                     |                     |                     |
 |--- MSG_CLOSE ------>|--- MSG_CLOSE ------>|--- MSG_CLOSE ------>|
 |    (client_id=1)    |                     |  (closes TCP)       |
```

1. The CLI opens a WebSocket to the Host at `/ws/forward/{task_id}/{port}`.
2. The Host looks up the task's Runner node and opens a WebSocket to `/ws/forward/{container_name}/{port}` on the Runner.
3. The Runner checks that a `ContainerTunnel` exists for the container and replies `"CONNECTED"` back through the chain.
4. The CLI sends a `MSG_CONNECT` with a locally allocated `client_id` and target port.
5. The Runner registers the user WebSocket for that `client_id` and forwards `MSG_CONNECT` to the container.
6. The tunnel client inside the container opens a TCP (or UDP) connection to `localhost:{port}` and replies `MSG_CONNECTED`.
7. `MSG_DATA` frames flow bidirectionally, carrying application data.
8. Either side can send `MSG_CLOSE` to tear down a specific connection.

---

## Tunnel Client Injection

The Rust tunnel client binary is mounted into containers at startup. The `tunnel_helper.py` module handles this:

1. **Binary mount**: The compiled `tunnel-client` binary is bind-mounted read-only at `/usr/local/bin/tunnel-client` inside the container.
2. **Environment variables**: Two variables are injected:
   - `KOHAKURIVER_TUNNEL_URL`: Runner's WebSocket URL for tunnel registration.
   - `KOHAKURIVER_CONTAINER_ID`: The container's identifier.
3. **Command wrapping**: The container's entrypoint is wrapped to start the tunnel client as a background daemon via `nohup` before running the main process.

The tunnel client (written in Rust with Tokio and Tungstenite) connects to the Runner's `/ws/tunnel/{container_id}` endpoint on startup and maintains the persistent WebSocket for the container's lifetime.

---

## SSH Proxy

For VPS containers, KohakuRiver provides an SSH proxy on the Host at port 8002. This allows users to SSH into VPS containers using a single entry point.

### Protocol

The SSH proxy uses a simple text-based handshake before switching to raw TCP forwarding:

```
Client                      Host SSH Proxy               Runner (SSH port)
  |                              |                              |
  |--- "REQUEST_TUNNEL <id>\n" ->|                              |
  |                              |-- (lookup task, validate) -->|
  |                              |--- TCP connect ------------->|
  |<----- "SUCCESS\n" ---------- |                              |
  |                              |                              |
  |<========= Bidirectional SSH traffic ========================>|
```

1. The CLI sends `REQUEST_TUNNEL <task_id>\n` to port 8002.
2. The Host validates the task (must be a VPS task, running, with a known SSH port).
3. The Host opens a TCP connection to the Runner's mapped SSH port.
4. On success, the Host replies `SUCCESS\n` and begins bidirectional forwarding.
5. On failure, the Host replies `ERROR <message>\n` and closes the connection.

The CLI then layers the local SSH client over this connection using `ProxyCommand`.

### Validation Checks

The SSH proxy performs several checks before routing:

| Check | Error condition |
|-------|-----------------|
| Task exists | Task ID not found in database |
| Task is VPS type | Non-VPS tasks do not have SSH |
| Task is active | Status must be `running` or `paused` |
| Node is online | Assigned Runner must be reachable |
| SSH port assigned | VPS must have an allocated SSH port |

---

## User-Facing CLI Commands

### Port Forwarding

```bash
kohakuriver forward <task_id> <port>
```

Opens a local listener and forwards traffic through the tunnel chain to the specified port inside the container. The local port matches the remote port by default.

### WebSocket Terminal

```bash
kohakuriver connect <task_id>
```

Opens an interactive terminal session to the container via WebSocket, distinct from the tunnel system but using the same Host-to-Runner WebSocket infrastructure.

### VPS SSH Connection

```bash
kohakuriver vps connect <task_id>
```

Connects to a VPS container via the SSH proxy on port 8002. Uses the local SSH client with `ProxyCommand` to tunnel through the Host, providing a native SSH experience with key-based authentication.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Container tunnel not connected | Host returns error text, closes WebSocket with code 1011 |
| Runner node offline | Host returns error text, closes WebSocket with code 1008 |
| Target port unreachable in container | Tunnel client sends MSG_ERROR with reason, Runner forwards to user |
| User WebSocket disconnects | Runner sends MSG_CLOSE for all active `client_id`s to container |
| Container tunnel disconnects | TunnelServer unregisters the tunnel; subsequent forward attempts fail |
| Host-to-Runner WebSocket timeout | Host returns timeout error within 10 seconds |
