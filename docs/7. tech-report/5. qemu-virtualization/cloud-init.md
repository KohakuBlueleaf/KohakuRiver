# Cloud-Init and VM Provisioning

## What is Cloud-Init

Cloud-init is the industry-standard system for early initialization of cloud and virtual machine instances. When a VM boots for the first time, cloud-init reads configuration from a data source (in our case, a virtual CDROM labeled `cidata`) and applies it before any user login. This allows KohakuRiver to inject user accounts, SSH keys, network settings, and the VM agent into a generic base image without creating per-task custom images.

### How KohakuRiver Uses Cloud-Init

```
┌──────────────────────────┐
│     Base qcow2 Image     │  Generic OS image with cloud-init installed
│    (shared, read-only)   │
└────────────┬─────────────┘
             │
             │  qemu-img create -b (overlay)
             ▼
┌──────────────────────────┐     ┌──────────────────────────┐
│   Instance root.qcow2   │     │       seed.iso           │
│   (copy-on-write)        │     │  (cloud-init config)     │
└────────────┬─────────────┘     │                          │
             │                   │  meta-data                │
             │                   │  user-data                │
             │                   │  network-config           │
             │                   └────────────┬─────────────┘
             │                                │
             └──────────┬─────────────────────┘
                        │  Both attached as drives
                        ▼
               ┌─────────────────┐
               │   QEMU VM       │
               │                 │
               │  cloud-init     │
               │  reads seed.iso │
               │  on first boot  │
               └─────────────────┘
```

---

## The Three Config Files

Cloud-init expects three files on the `cidata` volume. KohakuRiver generates all three from the `CloudInitConfig` dataclass.

### CloudInitConfig Fields

| Field | Example | Purpose |
|-------|---------|---------|
| `task_id` | `42` | KohakuRiver task identifier |
| `hostname` | `kohaku-vm-42` | VM hostname |
| `vm_ip` | `10.1.0.5` | Static IP address |
| `gateway` | `10.1.0.1` | Network gateway |
| `prefix_len` | `16` | Subnet prefix length |
| `dns_servers` | `["8.8.8.8", "1.1.1.1"]` | DNS resolvers |
| `ssh_public_key` | `ssh-ed25519 AAAA...` | User's SSH public key |
| `runner_url` | `http://10.1.0.1:8001` | Runner API URL for agent callbacks |

---

### 1. meta-data

Minimal instance identification:

```yaml
instance-id: kohaku-vm-42
local-hostname: kohaku-vm-42
```

The `instance-id` is critical: cloud-init uses it to determine whether this is a first boot or a subsequent boot. If the instance-id matches a previous run, cloud-init skips re-initialization. KohakuRiver generates a unique ID per task.

### 2. user-data

The user-data file is the primary configuration payload. It begins with the `#cloud-config` header and contains:

```yaml
#cloud-config
users:
  - name: kohaku
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...

  - name: root
    ssh_authorized_keys:
      - ssh-ed25519 AAAA...

ssh_pwauth: false

write_files:
  - path: /usr/local/bin/kohakuriver-vm-agent
    permissions: '0755'
    content: |
      #!/usr/bin/env python3
      ... (embedded agent script) ...

  - path: /etc/systemd/system/kohakuriver-vm-agent.service
    content: |
      [Unit]
      Description=KohakuRiver VM Agent
      After=network-online.target
      Wants=network-online.target

      [Service]
      Type=simple
      ExecStart=/usr/local/bin/kohakuriver-vm-agent
      Restart=always
      RestartSec=5
      Environment=KOHAKU_RUNNER_URL=http://10.1.0.1:8001
      Environment=KOHAKU_TASK_ID=42
      Environment=KOHAKU_HEARTBEAT_INTERVAL=10

      [Install]
      WantedBy=multi-user.target

runcmd:
  - systemctl daemon-reload
  - systemctl enable --now kohakuriver-vm-agent
```

#### User Accounts

| User | Purpose | SSH Key | Sudo |
|------|---------|---------|------|
| `kohaku` | Primary interactive user | Yes | ALL, NOPASSWD |
| `root` | Emergency access | Yes | N/A (root) |

Password authentication is disabled when an SSH key is provided (`ssh_pwauth: false`, `lock_passwd: true`). If no SSH key is set, password-less root login is enabled as a fallback.

#### Embedded Files

Two files are written to the VM filesystem via `write_files`:

1. **`/usr/local/bin/kohakuriver-vm-agent`**: The VM agent Python script (see below)
2. **`/etc/systemd/system/kohakuriver-vm-agent.service`**: The systemd unit that runs the agent

#### Boot Commands

The `runcmd` section executes after all other cloud-init modules. It reloads systemd and enables the VM agent service, which starts the phone-home and heartbeat loop.

### 3. network-config

Static network configuration using Netplan version 2 syntax:

```yaml
version: 2
ethernets:
  ens3:
    addresses:
      - 10.1.0.5/16
    gateway4: 10.1.0.1
    nameservers:
      addresses:
        - 8.8.8.8
        - 1.1.1.1
```

The interface name `ens3` corresponds to the first virtio-net device in QEMU. Cloud-init applies this configuration via Netplan, replacing any DHCP defaults from the base image.

---

## ISO Generation Process

The three config files are packaged into an ISO 9660 image with the volume label `cidata`. Cloud-init recognizes this label and reads the files automatically.

### Generation Flow

```
CloudInitConfig
      │
      ├── build_meta_data()    → meta-data (YAML)
      ├── build_user_data()    → user-data (YAML with #cloud-config header)
      └── build_network_config() → network-config (YAML)
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ Temporary directory                                         │
│  ├── meta-data                                              │
│  ├── user-data                                              │
│  └── network-config                                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ genisoimage (or mkisofs)                                    │
│                                                             │
│   genisoimage -output seed.iso                              │
│               -volid cidata                                 │
│               -joliet -rock                                 │
│               meta-data user-data network-config            │
│                                                             │
│   -volid cidata    → Volume label cloud-init looks for      │
│   -joliet          → Joliet extensions for long filenames   │
│   -rock            → Rock Ridge extensions for POSIX attrs  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
         /var/lib/kohakuriver/vm-instances/{task_id}/seed.iso
```

The ISO is attached to the VM as a read-only virtio CDROM drive. Cloud-init inside the guest detects the `cidata` volume label and processes the files during first boot.

### Tool Discovery

KohakuRiver checks for either `genisoimage` or `mkisofs` (they are compatible alternatives):

```python
iso_tool = shutil.which("genisoimage") or shutil.which("mkisofs")
```

If neither is found, a `CloudInitError` is raised during capability check.

---

## Embedded VM Agent

The VM agent is a self-contained Python script embedded directly in the cloud-init user-data. It has **no external dependencies** beyond the Python standard library (plus optional `pynvml` for GPU metrics). This ensures it works on any base image with Python 3 installed.

### Agent Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    VM Guest OS                                │
│                                                              │
│  systemd starts kohakuriver-vm-agent.service                 │
│       │                                                      │
│       ▼                                                      │
│  ┌──────────────────────────────────────────────┐            │
│  │         kohakuriver-vm-agent                  │            │
│  │                                               │            │
│  │  1. phone_home()                              │            │
│  │     POST /api/vps/{task_id}/vm-phone-home ────┼───► Runner │
│  │                                               │            │
│  │  2. Loop forever:                             │            │
│  │     send_heartbeat()                          │            │
│  │       ├── get_gpu_info()  (pynvml)            │            │
│  │       ├── get_system_info() (/proc, shutil)   │            │
│  │       └── POST /api/vps/{task_id}/vm-heartbeat┼───► Runner │
│  │     sleep(HEARTBEAT_INTERVAL)                 │            │
│  └──────────────────────────────────────────────┘            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Environment Variables

The agent reads its configuration from environment variables set by the systemd unit:

| Variable | Example | Purpose |
|----------|---------|---------|
| `KOHAKU_RUNNER_URL` | `http://10.1.0.1:8001` | Runner API base URL |
| `KOHAKU_TASK_ID` | `42` | Task identifier |
| `KOHAKU_HEARTBEAT_INTERVAL` | `10` | Seconds between heartbeats |

### Agent Lifecycle

```
Agent starts
    │
    ├── Check KOHAKU_TASK_ID is set (exit 1 if not)
    │
    ├── phone_home()
    │     POST /api/vps/{task_id}/vm-phone-home
    │     (no body, just a signal)
    │
    └── Heartbeat loop (infinite)
          │
          ├── get_gpu_info()
          │     pynvml: per-GPU utilization, memory, temperature,
          │     fan speed, power, clocks
          │
          ├── get_system_info()
          │     /proc/meminfo: total + available memory
          │     shutil.disk_usage("/"): disk total + used
          │     /proc/loadavg: 1-minute load average
          │
          ├── POST /api/vps/{task_id}/vm-heartbeat
          │     {task_id, timestamp, status, gpus[], system{}}
          │
          └── sleep(HEARTBEAT_INTERVAL)
```

---

## Phone-Home Mechanism

Phone-home is the signal that tells the Runner the VM guest has fully booted and the agent is operational. This is critical because QEMU starting successfully only means the hypervisor is running -- it says nothing about whether the guest OS has initialized.

### Timeline

```
t=0     QEMU process starts
        │
t=5s    UEFI firmware loads, GRUB starts
        │
t=15s   Linux kernel boots, systemd starts services
        │
t=20s   cloud-init runs:
        │  - Creates users
        │  - Writes SSH keys
        │  - Writes agent script
        │  - Configures network (ens3)
        │  - Enables agent service
        │
t=25s   kohakuriver-vm-agent starts
        │
t=25s   phone_home() ──────────────────► Runner
        │                                  │
        │                         Task state → RUNNING
        │
t=25s   Heartbeat loop begins
        │
t=30s   SSH daemon ready (port 22)
        │                                  │
        │                         vm.ssh_ready = True
```

The Runner waits for phone-home with a configurable timeout. If phone-home is not received, the task transitions to FAILED.

---

## Metrics Collected

### GPU Metrics (via pynvml)

| Metric | Field | Unit |
|--------|-------|------|
| GPU utilization | `gpu_utilization` | Percent |
| Memory utilization | `mem_utilization` | Percent |
| Graphics clock | `graphics_clock_mhz` | MHz |
| Memory clock | `mem_clock_mhz` | MHz |
| Memory total | `memory_total_mib` | MiB |
| Memory used | `memory_used_mib` | MiB |
| Memory free | `memory_free_mib` | MiB |
| Temperature | `temperature` | Celsius |
| Fan speed | `fan_speed` | Percent |
| Power usage | `power_usage_mw` | Milliwatts |
| Power limit | `power_limit_mw` | Milliwatts |
| Driver version | `driver_version` | String |
| PCI bus ID | `pci_bus_id` | String |

If `pynvml` is not installed inside the VM, the `gpus` array in the heartbeat is empty. This is expected for VMs without GPU passthrough.

### System Metrics (via /proc and stdlib)

| Metric | Field | Source |
|--------|-------|--------|
| Total memory | `memory_total_bytes` | `/proc/meminfo` (MemTotal) |
| Used memory | `memory_used_bytes` | MemTotal - MemAvailable |
| Total disk | `disk_total_bytes` | `shutil.disk_usage("/")` |
| Used disk | `disk_used_bytes` | `shutil.disk_usage("/")` |
| Load average (1m) | `load_1m` | `/proc/loadavg` |

### Heartbeat Payload Example

```json
{
    "task_id": 42,
    "timestamp": 1706200000.0,
    "status": "healthy",
    "gpus": [
        {
            "gpu_id": 0,
            "name": "NVIDIA GeForce RTX 4090",
            "driver_version": "550.54.14",
            "pci_bus_id": "0000:01:00.0",
            "gpu_utilization": 85,
            "mem_utilization": 60,
            "graphics_clock_mhz": 2520,
            "mem_clock_mhz": 10501,
            "memory_total_mib": 24564.0,
            "memory_used_mib": 14738.0,
            "memory_free_mib": 9826.0,
            "temperature": 72,
            "fan_speed": 65,
            "power_usage_mw": 350000,
            "power_limit_mw": 450000
        }
    ],
    "system": {
        "memory_total_bytes": 17179869184,
        "memory_used_bytes": 4294967296,
        "disk_total_bytes": 53687091200,
        "disk_used_bytes": 8589934592,
        "load_1m": 2.4
    }
}
```

---

## Error Handling

| Error | Cause | Effect |
|-------|-------|--------|
| `CloudInitError`: ISO tool not found | `genisoimage` and `mkisofs` both missing | VM creation fails at capability check |
| `CloudInitError`: ISO creation failed | Disk full, permission denied, corrupt temp files | VM creation fails; instance directory preserved for debugging |
| `CloudInitError`: ISO creation timed out | ISO tool hung (30s timeout) | VM creation fails |
| Agent phone-home timeout | Guest OS failed to boot, network misconfiguration | Task transitions to FAILED |
| Agent heartbeat failure | Network partition between VM and Runner | Runner marks VM as LOST after missed heartbeats |

The agent itself is resilient: `Restart=always` in the systemd unit ensures it restarts on crash, and all HTTP calls have a 5-second timeout to avoid blocking on network issues.
