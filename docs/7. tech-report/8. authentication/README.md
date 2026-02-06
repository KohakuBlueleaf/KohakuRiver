# KohakuRiver Authentication

Role-based authentication and authorization system for securing cluster access.

## Documents

| Document | Description |
|----------|-------------|
| [overview.md](overview.md) | Auth architecture, role hierarchy, sessions, API tokens, invitations, groups, and authorization |

## Quick Reference

### Role Hierarchy

```
ADMIN (40)  ──  Full system control
    |
OPERATOR (30)  ──  Manage tasks, approve submissions, assign VPS
    |
USER (20)  ──  Submit tasks (require approval), use assigned VPS
    |
VIEWER (10)  ──  Read-only access to dashboard and task status
    |
ANONY (0)  ──  Unauthenticated / minimal access
```

### Authentication Methods

| Method | Mechanism | Use Case |
|--------|-----------|----------|
| Session cookie | `kohakuriver_session` cookie set on login | Web dashboard, browser-based access |
| API token | `Authorization: Bearer <token>` header | CLI, scripts, programmatic access |
| Admin secret | `X-Admin-Token` header | Bootstrap operations before first user exists |

### Key Components

| Component | Path | Role |
|-----------|------|------|
| Auth Models | `src/kohakuriver/db/auth.py` | Peewee ORM models (User, Session, Token, Invitation, Group, etc.) |
| Auth Routes | `src/kohakuriver/host/auth/routes.py` | FastAPI endpoints for login, register, tokens, invitations |
| Auth Dependencies | `src/kohakuriver/host/auth/dependencies.py` | FastAPI dependencies for user extraction and role checking |
| Auth Utilities | `src/kohakuriver/host/auth/utils.py` | Password hashing (bcrypt), token generation, SHA3-512 hashing |
| Auth CLI | `src/kohakuriver/cli/commands/auth.py` | CLI commands for login, token management |

### Database Tables

| Table | Model | Purpose |
|-------|-------|---------|
| `users` | User | Registered user accounts |
| `sessions` | Session | Active login sessions |
| `tokens` | Token | API tokens (hash only) |
| `invitations` | Invitation | Registration invitation tokens |
| `groups` | Group | Resource quota groups |
| `user_groups` | UserGroup | User-to-group membership |
| `vps_assignments` | VpsAssignment | VPS access grants |
