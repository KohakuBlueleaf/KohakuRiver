---
title: Authentication
description: Setting up authentication, users, tokens, and role-based access control.
icon: i-carbon-locked
---

# Authentication

KohakuRiver supports optional role-based authentication. When disabled (default), all endpoints are public.

## Enabling Authentication

Set in `host_config.py`:

```python
AUTH_ENABLED: bool = True
ADMIN_SECRET: str = "your-bootstrap-secret"  # For creating first invitation
ADMIN_REGISTER_SECRET: str = "admin-register-key"  # For admin self-registration
```

## Role Hierarchy

| Role       | Level | Capabilities                                 |
| ---------- | ----- | -------------------------------------------- |
| `anony`    | 0     | Anonymous/unauthenticated access             |
| `viewer`   | 1     | Read-only access to cluster status           |
| `user`     | 2     | Submit tasks (may require operator approval) |
| `operator` | 3     | Manage VPS, approve tasks, manage users      |
| `admin`    | 4     | Full system access                           |

Higher roles inherit all permissions of lower roles.

## Initial Setup

### Option 1: Admin Self-Registration

If `ADMIN_REGISTER_SECRET` is set, navigate to the web dashboard and register using the secret as the invitation token. This creates the first admin account.

### Option 2: Bootstrap via Admin Secret

Use the `ADMIN_SECRET` to create an invitation via the API:

```bash
curl -X POST http://host:8000/api/auth/invitations/create \
    -H "X-Admin-Token: your-bootstrap-secret" \
    -H "Content-Type: application/json" \
    -d '{"role": "admin", "max_usage": 1}'
```

Use the returned invitation token to register.

## CLI Authentication

### Login

```bash
# Login with username and password (creates API token automatically)
kohakuriver auth login -u admin -p mypassword

# Login with existing API token
kohakuriver auth login --token YOUR_API_TOKEN

# Custom token name
kohakuriver auth login -u admin -p mypassword --token-name my-workstation
```

Login stores the API token in `~/.kohakuriver/auth.json` (mode 0600).

### Check Status

```bash
kohakuriver auth status
```

### Logout

```bash
# Logout (clear local credentials)
kohakuriver auth logout

# Logout and revoke the stored token on the server
kohakuriver auth logout --revoke
```

## API Token Management

```bash
# List your tokens
kohakuriver auth token list

# Create a new token
kohakuriver auth token create my-script-token

# Revoke a token by ID
kohakuriver auth token revoke 5
```

## User Management

Users are managed through invitations:

1. An operator/admin creates an invitation with a specific role
2. The invitation token is shared with the new user
3. The user registers using the token

## Task Approval Workflow

When `AUTH_ENABLED` is true:

- **User** role: Tasks are created in `pending_approval` state and require operator/admin approval
- **Operator/Admin** role: Tasks are auto-approved and dispatched immediately

Operators can approve or reject pending tasks via the API or web dashboard.

## Session Configuration

| Setting                   | Default       | Description                   |
| ------------------------- | ------------- | ----------------------------- |
| `SESSION_EXPIRE_HOURS`    | 720 (30 days) | Cookie session expiration     |
| `INVITATION_EXPIRE_HOURS` | 24 (1 day)    | Default invitation expiration |

## Authentication Methods

1. **Session cookies** (`kohakuriver_session`) -- Used by the web dashboard
2. **Bearer tokens** (`Authorization: Bearer TOKEN`) -- Used by the CLI and API clients
3. **Admin token** (`X-Admin-Token: SECRET`) -- For bootstrap operations only
