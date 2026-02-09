---
title: Admin Panel
description: User management and administration through the web dashboard.
icon: i-carbon-user-admin
---

# Admin Panel

The admin panel in the web dashboard provides user management, task approval, and system administration features. It is available when `AUTH_ENABLED = True` in the host configuration.

## Access Control

The admin panel is accessible based on user roles:

| Feature         | Viewer | User | Operator | Admin |
| --------------- | ------ | ---- | -------- | ----- |
| View nodes      | Yes    | Yes  | Yes      | Yes   |
| View tasks      | Yes    | Yes  | Yes      | Yes   |
| Submit tasks    | No     | Yes  | Yes      | Yes   |
| Approve tasks   | No     | No   | Yes      | Yes   |
| Manage VPS      | No     | No   | Yes      | Yes   |
| Manage users    | No     | No   | No       | Yes   |
| System settings | No     | No   | No       | Yes   |

## User Management

Admins can manage users through the admin panel:

### User List

Displays all registered users with:

- Username
- Role (anony, viewer, user, operator, admin)
- Group memberships
- Created date
- Last login
- Active sessions count

### Create Users

1. Click "Create User"
2. Enter username and password
3. Select role
4. Optionally assign to groups
5. Click "Create"

### Modify User Role

1. Click a user in the list
2. Select new role from the dropdown
3. Click "Save"

Role changes take effect immediately. Active sessions are updated on next API request.

### Delete Users

Remove a user account. This also:

- Revokes all active sessions
- Revokes all API tokens
- Does not delete tasks submitted by the user

## Task Approval Queue

When users with the `user` role submit tasks, they enter `pending_approval` state. The approval queue shows:

- Task command and arguments
- Requested resources (cores, memory, GPUs)
- Target node
- Submitting user
- Submission timestamp

Operators and admins can:

- **Approve**: The task proceeds to scheduling
- **Reject**: The task is marked as `rejected` with an optional reason

A notification badge on the admin panel icon shows the count of pending approvals.

## Token Management

API tokens provide programmatic access without session-based authentication:

### View Tokens

List all tokens for all users (admin only) or for the current user:

- Token name
- Owner
- Creation date
- Last used date
- Expiry date (if set)

### Create Tokens

1. Click "Create Token"
2. Enter a descriptive name
3. Set optional expiry
4. Click "Create"
5. Copy the generated token (shown only once)

### Revoke Tokens

Click "Revoke" on a token to invalidate it immediately. Subsequent API requests using the token are rejected.

## Group Management

Groups provide organizational structure for users:

- Create and delete groups
- Assign users to groups
- Groups can be used for VPS assignment policies

### VPS Assignment

VPS instances can be assigned to specific users or groups, restricting who can access them. This is configured through the admin panel or API.

## Initial Admin Setup

When `AUTH_ENABLED = True`, the first admin account is created using the `ADMIN_REGISTER_SECRET`:

```bash
kohakuriver auth login --username admin --password <password>
```

Or register a new admin via the API with the secret:

```bash
curl -X POST http://host:8000/api/auth/register \
    -H "Content-Type: application/json" \
    -d '{"username": "admin", "password": "...", "register_secret": "<ADMIN_REGISTER_SECRET>"}'
```

The `ADMIN_SECRET` in the host config provides a master key for administrative operations without user authentication.

## Invitation System

Admins can create invitation codes for new user registration:

1. Go to the admin panel "Invitations" section
2. Click "Create Invitation"
3. Set the target role for invited users
4. Share the invitation code
5. New users register using the invitation code

This prevents unauthorized user registration while allowing controlled onboarding.

## Related Topics

- [Authentication](../setup/authentication.md) -- Auth system setup
- [Security Hardening](../setup/security-hardening.md) -- Security best practices
- [User Management](../admin/user-management.md) -- CLI-based user management
