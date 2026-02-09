---
title: CLI Overview
description: Overview of the KohakuRiver command-line interface.
icon: i-carbon-terminal
---

# CLI Overview

The KohakuRiver CLI (`kohakuriver`) is the primary interface for interacting with the cluster. It is built with Typer for command parsing, Rich for formatted output, and Textual for the TUI dashboard.

## Installation

The CLI is installed as part of the KohakuRiver Python package:

```bash
pip install kohakuriver
```

This provides the `kohakuriver` command as the main entry point.

## Entry Points

| Command              | Entry Point                   | Description                      |
| -------------------- | ----------------------------- | -------------------------------- |
| `kohakuriver`        | `kohakuriver.cli.main:run`    | Unified CLI with all subcommands |
| `kohakuriver.host`   | `kohakuriver.cli.host:main`   | Start host server directly       |
| `kohakuriver.runner` | `kohakuriver.cli.runner:main` | Start runner agent directly      |

## Command Structure

```
kohakuriver
  host              Start the host server
  runner            Start the runner agent
  task              Task management (submit, list, status, kill, pause, resume, logs, watch)
  vps               VPS management (create, list, status, stop, restart, pause, resume, connect)
  node              Node management (list, status, health, watch, summary, overlay, ip-*)
  docker            Docker environment management (images, container, tar)
  qemu              QEMU/KVM management (check, acs-override, image, instances, cleanup)
  ssh               SSH access (connect, config)
  forward           Port forwarding
  connect           WebSocket terminal attach
  auth              Authentication (login, logout, status, token)
  config            Configuration management (show, completion, env)
  init              Initialization (config, service)
  terminal          TUI dashboard and container attach (attach, exec)
```

## Configuration

The CLI reads its configuration from `~/.kohakuriver/cli_config.py` or from environment variables. The key setting is the host address:

```bash
# Set via environment variable
export KOHAKURIVER_HOST=http://192.168.1.100:8000

# Or view current config
kohakuriver config show
```

See [Config](config.md) for full configuration details.

## Shell Completion

Enable tab completion for your shell:

```bash
# Bash
kohakuriver config completion bash >> ~/.bashrc

# Zsh
kohakuriver config completion zsh >> ~/.zshrc

# Fish
kohakuriver config completion fish > ~/.config/fish/completions/kohakuriver.fish
```

## Output Format

The CLI uses Rich for formatted output:

- **Tables**: Node lists, task lists, and status information use Rich tables
- **Panels**: Detailed status views use Rich panels with headers
- **Colors**: Status values are color-coded (green=running, red=failed, etc.)
- **Progress**: Long operations show progress indicators

### Compact Mode

Some commands support compact output for scripting:

```bash
kohakuriver task list -c    # Compact table format
```

## Authentication

When connecting to a host with authentication enabled, log in first:

```bash
kohakuriver auth login --username myuser --password mypass
```

The session token is stored locally and included in subsequent requests. See [Auth](auth.md) for details.

## Error Handling

The CLI provides clear error messages:

- **Connection errors**: When the host is unreachable
- **Authentication errors**: When credentials are invalid or expired
- **Validation errors**: When command arguments are invalid
- **Resource errors**: When requested resources are unavailable

## Related Topics

- [Host](host.md) -- Starting the host server
- [Runner](runner.md) -- Starting the runner agent
- [Task](task.md) -- Task management commands
- [VPS](vps.md) -- VPS management commands
- [Node](node.md) -- Node management commands
