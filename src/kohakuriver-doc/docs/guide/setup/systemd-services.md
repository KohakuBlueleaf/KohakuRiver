---
title: Systemd Services
description: Setting up systemd service files for KohakuRiver host and runner.
icon: i-carbon-restart
---

# Systemd Services

For production deployments, run KohakuRiver components as systemd services for automatic startup and restart.

## Generating Service Files

The `kohakuriver init service` command generates, installs, and registers systemd service files:

```bash
# Generate and install both host and runner services
kohakuriver init service --all

# Generate host service only
kohakuriver init service --host

# Generate runner service only
kohakuriver init service --runner
```

### Options

| Flag                   | Description                                          |
| ---------------------- | ---------------------------------------------------- |
| `--host`               | Create host service                                  |
| `--runner`             | Create runner service                                |
| `--all`                | Create both services                                 |
| `--host-config PATH`   | Custom host config file path                         |
| `--runner-config PATH` | Custom runner config file path                       |
| `--working-dir PATH`   | Working directory (default: `~/.kohakuriver`)        |
| `--python-path PATH`   | Python executable (default: current interpreter)     |
| `--capture-env`        | Capture current PATH for the service (default: true) |
| `--no-install`         | Only generate files, do not register with systemd    |

### Example with Custom Paths

```bash
kohakuriver init service --runner \
    --runner-config /etc/kohakuriver/runner_config.py \
    --working-dir /opt/kohakuriver \
    --python-path /opt/venv/bin/python
```

## Generated Service Files

### kohakuriver-host.service

```ini
[Unit]
Description=KohakuRiver Host Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/user/.kohakuriver
ExecStart=/usr/bin/python -m kohakuriver.cli.host --config /home/user/.kohakuriver/host_config.py
Restart=on-failure
RestartSec=5
Environment="PATH=/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
```

### kohakuriver-runner.service

```ini
[Unit]
Description=KohakuRiver Runner Agent
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
WorkingDirectory=/home/user/.kohakuriver
ExecStart=/usr/bin/python -m kohakuriver.cli.runner --config /home/user/.kohakuriver/runner_config.py
Restart=on-failure
RestartSec=5
Environment="PATH=/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
```

Note: The runner service has `After=docker.service` and `Wants=docker.service` to ensure Docker is available.

## Managing Services

### Start Services

```bash
sudo systemctl start kohakuriver-host
sudo systemctl start kohakuriver-runner
```

### Enable on Boot

```bash
sudo systemctl enable kohakuriver-host
sudo systemctl enable kohakuriver-runner
```

### Check Status

```bash
sudo systemctl status kohakuriver-host
sudo systemctl status kohakuriver-runner
```

### View Logs

```bash
journalctl -u kohakuriver-host -f
journalctl -u kohakuriver-runner -f

# Last 100 lines
journalctl -u kohakuriver-host -n 100
```

### Restart After Config Changes

```bash
sudo systemctl restart kohakuriver-host
sudo systemctl restart kohakuriver-runner
```

## Running as Root

Services run as root by default. This is needed for:

- Network interface management (VXLAN, bridges)
- Docker socket access
- VFIO device binding

If you want to run as a non-root user, ensure that user has:

- Docker group membership
- Necessary capabilities for network management
- Access to the database and log directories

## Manual Service File Generation

To only generate the files without installing:

```bash
kohakuriver init service --all --no-install
```

Then manually install:

```bash
sudo cp kohakuriver-host.service /etc/systemd/system/
sudo cp kohakuriver-runner.service /etc/systemd/system/
sudo systemctl daemon-reload
```
