---
title: Runner API Reference
description: Complete reference of all KohakuRiver runner server HTTP and WebSocket endpoints.
icon: i-carbon-server-proxy
---

# Runner API Reference

The runner server listens on port `8001` by default. All REST endpoints are prefixed with `/api`. WebSocket endpoints use the `/ws` prefix. Runner endpoints are typically called by the host or other internal services, not directly by end users.

## Task Execution

| Method | Path           | Description                                                                       |
| ------ | -------------- | --------------------------------------------------------------------------------- |
| POST   | `/api/execute` | Accept and execute a task in a Docker container. Called by host to dispatch tasks |
| POST   | `/api/kill`    | Kill a running task. Body: `{task_id, container_name}`                            |
| POST   | `/api/pause`   | Pause a running task container                                                    |
| POST   | `/api/resume`  | Resume a paused task container                                                    |

### Execute Request Body

```json
{
  "task_id": 123456789,
  "command": "/bin/bash script.sh",
  "arguments": ["--flag"],
  "env_vars": { "KEY": "value" },
  "required_cores": 4,
  "required_gpus": [0, 1],
  "required_memory_bytes": 8589934592,
  "target_numa_node_id": 0,
  "container_name": "kohakuriver-base",
  "registry_image": null,
  "working_dir": "/shared",
  "stdout_path": "/shared/logs/123/stdout.log",
  "stderr_path": "/shared/logs/123/stderr.log",
  "reserved_ip": null
}
```

## VPS Management

| Method | Path                        | Description                                                        |
| ------ | --------------------------- | ------------------------------------------------------------------ |
| POST   | `/api/vps/create`           | Create a VPS container or VM. Dispatches to Docker or QEMU backend |
| POST   | `/api/vps/stop/{task_id}`   | Stop a running VPS (Docker or VM)                                  |
| POST   | `/api/vps/pause/{task_id}`  | Pause a running VPS container                                      |
| POST   | `/api/vps/resume/{task_id}` | Resume a paused VPS container                                      |

### VPS Create Request Body

```json
{
  "task_id": 123456789,
  "required_cores": 4,
  "required_gpus": [0],
  "required_memory_bytes": null,
  "target_numa_node_id": null,
  "container_name": "kohakuriver-base",
  "registry_image": null,
  "ssh_key_mode": "upload",
  "ssh_public_key": "ssh-ed25519 AAAA...",
  "ssh_port": 2222,
  "vps_backend": "docker",
  "vm_image": null,
  "vm_disk_size": null,
  "memory_mb": null,
  "reserved_ip": null
}
```

## VPS Snapshots

| Method | Path                                       | Description                                   |
| ------ | ------------------------------------------ | --------------------------------------------- |
| GET    | `/api/vps/snapshots/{task_id}`             | List all snapshots for a VPS                  |
| POST   | `/api/vps/snapshots/{task_id}`             | Create a snapshot. Optional body: `{message}` |
| GET    | `/api/vps/snapshots/{task_id}/latest`      | Get latest snapshot tag                       |
| DELETE | `/api/vps/snapshots/{task_id}/{timestamp}` | Delete a specific snapshot                    |
| DELETE | `/api/vps/snapshots/{task_id}`             | Delete all snapshots for a VPS                |

## VM-Specific Endpoints

| Method | Path                               | Description                                                |
| ------ | ---------------------------------- | ---------------------------------------------------------- |
| GET    | `/api/vm/images`                   | List available VM base images (qcow2 files) on this runner |
| GET    | `/api/vps/{task_id}/vm-status`     | Get QEMU VM status                                         |
| POST   | `/api/vps/{task_id}/vm-restart`    | Restart VM via QMP system_reset                            |
| POST   | `/api/vps/{task_id}/vm-heartbeat`  | Receive heartbeat from VM agent inside guest               |
| POST   | `/api/vps/{task_id}/vm-phone-home` | Receive cloud-init phone-home callback from VM             |

## VM Instance Management

| Method | Path                              | Description                                                              |
| ------ | --------------------------------- | ------------------------------------------------------------------------ |
| GET    | `/api/vps/vm-instances`           | List all VM instance directories with disk usage                         |
| DELETE | `/api/vps/vm-instances/{task_id}` | Delete a VM instance directory. `?force=true` to stop running QEMU first |

## Docker Image Management

| Method | Path                                | Description                                        |
| ------ | ----------------------------------- | -------------------------------------------------- |
| GET    | `/api/docker/images`                | List locally available Docker images               |
| POST   | `/api/docker/sync/{container_name}` | Sync a container image from shared storage tarball |

## Container Filesystem

| Method | Path                       | Description                                                                |
| ------ | -------------------------- | -------------------------------------------------------------------------- |
| GET    | `/api/fs/{task_id}/list`   | List directory in a running task container. `?path=&show_hidden=`          |
| GET    | `/api/fs/{task_id}/read`   | Read file from container. `?path=&encoding=&limit=`                        |
| POST   | `/api/fs/{task_id}/write`  | Write file to container. Body: `{path, content, encoding, create_parents}` |
| POST   | `/api/fs/{task_id}/mkdir`  | Create directory. Body: `{path, parents}`                                  |
| POST   | `/api/fs/{task_id}/rename` | Rename/move. Body: `{source, destination, overwrite}`                      |
| DELETE | `/api/fs/{task_id}/delete` | Delete file/directory. `?path=&recursive=`                                 |
| GET    | `/api/fs/{task_id}/stat`   | Get file metadata. `?path=`                                                |

### Filesystem Limits

| Limit                 | Value                   |
| --------------------- | ----------------------- |
| Max file read size    | 10 MB                   |
| Max file write size   | 50 MB                   |
| Max directory entries | 1000                    |
| Forbidden paths       | `/proc`, `/sys`, `/dev` |

## WebSocket Endpoints

| Path                                | Description                                                               |
| ----------------------------------- | ------------------------------------------------------------------------- |
| `/ws/task/{task_id}/terminal`       | Interactive terminal to a running task/VPS container or VM (via SSH)      |
| `/ws/fs/{task_id}/watch`            | Real-time filesystem change notifications via inotifywait. `?paths=`      |
| `/ws/tunnel/{container_id}`         | Tunnel-client WebSocket endpoint. Used by tunnel binary inside containers |
| `/ws/forward/{container_id}/{port}` | Port forwarding to a container service. `?proto=tcp\|udp`                 |

## Internal Communication Flow

The host dispatches work to runners and queries status through this API:

1. Host calls `POST /api/execute` or `POST /api/vps/create` to start workloads
2. Runner reports status back via `POST /api/update` on the host
3. Host calls `POST /api/kill`, `/api/pause`, `/api/resume` for lifecycle control
4. Host proxies filesystem, terminal, and snapshot requests to the appropriate runner
5. Tunnel-client binaries inside containers connect to `/ws/tunnel/{container_id}` for port forwarding
