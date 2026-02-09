---
title: Host API Reference
description: Complete reference of all KohakuRiver host server HTTP and WebSocket endpoints.
icon: i-carbon-cloud-service-management
---

# Host API Reference

The host server listens on port `8000` by default. All REST endpoints are prefixed with `/api`. WebSocket endpoints use the `/ws` prefix.

## Authentication

| Method | Path                                    | Description                                          |
| ------ | --------------------------------------- | ---------------------------------------------------- |
| GET    | `/api/auth/status`                      | Check if authentication is enabled                   |
| POST   | `/api/auth/login`                       | Login with username/password, returns session cookie |
| POST   | `/api/auth/logout`                      | Invalidate current session                           |
| GET    | `/api/auth/me`                          | Get current authenticated user info                  |
| POST   | `/api/auth/register`                    | Register new user with invitation token              |
| GET    | `/api/auth/tokens`                      | List API tokens for current user                     |
| POST   | `/api/auth/tokens/create`               | Create a new API token                               |
| DELETE | `/api/auth/tokens/{token_id}`           | Delete an API token                                  |
| GET    | `/api/auth/invitations`                 | List invitations (admin)                             |
| POST   | `/api/auth/invitations`                 | Create invitation (admin)                            |
| DELETE | `/api/auth/invitations/{invitation_id}` | Delete invitation (admin)                            |
| GET    | `/api/auth/users`                       | List all users (admin)                               |
| PATCH  | `/api/auth/users/{user_id}`             | Update user role/status (admin)                      |
| DELETE | `/api/auth/users/{user_id}`             | Delete a user (admin)                                |

## Nodes and Health

| Method | Path                        | Description                                                                            |
| ------ | --------------------------- | -------------------------------------------------------------------------------------- |
| POST   | `/api/register`             | Register a runner node with the host                                                   |
| PUT    | `/api/heartbeat/{hostname}` | Receive heartbeat from a runner, reconcile task states                                 |
| GET    | `/api/nodes`                | Get status of all registered nodes                                                     |
| GET    | `/api/health`               | Get cluster health metrics (60s history at 1s intervals). Optional `?hostname=` filter |

## Task Submission and Querying

| Method | Path                    | Description                                                                    |
| ------ | ----------------------- | ------------------------------------------------------------------------------ |
| POST   | `/api/submit`           | Submit a task (command or VPS type). Returns 202. Requires `user` role         |
| POST   | `/api/update`           | Receive task status update from runner (runner-to-host)                        |
| GET    | `/api/status/{task_id}` | Get task status and details                                                    |
| GET    | `/api/tasks`            | List command tasks. Requires `viewer` role. Optional `?status=&limit=&offset=` |
| GET    | `/api/tasks/my`         | List tasks owned by current user. Requires `user` role                         |

## Task Control and Approval

| Method | Path                               | Description                                            |
| ------ | ---------------------------------- | ------------------------------------------------------ |
| POST   | `/api/kill/{task_id}`              | Kill a running task. Returns 202                       |
| POST   | `/api/command/{task_id}/{command}` | Send pause/resume to a task                            |
| GET    | `/api/tasks/{task_id}/stdout`      | Get task stdout (plain text). Optional `?lines=`       |
| GET    | `/api/tasks/{task_id}/stderr`      | Get task stderr (plain text). Optional `?lines=`       |
| GET    | `/api/tasks/pending-approval`      | List tasks awaiting approval. Requires `operator` role |
| POST   | `/api/approve/{task_id}`           | Approve a pending task and dispatch to runner          |
| POST   | `/api/reject/{task_id}`            | Reject a pending task. Optional `?reason=`             |

## VPS Management

| Method | Path                                  | Description                                                         |
| ------ | ------------------------------------- | ------------------------------------------------------------------- |
| POST   | `/api/vps/create`                     | Create a new VPS (Docker or QEMU backend). Requires `operator` role |
| POST   | `/api/vps/stop/{task_id}`             | Stop a VPS instance. Returns 202                                    |
| POST   | `/api/vps/restart/{task_id}`          | Restart a VPS (Docker recreate or QMP reset). Returns 202           |
| GET    | `/api/vps`                            | List all VPS tasks. Requires `viewer` role                          |
| GET    | `/api/vps/status`                     | List active VPS instances only                                      |
| GET    | `/api/vps/my`                         | List VPS instances assigned to current user                         |
| POST   | `/api/vps/{task_id}/assign`           | Assign users to a VPS. Body: `user_ids[]`. Requires `operator` role |
| DELETE | `/api/vps/{task_id}/assign/{user_id}` | Unassign user from VPS                                              |
| GET    | `/api/vps/{task_id}/assignments`      | List users assigned to a VPS                                        |

## VPS Snapshots (proxied to runner)

| Method | Path                                       | Description                             |
| ------ | ------------------------------------------ | --------------------------------------- |
| GET    | `/api/vps/snapshots/{task_id}`             | List all snapshots for a VPS            |
| POST   | `/api/vps/snapshots/{task_id}`             | Create a snapshot (VPS must be running) |
| GET    | `/api/vps/snapshots/{task_id}/latest`      | Get latest snapshot info                |
| DELETE | `/api/vps/snapshots/{task_id}/{timestamp}` | Delete a specific snapshot              |
| DELETE | `/api/vps/snapshots/{task_id}`             | Delete all snapshots for a VPS          |

## VM Instance Management

| Method | Path                              | Description                                                                    |
| ------ | --------------------------------- | ------------------------------------------------------------------------------ |
| GET    | `/api/vm/images/{hostname}`       | List VM base images on a runner. Requires `viewer` role                        |
| GET    | `/api/vps/vm-instances`           | List VM instances across all nodes with DB cross-reference. Requires `admin`   |
| DELETE | `/api/vps/vm-instances/{task_id}` | Delete a VM instance directory. Optional `?hostname=&force=`. Requires `admin` |

## Docker and Container Tarballs

| Method | Path                                  | Description                                                              |
| ------ | ------------------------------------- | ------------------------------------------------------------------------ |
| GET    | `/api/docker/host/containers`         | List environment containers on the host                                  |
| POST   | `/api/docker/host/create`             | Create a new environment container. Body: `{image_name, container_name}` |
| POST   | `/api/docker/host/start/{env_name}`   | Start a stopped environment container                                    |
| POST   | `/api/docker/host/stop/{env_name}`    | Stop a running environment container                                     |
| POST   | `/api/docker/host/delete/{env_name}`  | Delete an environment container                                          |
| POST   | `/api/docker/host/migrate/{old_name}` | Migrate container to `kohakuriver-env-` naming                           |
| GET    | `/api/docker/list`                    | List container tarballs in shared storage                                |
| POST   | `/api/docker/create_tar/{env_name}`   | Create a tarball from an environment container                           |
| GET    | `/api/docker/container/{name}`        | Download a container tarball                                             |
| DELETE | `/api/docker/container/{name}`        | Delete a container tarball                                               |

## Container Filesystem

Task container filesystem operations are proxied to the runner hosting the task. Host container filesystem operations execute directly on the host. Both support the same operations: `list`, `read`, `write`, `mkdir`, `rename`, `delete`, `stat`.

| Method | Path                              | Description                                                         |
| ------ | --------------------------------- | ------------------------------------------------------------------- |
| GET    | `/api/fs/{task_id}/list`          | List directory in a task container (proxied). `?path=&show_hidden=` |
| GET    | `/api/fs/{task_id}/read`          | Read file from task container. `?path=&encoding=&limit=`            |
| POST   | `/api/fs/{task_id}/write`         | Write file to task container                                        |
| POST   | `/api/fs/{task_id}/mkdir`         | Create directory in task container                                  |
| POST   | `/api/fs/{task_id}/rename`        | Rename/move in task container                                       |
| DELETE | `/api/fs/{task_id}/delete`        | Delete in task container. `?path=&recursive=`                       |
| GET    | `/api/fs/{task_id}/stat`          | Get file metadata in task container                                 |
| GET    | `/api/fs/container/{name}/list`   | List directory in host environment container (direct)               |
| GET    | `/api/fs/container/{name}/read`   | Read file from host container                                       |
| POST   | `/api/fs/container/{name}/write`  | Write file to host container                                        |
| DELETE | `/api/fs/container/{name}/delete` | Delete in host container                                            |
| GET    | `/api/fs/container/{name}/stat`   | Get file metadata in host container                                 |

## Overlay Network and IP Reservation

| Method | Path                                 | Description                                        |
| ------ | ------------------------------------ | -------------------------------------------------- |
| GET    | `/api/overlay/status`                | Get overlay network status and allocations         |
| POST   | `/api/overlay/release/{runner_name}` | Release overlay allocation for a runner            |
| POST   | `/api/overlay/cleanup`               | Force cleanup inactive overlay allocations         |
| GET    | `/api/overlay/ip/available`          | Get available IPs. `?runner=&limit=`               |
| GET    | `/api/overlay/ip/info/{runner_name}` | Get IP allocation info for a runner                |
| POST   | `/api/overlay/ip/reserve`            | Reserve an IP. `?runner=&ip=&ttl=`                 |
| POST   | `/api/overlay/ip/release`            | Release IP reservation. `?token=`                  |
| GET    | `/api/overlay/ip/reservations`       | List active reservations. `?runner=&include_used=` |
| POST   | `/api/overlay/ip/validate`           | Validate reservation token. `?token=&runner=`      |
| GET    | `/api/overlay/ip/stats`              | Get IP reservation statistics                      |

## WebSocket Endpoints

| Path                                                   | Description                                                |
| ------------------------------------------------------ | ---------------------------------------------------------- |
| `/ws/docker/host/containers/{container_name}/terminal` | Interactive terminal to host environment container         |
| `/ws/task/{task_id}/terminal`                          | Terminal proxy to task/VPS container on runner             |
| `/ws/fs/{task_id}/watch`                               | Filesystem change notifications proxy. `?paths=`           |
| `/ws/forward/{task_id}/{port}`                         | Port forwarding to container via tunnel. `?proto=tcp\|udp` |
