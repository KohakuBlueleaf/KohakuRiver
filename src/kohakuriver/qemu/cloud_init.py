"""
Cloud-init ISO generation for VM provisioning.

Creates seed.iso with meta-data, user-data, and network-config
for VM initialization.
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import textwrap
import yaml
from dataclasses import dataclass

from kohakuriver.qemu.exceptions import CloudInitError
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CloudInitConfig:
    """Cloud-init configuration."""

    task_id: int
    hostname: str
    mac_address: str
    vm_ip: str
    gateway: str
    prefix_len: int
    dns_servers: list[str]
    ssh_public_key: str
    runner_url: str
    runner_public_key: str = ""
    nvidia_driver_version: str | None = None


# Embedded VM agent script (runs inside VM, reports status to runner)
VM_AGENT_SCRIPT = textwrap.dedent(
    '''\
    #!/usr/bin/env python3
    """KohakuRiver VM Agent - Status reporter for VPS VMs."""

    import json
    import os
    import shutil
    import time
    import urllib.request
    from dataclasses import dataclass, asdict

    RUNNER_URL = os.environ.get("KOHAKU_RUNNER_URL")
    TASK_ID = os.environ.get("KOHAKU_TASK_ID")
    HEARTBEAT_INTERVAL = int(os.environ.get("KOHAKU_HEARTBEAT_INTERVAL", "10"))


    @dataclass
    class GPUInfo:
        gpu_id: int
        name: str
        driver_version: str
        pci_bus_id: str
        gpu_utilization: int
        graphics_clock_mhz: int
        mem_utilization: int
        mem_clock_mhz: int
        memory_total_mib: float
        memory_used_mib: float
        memory_free_mib: float
        temperature: int
        fan_speed: int
        power_usage_mw: int
        power_limit_mw: int


    def get_gpu_info():
        try:
            import pynvml
        except ImportError:
            return []

        gpu_list = []
        nvml_initialized = False
        try:
            pynvml.nvmlInit()
            nvml_initialized = True
            driver_version = pynvml.nvmlSystemGetDriverVersion()
            if isinstance(driver_version, bytes):
                driver_version = driver_version.decode("utf-8")
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(name, bytes):
                        name = name.decode("utf-8")
                    pci_info = pynvml.nvmlDeviceGetPciInfo(handle)
                    pci_bus_id = pci_info.busId
                    if isinstance(pci_bus_id, bytes):
                        pci_bus_id = pci_bus_id.decode("utf-8")
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    try:
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                        gpu_util, mem_util = util.gpu, util.memory
                    except pynvml.NVMLError:
                        gpu_util, mem_util = -1, -1
                    try:
                        graphics_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
                        mem_clock = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                    except pynvml.NVMLError:
                        graphics_clock, mem_clock = -1, -1
                    try:
                        temperature = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    except pynvml.NVMLError:
                        temperature = -1
                    try:
                        fan_speed = pynvml.nvmlDeviceGetFanSpeed(handle)
                    except pynvml.NVMLError:
                        fan_speed = -1
                    try:
                        power_usage = pynvml.nvmlDeviceGetPowerUsage(handle)
                        power_limit = pynvml.nvmlDeviceGetEnforcedPowerLimit(handle)
                    except pynvml.NVMLError:
                        power_usage, power_limit = -1, -1
                    gpu_info = GPUInfo(
                        gpu_id=i, name=name, driver_version=driver_version,
                        pci_bus_id=pci_bus_id, gpu_utilization=gpu_util,
                        mem_utilization=mem_util, graphics_clock_mhz=graphics_clock,
                        mem_clock_mhz=mem_clock,
                        memory_total_mib=mem_info.total / (1024**2),
                        memory_used_mib=mem_info.used / (1024**2),
                        memory_free_mib=mem_info.free / (1024**2),
                        temperature=temperature, fan_speed=fan_speed,
                        power_usage_mw=power_usage, power_limit_mw=power_limit,
                    )
                    gpu_list.append(asdict(gpu_info))
                except pynvml.NVMLError:
                    continue
        except Exception:
            return []
        finally:
            if nvml_initialized:
                try:
                    pynvml.nvmlShutdown()
                except Exception:
                    pass
        return gpu_list


    def get_system_info():
        try:
            with open("/proc/meminfo") as f:
                meminfo = {}
                for line in f:
                    if ":" in line:
                        key, val = line.split(":", 1)
                        meminfo[key.strip()] = val.strip()
            mem_total = int(meminfo["MemTotal"].split()[0]) * 1024
            mem_available = int(meminfo["MemAvailable"].split()[0]) * 1024
        except Exception:
            mem_total, mem_available = 0, 0

        try:
            disk = shutil.disk_usage("/")
        except Exception:
            disk = type("D", (), {"total": 0, "used": 0})()

        try:
            with open("/proc/loadavg") as f:
                load = float(f.read().split()[0])
        except Exception:
            load = 0.0

        return {
            "memory_total_bytes": mem_total,
            "memory_used_bytes": mem_total - mem_available,
            "disk_total_bytes": getattr(disk, "total", 0),
            "disk_used_bytes": getattr(disk, "used", 0),
            "load_1m": load,
        }


    def send_heartbeat():
        payload = {
            "task_id": int(TASK_ID),
            "timestamp": time.time(),
            "gpus": get_gpu_info(),
            "system": get_system_info(),
            "status": "healthy",
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{RUNNER_URL}/api/vps/{TASK_ID}/vm-heartbeat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"Heartbeat failed: {e}")
            return False


    def phone_home():
        req = urllib.request.Request(
            f"{RUNNER_URL}/api/vps/{TASK_ID}/vm-phone-home",
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                print("Phone-home successful")
        except Exception as e:
            print(f"Phone-home failed: {e}")


    def main():
        if not TASK_ID:
            print("KOHAKU_TASK_ID not set")
            return 1
        phone_home()
        while True:
            send_heartbeat()
            time.sleep(HEARTBEAT_INTERVAL)


    if __name__ == "__main__":
        exit(main() or 0)
'''
)


def build_meta_data(config: CloudInitConfig) -> str:
    """Generate meta-data content."""
    return yaml.dump(
        {
            "instance-id": f"kohaku-vm-{config.task_id}",
            "local-hostname": config.hostname,
        },
        default_flow_style=False,
    )


def build_user_data(config: CloudInitConfig) -> str:
    """
    Generate user-data content.

    Includes:
    - User setup (kohaku user with sudo)
    - SSH authorized_keys (user key + runner key for TTY/filesystem access)
    - VM agent installation
    - Phone-home callback
    """
    # Collect all SSH keys: user key + runner internal key
    ssh_keys = []
    if config.ssh_public_key:
        ssh_keys.append(config.ssh_public_key)
    if config.runner_public_key:
        ssh_keys.append(config.runner_public_key)

    user_data = {
        "users": [
            {
                "name": "kohaku",
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "shell": "/bin/bash",
                "lock_passwd": True,
                "ssh_authorized_keys": ssh_keys.copy(),
            },
            {
                "name": "root",
                "ssh_authorized_keys": ssh_keys.copy(),
            },
        ],
        "ssh_pwauth": not config.ssh_public_key,
        "write_files": [
            {
                "path": "/usr/local/bin/kohakuriver-vm-agent",
                "permissions": "0755",
                "content": VM_AGENT_SCRIPT,
            },
            {
                "path": "/etc/fstab",
                "append": True,
                "content": (
                    "kohaku_shared /shared 9p trans=virtio,version=9p2000.L,msize=524288,nofail,_netdev 0 0\n"
                    "kohaku_local /local_temp 9p trans=virtio,version=9p2000.L,msize=524288,nofail,_netdev 0 0\n"
                ),
            },
            {
                "path": "/etc/ssh/sshd_config.d/99-kohakuriver.conf",
                "content": ("PermitRootLogin yes\n" "PasswordAuthentication yes\n"),
            },
            {
                "path": "/etc/systemd/system/kohakuriver-vm-agent.service",
                "content": textwrap.dedent(
                    f"""\
                    [Unit]
                    Description=KohakuRiver VM Agent
                    After=network-online.target
                    Wants=network-online.target

                    [Service]
                    Type=simple
                    ExecStart=/usr/local/bin/kohakuriver-vm-agent
                    Restart=always
                    RestartSec=5
                    Environment=KOHAKU_RUNNER_URL={config.runner_url}
                    Environment=KOHAKU_TASK_ID={config.task_id}
                    Environment=KOHAKU_HEARTBEAT_INTERVAL=10

                    [Install]
                    WantedBy=multi-user.target
                """
                ),
            },
        ],
        "package_update": True,
        "packages": [
            "qemu-guest-agent",
            "net-tools",
        ],
        "runcmd": [
            # 9p kernel modules + mount shared filesystems
            "modprobe 9p 9pnet 9pnet_virtio || true",
            "mkdir -p /shared /local_temp",
            "mount -t 9p -o trans=virtio,version=9p2000.L,msize=524288 kohaku_shared /shared || true",
            "mount -t 9p -o trans=virtio,version=9p2000.L,msize=524288 kohaku_local /local_temp || true",
            "systemctl daemon-reload",
            "systemctl restart sshd || systemctl restart ssh || true",
            "systemctl enable --now kohakuriver-vm-agent",
            "systemctl enable --now qemu-guest-agent",
        ],
    }

    # If GPU passthrough, install NVIDIA driver + pynvml for VM agent
    if config.nvidia_driver_version:
        ver = config.nvidia_driver_version
        driver_url = f"https://us.download.nvidia.com/XFree86/Linux-x86_64/{ver}/NVIDIA-Linux-x86_64-{ver}.run"
        user_data["packages"].extend(
            [
                "build-essential",
                "dkms",
                "linux-headers-generic",
                "pkg-config",
                "libglvnd-dev",
                "python3-pip",
            ]
        )
        # Insert NVIDIA install steps before the VM agent starts
        nvidia_cmds = [
            f"wget -q -O /tmp/nvidia.run {driver_url}",
            "chmod +x /tmp/nvidia.run",
            "/tmp/nvidia.run --silent --dkms --no-cc-version-check",
            "rm -f /tmp/nvidia.run",
            "pip3 install nvidia-ml-py --break-system-packages",
        ]
        # Insert before "systemctl enable --now kohakuriver-vm-agent"
        runcmd = user_data["runcmd"]
        agent_idx = next(
            (i for i, c in enumerate(runcmd) if "kohakuriver-vm-agent" in c),
            len(runcmd),
        )
        for j, cmd in enumerate(nvidia_cmds):
            runcmd.insert(agent_idx + j, cmd)

    # If no SSH key, enable password-less root login
    if not config.ssh_public_key:
        user_data["chpasswd"] = {"expire": False}
        user_data["users"][1]["lock_passwd"] = False

    return "#cloud-config\n" + yaml.dump(user_data, default_flow_style=False)


def build_network_config(config: CloudInitConfig) -> str:
    """Generate network-config for static IP.

    Uses MAC address matching instead of a hardcoded device name
    to avoid issues with PCI-based naming (enp0s2, ens3, etc.).
    Uses 'routes' instead of deprecated 'gateway4'.
    """
    net_config = {
        "version": 2,
        "ethernets": {
            "vmnic0": {
                "match": {"macaddress": config.mac_address},
                "addresses": [f"{config.vm_ip}/{config.prefix_len}"],
                "routes": [{"to": "default", "via": config.gateway}],
                "nameservers": {"addresses": config.dns_servers},
            }
        },
    }
    return yaml.dump(net_config, default_flow_style=False)


async def create_cloud_init_iso(
    output_path: str,
    config: CloudInitConfig,
) -> None:
    """
    Create cloud-init seed ISO.

    Args:
        output_path: Path for output ISO
        config: Cloud-init configuration

    Raises:
        CloudInitError: If ISO creation fails
    """

    def _create_sync():
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write cloud-init files
            meta_data_path = os.path.join(tmpdir, "meta-data")
            user_data_path = os.path.join(tmpdir, "user-data")
            network_config_path = os.path.join(tmpdir, "network-config")

            with open(meta_data_path, "w") as f:
                f.write(build_meta_data(config))

            with open(user_data_path, "w") as f:
                f.write(build_user_data(config))

            with open(network_config_path, "w") as f:
                f.write(build_network_config(config))

            # Find ISO creation tool
            iso_tool = shutil.which("genisoimage") or shutil.which("mkisofs")
            if not iso_tool:
                raise CloudInitError(
                    "Neither genisoimage nor mkisofs found. Install genisoimage."
                )

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Create ISO
            cmd = [
                iso_tool,
                "-output",
                output_path,
                "-volid",
                "cidata",
                "-joliet",
                "-rock",
                meta_data_path,
                user_data_path,
                network_config_path,
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    raise CloudInitError(f"ISO creation failed: {result.stderr}")
            except subprocess.TimeoutExpired:
                raise CloudInitError("ISO creation timed out")
            except FileNotFoundError:
                raise CloudInitError(f"ISO tool not found: {iso_tool}")

        logger.info(f"Created cloud-init ISO: {output_path}")

    await asyncio.to_thread(_create_sync)
