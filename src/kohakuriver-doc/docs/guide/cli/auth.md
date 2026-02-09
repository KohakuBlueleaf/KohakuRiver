---
title: kohakuriver auth
description: Authentication commands for login, tokens, and session management.
icon: i-carbon-locked
---

# kohakuriver auth

The `kohakuriver auth` command group manages authentication when the host has `AUTH_ENABLED = True`.

## Commands

### auth login

Authenticate with the host.

```bash
kohakuriver auth login [options]
```

| Flag           | Default | Description                      |
| -------------- | ------- | -------------------------------- |
| `--username`   | Prompt  | Username                         |
| `--password`   | Prompt  | Password                         |
| `--token`      | None    | Login with an API token instead  |
| `--token-name` | None    | Name for the token-based session |

Examples:

```bash
# Interactive login (prompts for credentials)
kohakuriver auth login

# Non-interactive login
kohakuriver auth login --username admin --password mypassword

# Login with API token
kohakuriver auth login --token "tok_abc123"
```

On success, the session token is stored locally and used for all subsequent API requests.

### auth logout

End the current session.

```bash
kohakuriver auth logout [options]
```

| Flag       | Default | Description                               |
| ---------- | ------- | ----------------------------------------- |
| `--revoke` | `False` | Also revoke the session token server-side |

Examples:

```bash
# Local logout (remove stored token)
kohakuriver auth logout

# Logout and revoke server-side
kohakuriver auth logout --revoke
```

### auth status

Show current authentication status.

```bash
kohakuriver auth status
```

Displays:

- Whether you are logged in
- Username
- User role (anony, viewer, user, operator, admin)
- Session expiry time

### auth token

API token management subcommands:

#### token list

```bash
kohakuriver auth token list
```

Lists all API tokens for the current user with name, creation date, and last used date.

#### token create

```bash
kohakuriver auth token create <name>
```

Creates a new API token. The token string is displayed once and cannot be retrieved later.

#### token revoke

```bash
kohakuriver auth token revoke <token_name>
```

Revokes an API token, making it permanently invalid.

## User Roles

| Role       | Permissions                                     |
| ---------- | ----------------------------------------------- |
| `anony`    | No access (authentication required)             |
| `viewer`   | Read-only access to nodes and tasks             |
| `user`     | Submit tasks (require approval), view own tasks |
| `operator` | Full task/VPS management, approve user tasks    |
| `admin`    | Everything + user management + system settings  |

## Session Storage

Session tokens are stored in `~/.kohakuriver/session`. The file contains the authentication token that is sent with each API request in the `Authorization` header.

## Related Topics

- [Authentication](../setup/authentication.md) -- Auth system setup
- [Admin Panel](../web-dashboard/admin-panel.md) -- Web-based user management
- [User Management](../admin/user-management.md) -- CLI user administration
