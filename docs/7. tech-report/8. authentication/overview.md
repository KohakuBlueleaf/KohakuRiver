# Authentication System Overview

## Auth Architecture

KohakuRiver uses an invitation-only, role-based authentication system built into the Host's FastAPI application. Authentication is optional and controlled by the `AUTH_ENABLED` configuration flag. When disabled, all requests are treated as admin-level access with no restrictions.

```
                          ┌────────────────────────────┐
                          │       Incoming Request      │
                          └─────────────┬──────────────┘
                                        │
                                        v
                              ┌─────────────────┐
                              │  AUTH_ENABLED?   │
                              └────────┬────────┘
                               No /         \ Yes
                                  v           v
                         ┌──────────┐   ┌────────────────────┐
                         │  Admin   │   │  Check X-Admin-     │
                         │  pseudo  │   │  Token header       │
                         │  user    │   └──────────┬─────────┘
                         └──────────┘      Match /     \ No match
                                              v         v
                                    ┌──────────┐  ┌──────────────┐
                                    │  Admin   │  │ Check session │
                                    │  pseudo  │  │ cookie        │
                                    │  user    │  └──────┬───────┘
                                    └──────────┘  Valid /   \ Invalid
                                                    v       v
                                           ┌────────┐ ┌──────────────┐
                                           │  User  │ │ Check Bearer │
                                           │  from  │ │ token        │
                                           │session │ └──────┬───────┘
                                           └────────┘ Valid /   \ Invalid
                                                        v       v
                                               ┌────────┐ ┌──────────┐
                                               │  User  │ │ Anonymous│
                                               │  from  │ │ pseudo   │
                                               │ token  │ │ user     │
                                               └────────┘ └──────────┘
```

The authentication chain checks credentials in priority order: admin secret header, session cookie, then Bearer token. If none match, an anonymous pseudo-user is returned.

---

## Role Hierarchy

Roles form a strict linear hierarchy. Each role includes all permissions of lower roles.

| Role | Level | Description | Key Permissions |
|------|-------|-------------|-----------------|
| ANONY | 0 | Unauthenticated | Minimal/no access; most endpoints return 401 |
| VIEWER | 10 | Read-only | View dashboard, task status, node information |
| USER | 20 | Standard user | Submit tasks (require operator approval), use assigned VPS |
| OPERATOR | 30 | Task manager | Manage tasks, approve/reject user submissions, assign VPS access, create viewer invitations |
| ADMIN | 40 | Full control | Manage users, groups, invitations for any role, all system settings |

Authorization is enforced via `UserRole.is_at_least(user_role, required_role)`, which compares index positions in the hierarchy list `[ANONY, VIEWER, USER, OPERATOR, ADMIN]`.

### FastAPI Dependency Injection

Pre-built dependencies simplify role enforcement in endpoint definitions:

```python
require_viewer   = require_role(UserRole.VIEWER)
require_user     = require_role(UserRole.USER)
require_operator = require_role(UserRole.OPERATOR)
require_admin    = require_role(UserRole.ADMIN)
```

Type aliases provide clean endpoint signatures:

```python
ViewerUser   = Annotated[User, Depends(require_viewer)]
AuthUser     = Annotated[User, Depends(require_user)]
OperatorUser = Annotated[User, Depends(require_operator)]
AdminUser    = Annotated[User, Depends(require_admin)]
```

An endpoint requiring operator access simply declares its parameter as `current_user: OperatorUser`. The dependency handles authentication, role checking, and appropriate HTTP error responses (401 for unauthenticated, 403 for insufficient role).

---

## User Model and Password Handling

### User Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | AutoField | Primary key |
| `username` | CharField(50) | Unique login identifier, indexed |
| `display_name` | CharField(100) | Optional display name |
| `password_hash` | CharField(255) | bcrypt hash of password |
| `role` | CharField(20) | One of the five role strings |
| `is_active` | BooleanField | Account enabled/disabled flag |
| `created_at` | DateTimeField | Registration timestamp |

Passwords are hashed with bcrypt before storage. Plaintext passwords are never persisted. The `verify_password()` utility compares a candidate password against the stored bcrypt hash.

An inactive user (`is_active=False`) is treated as unauthenticated regardless of valid session or token.

---

## Session-Based Authentication

Sessions power browser-based access through the web dashboard.

### Login Flow

```
Browser                      Host /auth/login
   |                              |
   |--- POST {username, password} |
   |                              |-- verify credentials
   |                              |-- generate session_id (random 64 chars)
   |                              |-- INSERT into sessions table
   |                              |-- set expires_at (configurable hours)
   |                              |
   |<-- Set-Cookie: kohakuriver_session=<session_id>
   |<-- 200 { message, user }     |
```

### Session Details

| Property | Value |
|----------|-------|
| Cookie name | `kohakuriver_session` |
| Cookie flags | `httponly=True`, `samesite=lax` |
| Session ID length | 64 characters (cryptographically random) |
| Expiration | Configurable via `SESSION_EXPIRE_HOURS` |
| Storage | `sessions` table in SQLite |

On each request, the dependency extracts the cookie, looks up the session in the database, checks expiration, verifies the user is active, and returns the `User` object. Expired sessions are deleted on access.

### Logout

`POST /auth/logout` deletes the session row from the database and clears the cookie, invalidating the session immediately.

---

## Token-Based Authentication

API tokens provide long-lived, programmatic access for the CLI, scripts, and automation.

### Token Creation

```
Authenticated User           Host /auth/tokens/create
       |                              |
       |--- POST { name: "my-cli" }   |
       |                              |-- generate 32-byte random token
       |                              |-- hash with SHA3-512
       |                              |-- INSERT token_hash into tokens table
       |                              |
       |<-- 200 { id, name, token }   |
       |       (plaintext token)      |
       |                              |
       NOTE: Plaintext is only returned this once.
             It cannot be recovered from the hash.
```

### Token Validation

On each request with `Authorization: Bearer <token>`:

1. Extract the token from the header.
2. Compute `SHA3-512(token)`.
3. Look up the hash in the `tokens` table.
4. Verify the associated user is active.
5. Update `last_used` timestamp.
6. Return the `User` object.

### Token Security Properties

| Property | Detail |
|----------|--------|
| Hash algorithm | SHA3-512 |
| Storage | Only the hash is stored; plaintext is never persisted |
| Revocation | Deleting the token row immediately invalidates it |
| Scoping | Token inherits the creating user's role |
| Tracking | `last_used` timestamp updated on each use |

---

## Invitation System

KohakuRiver is an invitation-only system. New users cannot self-register without a valid invitation token.

### Registration Flow

```
Admin / Operator              Host /auth/invitations
       |                              |
       |--- POST { role, max_usage,   |
       |    expires_hours, group_id }  |
       |                              |-- generate random invitation token
       |                              |-- INSERT into invitations table
       |<-- 200 { id, token, ... }    |
       |                              |
       |   (admin shares token with   |
       |    new user out of band)     |

New User                      Host /auth/register?token=<invitation_token>
       |                              |
       |--- POST { username,          |
       |    password, display_name }  |
       |                              |-- validate invitation (exists, not expired, has uses)
       |                              |-- create User with invitation's role
       |                              |-- increment invitation usage_count
       |                              |-- auto-login (create session, set cookie)
       |<-- 200 { message, user }     |
```

### Invitation Fields

| Field | Description |
|-------|-------------|
| `token` | Unique random string (64 chars), shared with invitee |
| `role` | Role assigned to users who register with this invitation |
| `group` | Optional group to auto-assign the new user to |
| `max_usage` | Maximum number of registrations allowed |
| `usage_count` | Current number of registrations completed |
| `expires_at` | Expiration timestamp |
| `created_by` | The admin/operator who created the invitation |

### Invitation Rules

| Role | Can create invitations? | Restriction |
|------|-------------------------|-------------|
| ADMIN | Yes | Any role |
| OPERATOR | Yes | Only `viewer` role invitations |
| USER | No | -- |
| VIEWER | No | -- |

### Bootstrap: First User

When no users exist yet, the system provides two bootstrap mechanisms:

1. **Admin Secret Header**: Requests with `X-Admin-Token: <ADMIN_SECRET>` are treated as admin. This allows creating the first invitation via the API.
2. **Admin Register Secret**: If `ADMIN_REGISTER_SECRET` is configured, using it as the invitation token during registration creates an admin account directly.

---

## Groups and Resource Quotas

Groups organize users and define resource limits for task submission.

### Group Model

| Field | Description |
|-------|-------------|
| `name` | Unique group name |
| `tier` | Integer tier level (higher = more privileges) |
| `limits_json` | JSON string containing resource quotas |

### Quota Structure

The `limits_json` field stores a JSON object with resource constraints:

```json
{
    "max_tasks": 10,
    "max_vps": 2,
    "gpu_cap": 4
}
```

Quotas are enforced at task submission time. When a user belongs to multiple groups, the system evaluates limits from all groups.

### User-Group Membership

The `UserGroup` join table supports:

- A user belonging to multiple groups.
- An optional `role_override` per group membership, allowing group-specific privilege escalation.
- Unique constraint on (user, group) pairs to prevent duplicates.

---

## VPS Assignment Model

VPS tasks can be shared among multiple users through explicit assignment. The `VpsAssignment` table provides a many-to-many relationship between VPS tasks and users.

| Field | Description |
|-------|-------------|
| `vps_task_id` | References `Task.task_id` (the VPS task) |
| `user` | Foreign key to the assigned user |

Operators create VPS assignments to grant specific users access to a VPS container. When a user attempts to connect to a VPS (via SSH proxy or WebSocket terminal), the system checks whether the user has an active assignment for that VPS task.

---

## Task Approval Workflow

Users with the `USER` role cannot directly run tasks. Their submissions enter a `PENDING_APPROVAL` state and require operator or admin approval:

```
USER submits task
      |
      v
PENDING_APPROVAL  ──(operator approves)──>  PENDING  ──>  ASSIGNING  ──>  RUNNING
      |
      └──(operator rejects)──>  REJECTED
```

Operators and admins can review pending tasks and either approve them (moving to `PENDING` for scheduling) or reject them. This provides a gatekeeping mechanism for resource usage in shared environments.

---

## Authorization Enforcement in Endpoints

### Endpoint Protection Matrix

| Endpoint | Required Role | Notes |
|----------|---------------|-------|
| `GET /auth/status` | None | Public; returns whether auth is enabled |
| `POST /auth/login` | None | Validates credentials, creates session |
| `POST /auth/logout` | None | Destroys session if present |
| `POST /auth/register` | None (requires invitation token) | Creates user, auto-login |
| `GET /auth/me` | Authenticated | Returns current user info |
| `GET /auth/tokens` | Authenticated | Lists own API tokens |
| `POST /auth/tokens/create` | Authenticated | Creates new API token |
| `DELETE /auth/tokens/{id}` | Authenticated | Revokes own token |
| `GET /auth/users` | OPERATOR+ | Lists all users |
| `PATCH /auth/users/{id}` | ADMIN | Modify user role, active status |
| `DELETE /auth/users/{id}` | ADMIN | Delete a user |
| `GET /auth/invitations` | ADMIN | Lists all invitations |
| `POST /auth/invitations` | OPERATOR+ | Creates invitation (operators: viewer only) |
| `DELETE /auth/invitations/{id}` | ADMIN | Revokes an invitation |
| Task submission | USER+ | USER tasks enter PENDING_APPROVAL |
| Task management | OPERATOR+ | Approve, reject, kill tasks |
| VPS assignment | OPERATOR+ | Grant users access to VPS |

### Safety Guards

The auth system includes several self-protection measures:

- Admins cannot demote their own role.
- Admins cannot disable their own account.
- Admins cannot delete their own account.
- Operators cannot create invitations for roles above `viewer`.
- Expired sessions are cleaned up on access rather than requiring a background job.
- Token hashes are stored with SHA3-512; even a database breach does not reveal plaintext tokens.
