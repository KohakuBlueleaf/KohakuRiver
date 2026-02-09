---
title: Security Hardening
description: Best practices for securing your KohakuRiver cluster deployment.
icon: i-carbon-security
---

# Security Hardening

By default, KohakuRiver runs without authentication and accepts connections from any source. For production deployments, apply these security measures.

## Enable Authentication

The most important step. Set in `host_config.py`:

```python
AUTH_ENABLED: bool = True
ADMIN_SECRET: str = "strong-random-secret"
```

See [Authentication](./authentication.md) for full setup.

## Firewall Configuration

Restrict network access to only necessary ports:

```bash
# Host machine
sudo ufw allow 8000/tcp   # API (restrict to trusted IPs if possible)
sudo ufw allow 8002/tcp   # SSH proxy
sudo ufw allow 4789/udp   # VXLAN (only from runner IPs)

# Runner machines
sudo ufw allow 8001/tcp   # Runner API (only from host IP)
sudo ufw allow 2222:2300/tcp  # SSH to VPS (restrict range)
```

For stricter access, limit to specific source IPs:

```bash
sudo ufw allow from 192.168.1.100 to any port 8001 proto tcp
```

## TLS/HTTPS

KohakuRiver does not include built-in TLS. For encrypted communication, use a reverse proxy:

### Nginx Reverse Proxy

```nginx
server {
    listen 443 ssl;
    server_name kohaku.example.com;

    ssl_certificate /etc/ssl/certs/kohaku.crt;
    ssl_certificate_key /etc/ssl/private/kohaku.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Privileged Containers

By default, containers run without `--privileged`. Only enable when necessary:

```python
# In host/runner config
TASKS_PRIVILEGED: bool = False  # Keep this false
```

Individual tasks can request privileged mode via `--privileged`, but this should be restricted to trusted users.

## Admin Secret Protection

- Use a strong, randomly generated `ADMIN_SECRET`
- Rotate the secret after initial setup
- Consider clearing `ADMIN_SECRET` and `ADMIN_REGISTER_SECRET` after bootstrapping the first admin account

## Credential Storage

The CLI stores auth tokens at `~/.kohakuriver/auth.json` with mode 0600 (owner-only read/write). Ensure this file is not world-readable.

## Docker Security

- Avoid running the runner as root if possible
- Use user namespace remapping in Docker
- Restrict container capabilities
- Limit container mount paths via `ADDITIONAL_MOUNTS`

## Network Isolation

- Place the cluster on a private network segment
- Use the overlay network for inter-container communication instead of exposing ports
- Consider a VPN for remote access to the cluster

## Database Security

The SQLite database contains task history and user credentials (bcrypt hashed). Protect it:

```bash
chmod 600 /var/lib/kohakuriver/kohakuriver.db
```

## Monitoring

- Enable logging to files for audit trails:
  ```python
  HOST_LOG_FILE: str = "/var/log/kohakuriver/host.log"
  ```
- Monitor systemd journal for service health
- Set up alerts for node offline events
