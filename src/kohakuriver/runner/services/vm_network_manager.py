"""
VM Network Manager for KohakuRiver.

Provides network setup for QEMU VMs by creating TAP devices
and attaching them to the appropriate bridge based on the networking mode.

Two modes:
- Overlay mode (OVERLAY_ENABLED=True): TAP attaches to kohaku-overlay bridge.
  VMs share the same bridge as Docker containers, get IPs from overlay pool.
- Standard mode (OVERLAY_ENABLED=False): TAP attaches to kohaku-br0 NAT bridge.
  VMs get IPs from a local 10.200.0.0/24 pool with NAT for internet access.
"""

from __future__ import annotations

import asyncio
import ipaddress
import subprocess
from dataclasses import dataclass

import httpx

from kohakuriver.runner.config import config
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class VMNetworkInfo:
    """Network configuration for a VM."""

    tap_device: str  # e.g., "tap-vm-12345"
    vm_ip: str  # e.g., "10.128.64.5" or "10.200.0.10"
    gateway: str  # e.g., "10.128.64.1" or "10.200.0.1"
    bridge_name: str  # e.g., "kohaku-overlay" or "kohaku-br0"
    netmask: str  # e.g., "255.255.192.0" or "255.255.255.0"
    prefix_len: int  # e.g., 18 or 24
    dns_servers: list[str]  # e.g., ["8.8.8.8", "8.8.4.4"]
    mode: str  # "overlay" or "standard"
    runner_url: str  # URL for VM agent to reach runner
    reservation_token: str | None = None  # Overlay mode: IP reservation token


class VMNetworkManager:
    """
    Manages VM networking across overlay and standard modes.

    In overlay mode:
    - Uses the existing kohaku-overlay bridge (created by RunnerOverlayManager)
    - Reserves IPs from host's IPReservationManager via HTTP API
    - No bridge creation needed -- same bridge Docker containers use

    In standard mode:
    - Creates kohaku-br0 NAT bridge with 10.200.0.0/24 subnet
    - Manages a local IP pool (10.200.0.10 - 10.200.0.254)
    - Sets up iptables MASQUERADE for internet access
    - Docker doesn't need this -- Docker has its own bridge built-in
    """

    # Standard mode constants
    NAT_BRIDGE_NAME = "kohaku-br0"
    NAT_SUBNET = "10.200.0.0/24"
    NAT_GATEWAY = "10.200.0.1"
    NAT_PREFIX = 24
    NAT_POOL_START = 10  # 10.200.0.10
    NAT_POOL_END = 254  # 10.200.0.254
    DNS_SERVERS = ["8.8.8.8", "8.8.4.4"]

    def __init__(self):
        self._is_overlay: bool = False
        self._nat_bridge_ready: bool = False
        self._allocations: dict[int, VMNetworkInfo] = {}  # task_id -> info
        self._used_local_ips: set[str] = set()  # Standard mode pool tracking
        self._ipr = None

    # =========================================================================
    # Setup
    # =========================================================================

    async def setup(self) -> None:
        """
        Initialize VM network manager. Called AFTER overlay setup in runner/app.py.

        Overlay mode: verify kohaku-overlay bridge exists (no creation needed).
        Standard mode: create kohaku-br0 NAT bridge with MASQUERADE.
        """
        self._is_overlay = (
            config.OVERLAY_ENABLED
            and hasattr(config, "_overlay_configured")
            and config._overlay_configured
        )

        if self._is_overlay:
            from kohakuriver.runner.services.overlay_manager import (
                RunnerOverlayManager,
            )

            logger.info("VM network: overlay mode -- using kohaku-overlay bridge")
            # Verify bridge exists
            exists = await asyncio.to_thread(
                self._check_bridge_exists_sync,
                RunnerOverlayManager.BRIDGE_NAME,
            )
            if not exists:
                raise RuntimeError("Overlay mode but kohaku-overlay bridge not found")
        else:
            logger.info("VM network: standard mode -- creating NAT bridge kohaku-br0")
            await asyncio.to_thread(self._setup_nat_bridge_sync)
            self._nat_bridge_ready = True

    def _check_bridge_exists_sync(self, bridge_name: str) -> bool:
        """Check if a bridge interface exists."""
        from pyroute2 import IPRoute

        ipr = IPRoute()
        try:
            for link in ipr.get_links():
                if link.get_attr("IFLA_IFNAME") == bridge_name:
                    return True
            return False
        finally:
            ipr.close()

    def _setup_nat_bridge_sync(self) -> None:
        """
        Create kohaku-br0 NAT bridge for standard mode (synchronous).

        1. Create bridge kohaku-br0
        2. Assign 10.200.0.1/24
        3. Bring bridge up
        4. Enable IP forwarding
        5. iptables MASQUERADE for 10.200.0.0/24
        6. iptables FORWARD rules for 10.200.0.0/24
        """
        from pyroute2 import IPRoute

        ipr = IPRoute()
        try:
            bridge_name = config.VM_BRIDGE_NAME

            # Check if bridge already exists
            bridge_idx = None
            for link in ipr.get_links():
                if link.get_attr("IFLA_IFNAME") == bridge_name:
                    bridge_idx = link["index"]
                    logger.info(f"NAT bridge {bridge_name} already exists")
                    break

            if bridge_idx is None:
                logger.info(f"Creating NAT bridge: {bridge_name}")
                ipr.link("add", ifname=bridge_name, kind="bridge")
                for link in ipr.get_links():
                    if link.get_attr("IFLA_IFNAME") == bridge_name:
                        bridge_idx = link["index"]
                        break

            if bridge_idx is None:
                raise RuntimeError(f"Failed to create bridge {bridge_name}")

            # Bring bridge up
            ipr.link("set", index=bridge_idx, state="up")

            # Add gateway IP if not present
            gateway = config.VM_BRIDGE_GATEWAY
            existing_addrs = list(ipr.get_addr(index=bridge_idx))
            has_ip = any(
                addr.get_attr("IFA_ADDRESS") == gateway for addr in existing_addrs
            )

            if not has_ip:
                logger.info(f"Adding IP {gateway}/{self.NAT_PREFIX} to {bridge_name}")
                ipr.addr(
                    "add",
                    index=bridge_idx,
                    address=gateway,
                    prefixlen=self.NAT_PREFIX,
                )

            # Enable IP forwarding
            try:
                with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                    f.write("1")
            except OSError as e:
                logger.warning(f"Failed to enable IP forwarding: {e}")

            # Set up iptables rules
            self._setup_nat_firewall_rules()

            logger.info(f"NAT bridge {bridge_name} ready ({gateway}/{self.NAT_PREFIX})")

        finally:
            ipr.close()

    def _setup_nat_firewall_rules(self) -> None:
        """Set up iptables MASQUERADE and FORWARD rules for NAT bridge."""
        subnet = config.VM_BRIDGE_SUBNET

        # MASQUERADE for internet access
        nat_check = [
            "iptables",
            "-t",
            "nat",
            "-C",
            "POSTROUTING",
            "-s",
            subnet,
            "!",
            "-d",
            subnet,
            "-j",
            "MASQUERADE",
        ]
        nat_add = [
            "iptables",
            "-t",
            "nat",
            "-A",
            "POSTROUTING",
            "-s",
            subnet,
            "!",
            "-d",
            subnet,
            "-j",
            "MASQUERADE",
        ]
        try:
            subprocess.run(nat_check, check=True, capture_output=True)
            logger.debug("NAT masquerade rule already exists")
        except subprocess.CalledProcessError:
            try:
                subprocess.run(nat_add, check=True, capture_output=True)
                logger.info("Added NAT masquerade rule for VM bridge")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to add NAT rule: {e}")

        # FORWARD rules
        for direction in ["-s", "-d"]:
            check = ["iptables", "-C", "FORWARD", direction, subnet, "-j", "ACCEPT"]
            add = ["iptables", "-I", "FORWARD", "1", direction, subnet, "-j", "ACCEPT"]
            try:
                subprocess.run(check, check=True, capture_output=True)
            except subprocess.CalledProcessError:
                try:
                    subprocess.run(add, check=True, capture_output=True)
                    logger.info(f"Added FORWARD rule for {direction} {subnet}")
                except subprocess.CalledProcessError as e:
                    logger.warning(f"Failed to add FORWARD rule: {e}")

    # =========================================================================
    # VM Network Lifecycle
    # =========================================================================

    async def create_vm_network(self, task_id: int) -> VMNetworkInfo:
        """
        Create network for a VM. Returns VMNetworkInfo.

        Overlay: create TAP -> attach to kohaku-overlay -> reserve IP from host
        Standard: create TAP -> attach to kohaku-br0 -> allocate from local pool
        """
        if self._is_overlay:
            info = await self._create_overlay_vm_network(task_id)
        else:
            info = await asyncio.to_thread(self._create_standard_vm_network, task_id)
        self._allocations[task_id] = info
        return info

    async def cleanup_vm_network(self, task_id: int) -> None:
        """Remove TAP device and release IP."""
        info = self._allocations.pop(task_id, None)
        if info is None:
            return
        await asyncio.to_thread(self._delete_tap_sync, info.tap_device)
        if info.mode == "overlay":
            await self._release_overlay_ip(info)
        else:
            self._release_local_ip(info.vm_ip)

    # =========================================================================
    # Overlay mode: TAP -> kohaku-overlay, IP from host IPReservationManager
    # =========================================================================

    async def _create_overlay_vm_network(self, task_id: int) -> VMNetworkInfo:
        """
        Reserve IP from host, create TAP on kohaku-overlay bridge.

        Uses same IPReservationManager API as Docker containers.
        """
        from kohakuriver.runner.services.overlay_manager import (
            RunnerOverlayManager,
        )

        vm_ip, token = await self._reserve_overlay_ip(task_id)
        tap_name = f"tap-vm-{task_id}"
        bridge = RunnerOverlayManager.BRIDGE_NAME  # "kohaku-overlay"
        await asyncio.to_thread(self._create_tap_sync, tap_name, bridge)

        gateway = config._overlay_gateway
        # Derive prefix from overlay subnet config
        from kohakuriver.models.overlay_subnet import OverlaySubnetConfig

        subnet_cfg = OverlaySubnetConfig.parse(config.OVERLAY_SUBNET)
        prefix_len = subnet_cfg.runner_prefix
        network = ipaddress.IPv4Network(f"{gateway}/{prefix_len}", strict=False)

        return VMNetworkInfo(
            tap_device=tap_name,
            vm_ip=vm_ip,
            gateway=gateway,
            bridge_name=bridge,
            netmask=str(network.netmask),
            prefix_len=prefix_len,
            dns_servers=self.DNS_SERVERS,
            mode="overlay",
            runner_url=f"http://{gateway}:{config.RUNNER_PORT}",
            reservation_token=token,
        )

    async def _reserve_overlay_ip(self, task_id: int) -> tuple[str, str]:
        """Reserve IP from host's IPReservationManager via HTTP API."""
        import socket

        hostname = socket.gethostname()
        host_url = config.get_host_url()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{host_url}/api/overlay/ip/reserve",
                    params={"runner": hostname, "ttl": 3600},
                    timeout=15.0,
                )
                response.raise_for_status()
                data = response.json()
                return data["ip"], data["token"]
        except Exception as e:
            raise RuntimeError(f"Failed to reserve overlay IP: {e}")

    async def _release_overlay_ip(self, info: VMNetworkInfo) -> None:
        """Release overlay IP via host API using reservation token."""
        if not info.reservation_token:
            return

        host_url = config.get_host_url()
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{host_url}/api/overlay/ip/release",
                    params={"token": info.reservation_token},
                    timeout=10.0,
                )
        except Exception as e:
            logger.warning(f"Failed to release overlay IP {info.vm_ip}: {e}")

    # =========================================================================
    # Standard mode: TAP -> kohaku-br0, IP from local 10.200.0.0/24 pool
    # =========================================================================

    def _create_standard_vm_network(self, task_id: int) -> VMNetworkInfo:
        """Allocate local IP, create TAP on kohaku-br0."""
        vm_ip = self._allocate_local_ip()
        tap_name = f"tap-vm-{task_id}"
        self._create_tap_sync(tap_name, config.VM_BRIDGE_NAME)
        network = ipaddress.IPv4Network(config.VM_BRIDGE_SUBNET)

        return VMNetworkInfo(
            tap_device=tap_name,
            vm_ip=vm_ip,
            gateway=config.VM_BRIDGE_GATEWAY,
            bridge_name=config.VM_BRIDGE_NAME,
            netmask=str(network.netmask),
            prefix_len=self.NAT_PREFIX,
            dns_servers=self.DNS_SERVERS,
            mode="standard",
            runner_url=f"http://{config.VM_BRIDGE_GATEWAY}:{config.RUNNER_PORT}",
        )

    def _allocate_local_ip(self) -> str:
        """Allocate next available IP from 10.200.0.10-254."""
        base = config.VM_BRIDGE_SUBNET.split("/")[0].rsplit(".", 1)[0]  # "10.200.0"
        for i in range(self.NAT_POOL_START, self.NAT_POOL_END + 1):
            ip = f"{base}.{i}"
            if ip not in self._used_local_ips:
                self._used_local_ips.add(ip)
                return ip
        raise RuntimeError("No available IPs in VM NAT pool")

    def _release_local_ip(self, ip: str) -> None:
        """Release local IP back to pool."""
        self._used_local_ips.discard(ip)

    # =========================================================================
    # TAP device operations (shared, uses pyroute2)
    # =========================================================================

    def _create_tap_sync(self, tap_name: str, bridge_name: str) -> None:
        """Create TAP device and attach to bridge via pyroute2."""
        from pyroute2 import IPRoute

        ipr = IPRoute()
        try:
            # Check if TAP already exists
            tap_idx = None
            for link in ipr.get_links():
                if link.get_attr("IFLA_IFNAME") == tap_name:
                    tap_idx = link["index"]
                    logger.info(f"TAP {tap_name} already exists")
                    break

            if tap_idx is None:
                logger.info(f"Creating TAP device: {tap_name}")
                ipr.link("add", ifname=tap_name, kind="tun", tun_type="tap")
                for link in ipr.get_links():
                    if link.get_attr("IFLA_IFNAME") == tap_name:
                        tap_idx = link["index"]
                        break

            if tap_idx is None:
                raise RuntimeError(f"Failed to create TAP {tap_name}")

            # Find bridge
            bridge_idx = None
            for link in ipr.get_links():
                if link.get_attr("IFLA_IFNAME") == bridge_name:
                    bridge_idx = link["index"]
                    break

            if bridge_idx is None:
                raise RuntimeError(f"Bridge {bridge_name} not found")

            # Attach TAP to bridge
            ipr.link("set", index=tap_idx, master=bridge_idx)

            # Bring TAP up
            ipr.link("set", index=tap_idx, state="up")

            logger.info(f"TAP {tap_name} attached to bridge {bridge_name}")

        finally:
            ipr.close()

    def _delete_tap_sync(self, tap_name: str) -> None:
        """Delete TAP device via pyroute2."""
        from pyroute2 import IPRoute

        ipr = IPRoute()
        try:
            for link in ipr.get_links():
                if link.get_attr("IFLA_IFNAME") == tap_name:
                    ipr.link("del", index=link["index"])
                    logger.info(f"Deleted TAP {tap_name}")
                    return
            logger.debug(f"TAP {tap_name} not found for deletion")
        except Exception as e:
            logger.warning(f"Failed to delete TAP {tap_name}: {e}")
        finally:
            ipr.close()

    # =========================================================================
    # Cloud-init helpers
    # =========================================================================

    def get_cloud_init_network_config(self, info: VMNetworkInfo) -> dict:
        """Generate cloud-init network-config v2 for this VM."""
        return {
            "version": 2,
            "ethernets": {
                "ens3": {
                    "addresses": [f"{info.vm_ip}/{info.prefix_len}"],
                    "gateway4": info.gateway,
                    "nameservers": {"addresses": info.dns_servers},
                }
            },
        }

    def get_vm_runner_url(self, info: VMNetworkInfo) -> str:
        """Get RUNNER_URL for VM agent to reach runner."""
        return info.runner_url


# Global instance
_vm_network_manager: VMNetworkManager | None = None


def get_vm_network_manager() -> VMNetworkManager:
    """Get global VMNetworkManager instance."""
    global _vm_network_manager
    if _vm_network_manager is None:
        _vm_network_manager = VMNetworkManager()
    return _vm_network_manager
