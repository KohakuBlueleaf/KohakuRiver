---
title: kohakuriver forward
description: Port forwarding command for accessing services inside containers.
icon: i-carbon-port-input
---

# kohakuriver forward

The `kohakuriver forward` command forwards a local port to a service running inside a VPS container or VM via a WebSocket tunnel.

## Usage

```bash
kohakuriver forward <task_id> <remote_port> [options]
```

## Arguments

| Argument      | Description                                |
| ------------- | ------------------------------------------ |
| `task_id`     | Task ID of the running VPS                 |
| `remote_port` | Port inside the container/VM to forward to |

## Options

| Flag           | Default        | Description              |
| -------------- | -------------- | ------------------------ |
| `--local-port` | Same as remote | Local port to listen on  |
| `--local-host` | `127.0.0.1`    | Local address to bind to |
| `--proto`      | `tcp`          | Protocol: `tcp` or `udp` |

## Examples

```bash
# Forward Jupyter (same port)
kohakuriver forward 1234567890 8888

# Forward with different local port
kohakuriver forward 1234567890 8888 --local-port 9999

# Forward TensorBoard
kohakuriver forward 1234567890 6006

# Forward UDP traffic
kohakuriver forward 1234567890 5060 --proto udp

# Bind to all interfaces
kohakuriver forward 1234567890 8080 --local-host 0.0.0.0
```

## How It Works

The forward command creates a `TunnelForwarder` that:

1. Opens a local TCP/UDP listener on `--local-host:--local-port`
2. Establishes a WebSocket connection to the host's tunnel proxy
3. The host proxies the WebSocket to the runner's tunnel server
4. For each incoming local connection, sends a `MSG_CONNECT` message
5. Bidirectionally relays data using `MSG_DATA` messages
6. Closes connections with `MSG_CLOSE` messages

### Tunnel Protocol

The tunnel uses a binary protocol with an 8-byte header:

| Bytes | Field     | Description                                                               |
| ----- | --------- | ------------------------------------------------------------------------- |
| 0     | Type      | `0x01`=CONNECT, `0x02`=CONNECTED, `0x03`=DATA, `0x04`=CLOSE, `0x05`=ERROR |
| 1     | Proto     | `0x00`=TCP, `0x01`=UDP                                                    |
| 2-3   | Client ID | Unique connection identifier                                              |
| 4-5   | Port      | Target port (big-endian)                                                  |
| 6-7   | Reserved  | Unused                                                                    |

Data payload follows immediately after the header.

## Multiple Forwards

Run multiple forwards in parallel:

```bash
kohakuriver forward 1234567890 8888 &
kohakuriver forward 1234567890 6006 &
kohakuriver forward 1234567890 3000 &
```

Each creates an independent WebSocket tunnel.

## Related Topics

- [Port Forwarding](../vps/port-forwarding.md) -- Detailed forwarding documentation
- [SSH](ssh.md) -- SSH-based access
- [Connect](connect.md) -- WebSocket terminal
