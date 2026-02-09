---
title: kohakuriver connect
description: WebSocket terminal connection to running containers and VMs.
icon: i-carbon-connect
---

# kohakuriver connect

The `kohakuriver connect` command opens an interactive terminal session to a running container or VM via WebSocket.

## Usage

```bash
kohakuriver connect <task_id> [options]
```

## Options

| Flag    | Default | Description                             |
| ------- | ------- | --------------------------------------- |
| `--ide` | `False` | Open in IDE mode (for programmatic use) |

## Examples

```bash
# Connect to a running VPS
kohakuriver connect 1234567890

# Connect to a running command task (for debugging)
kohakuriver connect 1234567890
```

## How It Works

The connect command creates a `TerminalHandler` that:

1. Establishes a WebSocket connection to the host
2. The host proxies the WebSocket to the runner
3. The runner attaches to the container's shell (via Docker exec)
4. Terminal input/output is relayed over the WebSocket

### Cross-Platform Support

The terminal handler supports both POSIX and Windows:

- **POSIX (Linux/macOS)**: Uses `termios` and `tty` modules for raw terminal mode. Terminal resize events (`SIGWINCH`) are forwarded to the container.
- **Windows**: Uses `msvcrt` for character-by-character input.

### Terminal Features

- Full interactive shell with colors and cursor support
- Terminal resize handling (auto-detects and forwards window size changes)
- Ctrl+C, Ctrl+D, and other control sequences are forwarded
- Exit with `exit` command or Ctrl+D

## Comparison with Other Access Methods

| Method            | Command                                 | Use Case                                       |
| ----------------- | --------------------------------------- | ---------------------------------------------- |
| `connect`         | `kohakuriver connect <id>`              | Quick interactive access via WebSocket         |
| `ssh`             | `kohakuriver ssh <id>`                  | Persistent SSH session, supports SCP/SFTP      |
| `terminal attach` | `kohakuriver terminal attach <id>`      | Direct Docker exec (requires Docker on runner) |
| `terminal exec`   | `kohakuriver terminal exec <id> -- cmd` | Run single command                             |

The `connect` command is best for quick debugging sessions. For long-running work, use SSH.

## Related Topics

- [SSH](ssh.md) -- SSH-based access
- [Port Forwarding](../vps/port-forwarding.md) -- Forwarding ports
- [Monitoring](../tasks/monitoring.md) -- Task monitoring
