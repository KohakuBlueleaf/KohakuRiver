# QEMU VM Architecture Overview

## Motivation: VMs Alongside Docker

KohakuRiver's primary workload engine is Docker. Containers are fast, lightweight, and sufficient for most tasks. However, certain workloads require stronger isolation or capabilities that containers cannot provide:

| Requirement | Docker | QEMU/KVM |
|-------------|--------|----------|
| Full kernel isolation | Shared host kernel | Independent guest kernel |
| Nested Docker / Kubernetes | Not supported | Fully supported |
| Exclusive GPU passthrough | Shared via NVIDIA CTK | Hardware-level via VFIO |
| Custom kernel modules | Not possible | Full control |
| Untrusted workloads | Namespace escape risk | Hardware isolation boundary |

QEMU VMs fill this gap. They run as an alternative VPS engine on the same Runner infrastructure, reusing the existing task scheduler, networking overlay, and monitoring pipeline.

---

## QEMUManager Design

The `QEMUManager` class (`src/kohakuriver/qemu/client.py`) follows the same pattern as the Docker-based task executor: a singleton manager that tracks running workloads and provides lifecycle operations.

### Class Structure

```
QEMUManager
├── _vms: dict[int, VMInstance]     # task_id → running VM state
├── _lock: asyncio.Lock             # Protects concurrent VM operations
│
├── create_vm(options) → VMInstance  # Full creation pipeline
├── stop_vm(task_id, timeout)        # Graceful shutdown → force kill
├── kill_vm(task_id)                 # Immediate SIGKILL
├── restart_vm(task_id)              # QMP system_reset
│
├── get_vm(task_id)                  # Lookup by task ID
├── list_vms()                       # All tracked VMs
├── vm_exists(task_id)               # Existence check
│
├── qmp_command(task_id, cmd)        # Raw QMP command
├── qmp_shutdown(task_id)            # system_powerdown
└── qmp_reset(task_id)              # system_reset
```

### VMInstance State

Each running VM is tracked as a `VMInstance` dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `int` | KohakuRiver task ID |
| `pid` | `int` | QEMU process PID |
| `vm_ip` | `str` | Overlay or NAT IP address |
| `tap_device` | `str` | TAP network interface name |
| `gpu_pci_addresses` | `list[str]` | PCI addresses of passed-through GPUs |
| `instance_dir` | `str` | Path to instance directory |
| `qmp_socket` | `str` | Path to QMP Unix socket |
| `ssh_ready` | `bool` | Whether SSH port 22 is accepting connections |
| `last_heartbeat` | `float` | Timestamp of last agent heartbeat |

### VMCreateOptions

Options are passed to `create_vm()` as a `VMCreateOptions` dataclass:

| Field | Description |
|-------|-------------|
| `task_id` | Task identifier |
| `base_image` | Name of qcow2 base image (without extension) |
| `cores` | Number of vCPUs |
| `memory_mb` | RAM in megabytes |
| `disk_size` | Disk size string (e.g., `"50G"`) |
| `gpu_pci_addresses` | GPUs to pass through |
| `ssh_public_key` | SSH key for user authentication |
| `vm_ip` | IP address to assign |
| `tap_device` | Pre-created TAP interface |
| `gateway` | Network gateway IP |
| `prefix_len` | Subnet prefix length |
| `dns_servers` | DNS server addresses |
| `runner_url` | Runner API URL (for VM agent callbacks) |

---

## VM Creation Flow

The full creation pipeline executed by `QEMUManager.create_vm()`:

```
VMCreateOptions
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 1. INSTANCE DIRECTORY                                            │
│    Create /var/lib/kohakuriver/vm-instances/{task_id}/           │
│    Create /run/kohakuriver/vm/ for QMP socket                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 2. OVERLAY DISK                                                  │
│    qemu-img create -f qcow2 -b <base>.qcow2 -F qcow2 root.qcow2│
│    qemu-img resize root.qcow2 <disk_size>                       │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 3. VFIO GPU BINDING                                              │
│    For each GPU PCI address:                                     │
│      unbind from nvidia/nouveau → set driver_override → probe    │
│    (See vfio-passthrough.md for details)                         │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 4. CLOUD-INIT ISO                                                │
│    Generate meta-data, user-data (with agent), network-config    │
│    Create seed.iso via genisoimage with "cidata" volume label    │
│    (See cloud-init.md for details)                               │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 5. BUILD QEMU COMMAND                                            │
│    qemu-system-x86_64 -enable-kvm -machine q35,accel=kvm        │
│      -cpu host -smp <cores> -m <memory>M                        │
│      -drive if=pflash,...,file=OVMF_CODE.fd                     │
│      -drive file=root.qcow2,format=qcow2,if=virtio             │
│      -drive file=seed.iso,format=raw,if=virtio,media=cdrom      │
│      -netdev tap,id=net0,ifname=<tap>,script=no                 │
│      -device virtio-net-pci,netdev=net0                         │
│      -qmp unix:<socket>,server,nowait                           │
│      -device vfio-pci,host=<gpu_pci> ...                        │
│      -daemonize -display none                                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 6. START QEMU PROCESS                                            │
│    asyncio.create_subprocess_exec(*qemu_cmd)                     │
│    Wait 2 seconds, check returncode != None (immediate exit)     │
│    Track VMInstance in _vms dict                                  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 7. WAIT FOR PHONE-HOME                                           │
│    VM agent inside guest POSTs to runner:                        │
│      POST /api/vps/{task_id}/vm-phone-home                      │
│    Signals guest OS has booted and agent is running              │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 8. WAIT FOR SSH                                                  │
│    Poll port 22 on vm_ip (2s interval, 120s timeout)             │
│    SSH ready → vm.ssh_ready = True                               │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
                 VM is RUNNING
```

### Error Handling

If any step fails, `_cleanup_vm_on_error()` runs to release partially-allocated resources:

- GPUs are unbound from VFIO (returned to their original driver)
- The instance directory is left intact for debugging

All creation errors are wrapped in `VMCreationError` with the task ID attached.

---

## VM Lifecycle

```
                    create_vm()
                        │
                        ▼
              ┌─────────────────┐
              │    CREATED      │
              │  QEMU running   │
              └────────┬────────┘
                       │  phone-home received
                       ▼
              ┌─────────────────┐
              │    RUNNING      │◄────────────┐
              │  SSH ready      │             │
              │  Agent active   │   restart_vm() (QMP reset)
              └───┬────────┬───┘             │
                  │        │                 │
       stop_vm() │        │ kill_vm()       │
                  │        │                 │
                  ▼        ▼                 │
         ┌────────────┐  ┌──────────┐       │
         │  STOPPING  │  │ KILLED   │       │
         │ QMP        │  │ SIGKILL  │       │
         │ powerdown  │  └──────────┘       │
         └─────┬──────┘                     │
               │ timeout?                   │
               ├──────── no ─► STOPPED      │
               └──────── yes ─► SIGKILL ────┘ (if restart)
                                   │
                                   ▼
                               STOPPED
```

### Stop Sequence

1. Send `system_powerdown` via QMP (ACPI power button)
2. Wait up to `timeout` seconds (default 30) for the process to exit
3. If still running, send `SIGKILL`
4. Run `_cleanup_vm()`: unbind GPUs from VFIO, remove QMP socket, remove from `_vms` dict

### Restart

Restart uses QMP `system_reset`, which is equivalent to pressing the hardware reset button. The guest OS reboots without destroying the QEMU process. The VM agent inside the guest will re-run phone-home after the reboot.

---

## Disk Management

### Base Images

Base images are pre-built qcow2 files stored in a central directory:

```
/var/lib/kohakuriver/vm-images/
├── ubuntu-24.04.qcow2       # Default supported image
└── custom-images.qcow2      # User-created images
```

These are read-only and shared across all VM instances. Operators prepare them with cloud-init support and any required base packages.

### Instance Overlay Disks

Each VM gets a copy-on-write overlay disk backed by the base image:

```
/var/lib/kohakuriver/vm-instances/{task_id}/
├── root.qcow2       # Overlay disk (COW, backed by base image)
├── seed.iso          # Cloud-init ISO
├── serial.log        # Serial console output
├── qemu.pid          # QEMU process PID file
```

The overlay is created with:

```bash
qemu-img create -f qcow2 -b /path/to/base.qcow2 -F qcow2 root.qcow2
qemu-img resize root.qcow2 50G
```

**Benefits of overlays:**
- Instant VM creation (no full disk copy)
- Base image shared across instances (saves disk space)
- Each VM's writes are isolated in its own overlay file
- Overlay can be resized independently of the base

### QMP Socket

The QMP (QEMU Machine Protocol) control socket is placed in the runtime directory:

```
/run/kohakuriver/vm/{task_id}.qmp
```

This is a Unix domain socket created by QEMU with the `-qmp unix:<path>,server,nowait` flag.

---

## QMP Control Protocol

QMP is QEMU's JSON-based machine control protocol. KohakuRiver uses it for runtime VM management without needing to interact with the QEMU process directly.

### Connection Sequence

```
Client                                QMP Socket
  │                                       │
  │◄──── Greeting (capabilities) ─────────│
  │                                       │
  │───── {"execute":"qmp_capabilities"} ──►│
  │◄──── {"return": {}} ─────────────────│
  │                                       │
  │───── {"execute":"<command>"} ─────────►│
  │◄──── {"return": <result>} ────────────│
  │                                       │
  └── close ──────────────────────────────┘
```

### Commands Used

| Command | Purpose | When |
|---------|---------|------|
| `system_powerdown` | ACPI power button (graceful shutdown) | `stop_vm()` |
| `system_reset` | Hardware reset (reboot) | `restart_vm()` |

### Implementation

QMP communication is synchronous (blocking socket I/O) and runs in a thread via `asyncio.to_thread()` to avoid blocking the event loop. Each QMP interaction is a fresh connection: connect, negotiate capabilities, send command, read response, close. This avoids complications with persistent connections and socket state management.

The socket timeout is 5 seconds. Connection failures raise `QEMUConnectionError`.

---

## VM Agent Architecture

Each VM runs an embedded Python agent (`kohakuriver-vm-agent`) installed via cloud-init. The agent provides two critical functions:

### Phone-Home

On first boot, the agent sends a POST request to the Runner:

```
POST {runner_url}/api/vps/{task_id}/vm-phone-home
```

This signals that the guest OS has fully booted and the agent is operational. The Runner uses this event to transition the task from ASSIGNING to RUNNING.

### Heartbeat

After phone-home, the agent enters a loop sending periodic heartbeats:

```
POST {runner_url}/api/vps/{task_id}/vm-heartbeat
Content-Type: application/json

{
    "task_id": 42,
    "timestamp": 1706200000.0,
    "status": "healthy",
    "gpus": [ ... GPU metrics ... ],
    "system": {
        "memory_total_bytes": 17179869184,
        "memory_used_bytes": 4294967296,
        "disk_total_bytes": 53687091200,
        "disk_used_bytes": 8589934592,
        "load_1m": 0.5
    }
}
```

GPU metrics are collected via `pynvml` (the same library used by the Runner for host-level monitoring). System metrics come from `/proc/meminfo`, `shutil.disk_usage()`, and `/proc/loadavg`.

The heartbeat interval defaults to 10 seconds (configurable via `KOHAKU_HEARTBEAT_INTERVAL` environment variable).

---

## VM Networking

VMs connect to the cluster network via TAP devices. The networking mode (overlay or standard) is determined by the Runner's configuration. See the [Networking](../6.%20networking/) section for the full overlay architecture.

### Dual-Mode Networking

| Mode | Bridge | IP Source | Use Case |
|------|--------|-----------|----------|
| **Overlay** | `kohaku-overlay` | Host's IPReservationManager | Cross-node VM communication |
| **Standard** | `kohaku-br0` | Local 10.200.0.0/24 pool | Single-node, NAT-only |

In both modes, a TAP device is created and attached to the appropriate bridge before the VM starts. The TAP device name is passed to QEMU via `-netdev tap,ifname=<tap>`. Inside the guest, the interface appears as `ens3` and is configured with a static IP by cloud-init's network-config.

---

## QEMU Command Line

The full QEMU command assembled by `_build_qemu_command()`:

```bash
qemu-system-x86_64 \
  -enable-kvm \
  -machine q35,accel=kvm \
  -cpu host \
  -smp 8 \
  -m 16384M \
  -daemonize \
  -pidfile /var/lib/kohakuriver/vm-instances/42/qemu.pid \
  # UEFI firmware
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
  # Root disk (virtio for performance)
  -drive file=root.qcow2,format=qcow2,if=virtio,cache=writeback \
  # Cloud-init ISO (read-only CDROM)
  -drive file=seed.iso,format=raw,if=virtio,media=cdrom,readonly=on \
  # Network (TAP device, pre-attached to bridge)
  -netdev tap,id=net0,ifname=tap-vm-42,script=no,downscript=no \
  -device virtio-net-pci,netdev=net0 \
  # QMP control socket
  -qmp unix:/run/kohakuriver/vm/42.qmp,server,nowait \
  # Serial console log
  -serial file:/var/lib/kohakuriver/vm-instances/42/serial.log \
  # No display
  -display none \
  -vga std \
  # GPU passthrough (one -device per GPU)
  -device vfio-pci,host=0000:01:00.0 \
  -device vfio-pci,host=0000:01:00.1    # Audio device on same slot
```

### Key Choices

| Choice | Reason |
|--------|--------|
| `q35` machine type | Modern PCIe topology, required for VFIO passthrough |
| `-cpu host` | Expose host CPU features to guest (performance) |
| `virtio` disk/net | Paravirtualized I/O for near-native performance |
| `cache=writeback` | Best disk performance (data loss risk on host crash is acceptable) |
| `-daemonize` | QEMU runs in background; managed via PID file and QMP |
| OVMF firmware | UEFI boot required for modern OS images and GPU passthrough |
| `script=no` | TAP device is pre-configured by Runner; no QEMU scripts needed |

---

## Naming Conventions

All VM-related paths and names are generated by `src/kohakuriver/qemu/naming.py`:

| Function | Example Output | Purpose |
|----------|---------------|---------|
| `vm_name(42)` | `kohaku-vm-42` | VM display name / hostname |
| `vm_instance_dir(base, 42)` | `{base}/42/` | Instance working directory |
| `vm_root_disk_path(dir)` | `{dir}/root.qcow2` | Overlay disk |
| `vm_cloud_init_path(dir)` | `{dir}/seed.iso` | Cloud-init ISO |
| `vm_qmp_socket_path(42)` | `/run/kohakuriver/vm/42.qmp` | QMP control socket |
| `vm_serial_log_path(dir)` | `{dir}/serial.log` | Serial console log |
| `vm_pidfile_path(dir)` | `{dir}/qemu.pid` | QEMU PID file |

---

## Runner Configuration

VM-related settings in the Runner config (`~/.kohakuriver/runner_config.py`):

| Setting | Default | Description |
|---------|---------|-------------|
| `VM_IMAGES_DIR` | `/var/lib/kohakuriver/vm-images/` | Directory containing base qcow2 images |
| `VM_INSTANCES_DIR` | `/var/lib/kohakuriver/vm-instances/` | Directory for VM instance data |

The Runner must also have the following system prerequisites:

- `/dev/kvm` accessible (KVM kernel module loaded)
- `qemu-system-x86_64` and `qemu-img` binaries installed
- OVMF UEFI firmware installed
- `genisoimage` or `mkisofs` for cloud-init ISO creation
- For GPU passthrough: IOMMU enabled, VFIO kernel modules loaded
