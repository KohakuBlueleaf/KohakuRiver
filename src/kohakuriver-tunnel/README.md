# KohakuRiver Tunnel Client

A lightweight tunnel client that runs inside Docker containers to enable port forwarding without Docker port mapping.

## Overview

The tunnel client connects to the runner's WebSocket endpoint and handles incoming port forward requests. When a user wants to access a service running inside a container (e.g., port 8080), the flow is:

```
User App → CLI (TCP server) → Host (WS proxy) → Runner (WS) → Tunnel Client → Container Service
```

## Building

```bash
# Debug build
cargo build

# Release build (optimized for size)
cargo build --release

# The binary will be at target/release/tunnel-client (~1.7MB)
```

## Usage

```bash
# Using command line arguments
tunnel-client --runner-url ws://192.168.1.100:8001 --container-id my-container

# Using environment variables
RUNNER_URL=ws://192.168.1.100:8001 CONTAINER_ID=my-container tunnel-client
```

### Options

| Option | Env Variable | Default | Description |
|--------|--------------|---------|-------------|
| `-r, --runner-url` | `RUNNER_URL` | required | Runner WebSocket URL |
| `-c, --container-id` | `CONTAINER_ID` | required | Container ID or name |
| `--reconnect-delay` | `RECONNECT_DELAY` | 5 | Reconnect delay in seconds |
| `--max-reconnect` | `MAX_RECONNECT` | 0 | Max reconnect attempts (0=infinite) |
| `--log-level` | `LOG_LEVEL` | info | Log level |

## Protocol

The tunnel uses a binary protocol with 8-byte headers:

```
┌──────────┬──────────┬──────────┬──────────┬─────────────────────┐
│ Type (1B)│ Proto(1B)│ClientID  │ Port (2B)│  Payload (var)      │
│          │          │  (4B)    │          │                     │
└──────────┴──────────┴──────────┴──────────┴─────────────────────┘
```

### Message Types

| Type | Value | Direction | Description |
|------|-------|-----------|-------------|
| CONNECT | 0x01 | Server→Client | Open connection to port |
| CONNECTED | 0x02 | Client→Server | Connection established |
| DATA | 0x03 | Bidirectional | Relay data |
| CLOSE | 0x04 | Bidirectional | Close connection |
| ERROR | 0x05 | Client→Server | Connection failed |
| PING | 0x06 | Server→Client | Keepalive ping |
| PONG | 0x07 | Client→Server | Keepalive pong |

### Protocol Types

| Proto | Value | Description |
|-------|-------|-------------|
| TCP | 0x00 | TCP connection |
| UDP | 0x01 | UDP datagram |

## Static Binary for Containers

For use in minimal containers (scratch, distroless), build a static binary:

```bash
# Install musl target
rustup target add x86_64-unknown-linux-musl

# Build static binary
cargo build --release --target x86_64-unknown-linux-musl
```

## License

MIT
