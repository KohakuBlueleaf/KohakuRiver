"""
VXLAN Hub Overlay Network Manager for Host node.

This module manages the VXLAN hub architecture where Host acts as the central
L3 router for cross-node container networking.

Architecture:
=============
- Each runner gets a unique VNI (base_vxlan_id + runner_id)
- Each VXLAN interface (vxkr{id}) gets its own IP on the runner's subnet
- Host acts as L3 router between subnets (IP forwarding enabled)
- No L2 bridge needed - pure L3 routing between VXLAN tunnels

Network Layout:
- Runner 1: subnet 10.1.0.0/16, gateway 10.1.0.1, host IP 10.1.0.254
- Runner 2: subnet 10.2.0.0/16, gateway 10.2.0.1, host IP 10.2.0.254
- Host overlay IP: 10.0.0.1/32 (on loopback or dummy, for containers to reach host)

Traffic Flow (Container A on Runner1 -> Container B on Runner2):
1. Container A (10.1.0.5) sends to 10.2.0.8
2. Runner1 routes via gateway 10.1.0.1 -> VXLAN (VNI=101) -> Host
3. Host receives on vxkr1 (has IP 10.1.0.254)
4. Host kernel routes: 10.2.0.0/16 is reachable via vxkr2
5. Host sends via vxkr2 (VNI=102) -> Runner2
6. Runner2 delivers to Container B (10.2.0.8)

Device Naming:
- Format: "vxkr{base36_runner_id}" (e.g., "vxkr1", "vxkr2", "vxkra" for id=10)
- VNI = base_vxlan_id + runner_id (e.g., 101, 102, ...)
- Runner ID is encoded in base36 for compact, decodable naming

Recovery & Edge Cases:
======================

On Host Startup (_recover_state_from_interfaces_sync):
------------------------------------------------------
1. VALID interface (correct name format + expected VNI):
   - Recover: create placeholder allocation "runner_{id}"
   - Runner will re-register and claim this allocation by matching physical_ip
   - Keeps existing VXLAN tunnel intact (no container disruption)

2. INVALID interface (wrong name format OR unexpected VNI):
   - Delete: old/corrupted interface, free up resources
   - Will be recreated correctly when runner registers

On Runner Registration (allocate_for_runner):
---------------------------------------------
1. Runner name already in allocations:
   - Reuse existing allocation
   - If physical_ip changed: recreate VXLAN with new remote IP

2. Recovered allocation matches physical_ip (placeholder "runner_{id}"):
   - Remap: update runner_name, reuse runner_id and VXLAN interface
   - No network disruption for containers

3. New runner, interface vxkr{id} does NOT exist:
   - Create: new VXLAN interface with IP and routing

4. New runner, interface vxkr{id} ALREADY exists (stale from crash/etc):
   - Delete and recreate: ensures correct remote IP and routing

On VXLAN Creation (_create_vxlan_sync):
---------------------------------------
1. Interface does not exist:
   - Create new VXLAN with VNI = base + runner_id
   - Assign IP 10.{runner_id}.0.254/16 to interface
   - Route is auto-added by kernel for 10.{runner_id}.0.0/16

2. Interface already exists with CORRECT config (same VNI, same remote):
   - Reuse: ensure IP is assigned and interface is up

3. Interface already exists with WRONG config:
   - Delete and recreate: ensures correct configuration
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from kohakuriver.models.overlay_subnet import OverlaySubnetConfig
from kohakuriver.utils.logger import get_logger

if TYPE_CHECKING:
    from kohakuriver.host.config import HostConfig

logger = get_logger(__name__)


@dataclass
class OverlayAllocation:
    """Represents an overlay network allocation for a runner."""

    runner_name: str
    runner_id: int
    physical_ip: str
    subnet: str  # "10.X.0.0/16"
    gateway: str  # "10.X.0.1"
    vxlan_device: str  # "vxlan_kohakuriver_xxx"
    last_used: datetime = field(default_factory=datetime.now)
    is_active: bool = False


class OverlayNetworkManager:
    """
    Manages the VXLAN Hub overlay network on the Host node.

    The Host acts as a central L2 switch, connecting all Runner nodes
    via VXLAN tunnels attached to a single bridge (kohaku-overlay).

    State Management:
    - In-memory state (_allocations, _id_to_runner) is a CACHE
    - Network interfaces are the source of truth
    - On startup, state is recovered from existing vxlan_kohakuriver_* interfaces
    - Host restart does NOT break existing tunnels
    """

    # Device naming: "vxkr{base36_id}" - e.g., "vxkr1", "vxkra" (for id=10)
    # Linux interface names limited to 15 chars, this scheme uses 5-7 chars max
    VXLAN_PREFIX = "vxkr"

    def __init__(self, config: HostConfig):
        """Initialize overlay manager with configuration."""
        self.config = config

        # Parse subnet configuration
        self.subnet_config = OverlaySubnetConfig.parse(config.OVERLAY_SUBNET)

        # Configuration from HostConfig
        self.host_ip = self.subnet_config.get_host_ip()
        self.host_prefix = self.subnet_config.overlay_prefix
        self.base_vxlan_id = config.OVERLAY_VXLAN_ID
        self.vxlan_port = config.OVERLAY_VXLAN_PORT
        self.mtu = config.OVERLAY_MTU

        # In-Memory State (CACHE - derived from network interfaces)
        # These are rebuilt on every startup from existing interfaces
        self._allocations: dict[str, OverlayAllocation] = {}
        self._id_to_runner: dict[int, str] = {}
        self._lock = asyncio.Lock()

        # Lazy-loaded pyroute2 IPRoute instance
        self._ipr = None

        logger.info(
            f"Overlay subnet config: {self.subnet_config}, "
            f"max_runners={self.subnet_config.max_runners}"
        )

    def _get_ipr(self):
        """Get or create IPRoute instance."""
        if self._ipr is None:
            from pyroute2 import IPRoute

            self._ipr = IPRoute()
        return self._ipr

    @staticmethod
    def _encode_runner_id(runner_id: int) -> str:
        """Encode runner_id to base36 string."""
        if runner_id < 0:
            raise ValueError("runner_id must be non-negative")
        if runner_id == 0:
            return "0"
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        result = ""
        n = runner_id
        while n:
            result = chars[n % 36] + result
            n //= 36
        return result

    @staticmethod
    def _decode_runner_id(encoded: str) -> int | None:
        """Decode base36 string to runner_id. Returns None if invalid."""
        if not encoded:
            return None
        try:
            return int(encoded, 36)
        except ValueError:
            return None

    def _get_vxlan_device_name(self, runner_id: int) -> str:
        """Get VXLAN device name for a runner_id."""
        return f"{self.VXLAN_PREFIX}{self._encode_runner_id(runner_id)}"

    def _parse_vxlan_device_name(self, device_name: str) -> int | None:
        """
        Parse VXLAN device name to extract runner_id.
        Returns None if not a valid vxkr device name.
        """
        if not device_name.startswith(self.VXLAN_PREFIX):
            return None
        encoded = device_name[len(self.VXLAN_PREFIX) :]
        runner_id = self._decode_runner_id(encoded)
        if (
            runner_id is None
            or runner_id < 1
            or runner_id > self.subnet_config.max_runners
        ):
            return None
        return runner_id

    async def initialize(self) -> None:
        """
        Initialize the overlay network.

        1. Enable IP forwarding for L3 routing between VXLAN interfaces
        2. Set up dummy interface with host overlay IP (10.0.0.1)
        3. Recover state from existing vxkr* interfaces
        4. Mark all recovered allocations as inactive (runner must re-register)
        """
        logger.info("Initializing overlay network manager...")

        # Run network operations in executor to avoid blocking
        await asyncio.to_thread(self._setup_host_routing_sync)
        await asyncio.to_thread(self._recover_state_from_interfaces_sync)

        logger.info(
            f"Overlay network initialized: host_ip={self.host_ip}, "
            f"recovered_allocations={len(self._allocations)}"
        )

    def _setup_host_routing_sync(self) -> None:
        """
        Set up host for L3 routing between VXLAN interfaces.

        1. Enable IP forwarding
        2. Create dummy interface with host overlay IP (10.0.0.1)
           - This allows containers to reach host at consistent IP
        """
        import os

        # Enable IP forwarding
        try:
            with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                f.write("1")
            logger.info("Enabled IPv4 forwarding")
        except PermissionError:
            logger.warning(
                "Cannot enable IP forwarding (no permission). "
                "Ensure net.ipv4.ip_forward=1 is set."
            )

        # Create dummy interface for host overlay IP
        # This gives containers a consistent IP to reach the host
        ipr = self._get_ipr()
        dummy_name = "kohaku-host"

        # Check if dummy exists
        dummy_idx = None
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == dummy_name:
                dummy_idx = link["index"]
                break

        if dummy_idx is None:
            logger.info(f"Creating dummy interface: {dummy_name}")
            ipr.link("add", ifname=dummy_name, kind="dummy")

            for link in ipr.get_links():
                if link.get_attr("IFLA_IFNAME") == dummy_name:
                    dummy_idx = link["index"]
                    break

        if dummy_idx is None:
            logger.error(f"Failed to create dummy interface {dummy_name}")
            return

        # Bring up
        ipr.link("set", index=dummy_idx, state="up")

        # Add host overlay IP if not present
        existing_addrs = list(ipr.get_addr(index=dummy_idx))
        has_ip = False
        for addr in existing_addrs:
            if addr.get_attr("IFA_ADDRESS") == self.host_ip:
                has_ip = True
                break

        if not has_ip:
            # Use /8 prefix so host can receive packets for any 10.x.x.x
            logger.info(f"Adding IP {self.host_ip}/{self.host_prefix} to {dummy_name}")
            ipr.addr(
                "add", index=dummy_idx, address=self.host_ip, prefixlen=self.host_prefix
            )

        logger.info(
            f"Host routing ready: {dummy_name} has {self.host_ip}/{self.host_prefix}"
        )

        # Set up iptables rules for overlay forwarding
        self._setup_iptables_rules_sync()

    def _setup_iptables_rules_sync(self) -> None:
        """
        Set up iptables rules to allow forwarding between overlay interfaces.

        This ensures cross-runner communication works even when firewalld
        or default iptables policies block forwarding.
        """
        import subprocess

        overlay_cidr = self.subnet_config.get_overlay_network_cidr()

        # Rules to add:
        # 1. Allow forwarding from/to overlay subnet
        # 2. Allow forwarding between vxkr interfaces
        rules = [
            # Allow all traffic from overlay subnet to be forwarded
            ["-A", "FORWARD", "-s", overlay_cidr, "-j", "ACCEPT"],
            ["-A", "FORWARD", "-d", overlay_cidr, "-j", "ACCEPT"],
        ]

        for rule in rules:
            # Check if rule exists (use -C to check)
            check_cmd = ["iptables", "-C"] + rule[1:]  # Replace -A with -C
            try:
                subprocess.run(check_cmd, check=True, capture_output=True)
                # Rule exists, skip
                logger.debug(f"iptables rule already exists: {' '.join(rule)}")
            except subprocess.CalledProcessError:
                # Rule doesn't exist, add it
                add_cmd = ["iptables"] + rule
                try:
                    subprocess.run(add_cmd, check=True, capture_output=True)
                    logger.info(f"Added iptables rule: {' '.join(rule)}")
                except subprocess.CalledProcessError as e:
                    logger.warning(f"Failed to add iptables rule {rule}: {e}")

    def _recover_state_from_interfaces_sync(self) -> None:
        """
        Rebuild in-memory state from existing network interfaces.

        Called on every Host startup - ensures Host restart doesn't break anything.
        Network interfaces ARE the source of truth.

        Device naming: "vxkr{base36_id}" - runner_id is encoded in base36.
        VNI = base_vxlan_id + runner_id (e.g., 101 for runner_id=1)
        Invalid/old-format interfaces are deleted.
        """
        ipr = self._get_ipr()

        # Collect interfaces to process (can't modify while iterating)
        interfaces_to_delete = []
        interfaces_to_recover = []

        # Find all vxkr* interfaces (our VXLAN devices)
        for link in ipr.get_links():
            name = link.get_attr("IFLA_IFNAME")
            if not name or not name.startswith(self.VXLAN_PREFIX):
                continue

            # Check if it's a VXLAN device
            linkinfo = link.get_attr("IFLA_LINKINFO")
            if not linkinfo:
                continue

            kind = linkinfo.get_attr("IFLA_INFO_KIND")
            if kind != "vxlan":
                continue

            vxlan_data = linkinfo.get_attr("IFLA_INFO_DATA")
            if not vxlan_data:
                continue

            # Extract VXLAN info
            vni = vxlan_data.get_attr("IFLA_VXLAN_ID")
            remote_ip = vxlan_data.get_attr("IFLA_VXLAN_GROUP") or vxlan_data.get_attr(
                "IFLA_VXLAN_REMOTE"
            )

            # Parse runner_id from device name (base36 encoded)
            runner_id = self._parse_vxlan_device_name(name)

            # Check if valid: parseable name AND correct VNI (base + runner_id)
            expected_vni = self.base_vxlan_id + runner_id if runner_id else None
            if runner_id is None or vni != expected_vni:
                logger.warning(
                    f"Invalid VXLAN interface {name} (runner_id={runner_id}, "
                    f"vni={vni}, expected_vni={expected_vni}), will delete"
                )
                interfaces_to_delete.append(link["index"])
                continue

            interfaces_to_recover.append((name, runner_id, remote_ip, link["index"]))

        # Delete invalid interfaces
        for idx in interfaces_to_delete:
            try:
                ipr.link("del", index=idx)
                logger.info(f"Deleted invalid VXLAN interface (index={idx})")
            except Exception as e:
                logger.warning(f"Failed to delete interface index={idx}: {e}")

        # Recover valid interfaces
        for name, runner_id, remote_ip, _ in interfaces_to_recover:
            # Check for runner_id collision (shouldn't happen with correct naming)
            if runner_id in self._id_to_runner:
                logger.warning(
                    f"Duplicate runner_id {runner_id} found, skipping {name}"
                )
                continue

            # Use runner_id as placeholder name until runner re-registers
            runner_name_placeholder = f"runner_{runner_id}"

            allocation = OverlayAllocation(
                runner_name=runner_name_placeholder,
                runner_id=runner_id,
                physical_ip=remote_ip or "unknown",
                subnet=self.subnet_config.get_runner_subnet(runner_id),
                gateway=self.subnet_config.get_runner_gateway(runner_id),
                vxlan_device=name,
                last_used=datetime.now(),
                is_active=False,  # Runner must re-register to become active
            )

            self._allocations[runner_name_placeholder] = allocation
            self._id_to_runner[runner_id] = runner_name_placeholder

            # Add recovered interface to firewalld trusted zone
            self._add_interface_to_trusted_zone(name)

            logger.debug(
                f"Recovered allocation: runner_id={runner_id}, "
                f"remote={remote_ip}, device={name}"
            )

        logger.info(
            f"Recovered {len(interfaces_to_recover)} overlay allocations, "
            f"deleted {len(interfaces_to_delete)} invalid interfaces"
        )

    async def allocate_for_runner(
        self, runner_name: str, physical_ip: str
    ) -> OverlayAllocation:
        """
        Allocate or retrieve overlay network configuration for a runner.

        If runner already has an allocation (active or inactive), return it
        with updated physical_ip. This ensures runner gets SAME subnet when
        reconnecting (containers may still be running).

        Args:
            runner_name: Runner hostname
            physical_ip: Runner's physical IP address

        Returns:
            OverlayAllocation with subnet info
        """
        async with self._lock:
            # Check if already allocated by runner_name
            if runner_name in self._allocations:
                alloc = self._allocations[runner_name]
                alloc.last_used = datetime.now()
                alloc.is_active = True

                # Update VXLAN if IP changed (or ensure correct config)
                if alloc.physical_ip != physical_ip:
                    # _create_vxlan_sync handles: exists with correct config (noop),
                    # exists with wrong config (delete+recreate), doesn't exist (create)
                    await asyncio.to_thread(
                        self._create_vxlan_sync,
                        alloc.runner_id,
                        physical_ip,
                    )
                    alloc.physical_ip = physical_ip
                    logger.info(
                        f"Updated VXLAN remote for {runner_name}: {physical_ip}"
                    )

                logger.info(
                    f"Reusing existing allocation for {runner_name}: {alloc.subnet}"
                )
                return alloc

            # Check if there's a recovered allocation (placeholder name) matching physical_ip
            # This handles the case where runner re-registers after host restart
            for existing_name, alloc in list(self._allocations.items()):
                if (
                    existing_name.startswith("runner_")
                    and alloc.physical_ip == physical_ip
                ):
                    # Found matching recovered allocation, update runner_name
                    del self._allocations[existing_name]
                    alloc.runner_name = runner_name
                    alloc.last_used = datetime.now()
                    alloc.is_active = True

                    self._allocations[runner_name] = alloc
                    self._id_to_runner[alloc.runner_id] = runner_name
                    logger.info(
                        f"Remapped recovered allocation {existing_name} -> {runner_name}: "
                        f"{alloc.subnet}"
                    )
                    return alloc

            # New runner - find available runner_id
            max_id = self.subnet_config.max_runners
            used_ids = set(self._id_to_runner.keys())
            available_ids = set(range(1, max_id + 1)) - used_ids

            if not available_ids:
                # Pool exhausted - cleanup LRU inactive allocation
                lru_runner = self._find_lru_inactive()
                if lru_runner:
                    await self._release_runner_internal(lru_runner)
                    available_ids = set(range(1, max_id + 1)) - set(
                        self._id_to_runner.keys()
                    )

                if not available_ids:
                    raise RuntimeError(
                        f"No available runner IDs (1-{max_id}) and no inactive allocations to cleanup"
                    )

            runner_id = min(available_ids)

            # Create VXLAN tunnel
            vxlan_device = await asyncio.to_thread(
                self._create_vxlan_sync, runner_id, physical_ip
            )

            # Create allocation
            allocation = OverlayAllocation(
                runner_name=runner_name,
                runner_id=runner_id,
                physical_ip=physical_ip,
                subnet=self.subnet_config.get_runner_subnet(runner_id),
                gateway=self.subnet_config.get_runner_gateway(runner_id),
                vxlan_device=vxlan_device,
                last_used=datetime.now(),
                is_active=True,
            )

            self._allocations[runner_name] = allocation
            self._id_to_runner[runner_id] = runner_name

            logger.info(
                f"Created new allocation for {runner_name}: "
                f"runner_id={runner_id}, subnet={allocation.subnet}, device={vxlan_device}"
            )

            return allocation

    def _create_vxlan_sync(self, runner_id: int, physical_ip: str) -> str:
        """
        Create or update VXLAN tunnel to runner (synchronous).

        L3 Routing approach:
        - Each VXLAN has unique VNI = base_vxlan_id + runner_id
        - Each VXLAN interface gets IP 10.{runner_id}.0.254/16
        - Kernel auto-adds route for 10.{runner_id}.0.0/16 via this interface
        - No bridge needed - host routes between interfaces

        Edge cases handled:
        1. Interface does not exist → create new with IP
        2. Interface exists with correct config (VNI + remote) → reuse, ensure IP assigned
        3. Interface exists with wrong config → delete and recreate
        """
        ipr = self._get_ipr()

        device_name = self._get_vxlan_device_name(runner_id)
        vni = self.base_vxlan_id + runner_id  # Unique VNI per runner
        host_ip_on_runner_subnet = self.subnet_config.get_host_ip_on_runner_subnet(
            runner_id
        )
        runner_prefix = self.subnet_config.runner_prefix

        # Check if device already exists
        existing_link = None
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == device_name:
                existing_link = link
                break

        if existing_link is not None:
            # Device exists - check if config matches
            vxlan_idx = existing_link["index"]
            linkinfo = existing_link.get_attr("IFLA_LINKINFO")
            existing_vni = None
            existing_remote = None

            if linkinfo:
                vxlan_data = linkinfo.get_attr("IFLA_INFO_DATA")
                if vxlan_data:
                    existing_vni = vxlan_data.get_attr("IFLA_VXLAN_ID")
                    existing_remote = vxlan_data.get_attr(
                        "IFLA_VXLAN_GROUP"
                    ) or vxlan_data.get_attr("IFLA_VXLAN_REMOTE")

            # Check if config matches
            if existing_vni == vni and existing_remote == physical_ip:
                # Case 2: Correct config - ensure IP assigned and up
                logger.info(
                    f"VXLAN {device_name} already exists with correct config, reusing"
                )
                ipr.link("set", index=vxlan_idx, mtu=self.mtu, state="up")
                self._ensure_vxlan_ip_sync(
                    ipr, vxlan_idx, host_ip_on_runner_subnet, runner_prefix
                )
                return device_name
            else:
                # Case 3: Wrong config - delete and recreate
                logger.info(
                    f"VXLAN {device_name} exists with wrong config "
                    f"(vni={existing_vni} vs {vni}, remote={existing_remote} vs {physical_ip}), "
                    f"deleting and recreating"
                )
                ipr.link("del", index=vxlan_idx)

        # Case 1 or after Case 3: Create new VXLAN device
        local_ip = self.config.HOST_REACHABLE_ADDRESS
        logger.info(
            f"Creating VXLAN: {device_name}, VNI={vni}, local={local_ip}, "
            f"remote={physical_ip}, port={self.vxlan_port}"
        )
        ipr.link(
            "add",
            ifname=device_name,
            kind="vxlan",
            vxlan_id=vni,
            vxlan_local=local_ip,  # Bind to Host's reachable address
            vxlan_group=physical_ip,  # Unicast remote
            vxlan_port=self.vxlan_port,
            vxlan_learning=False,  # Disable learning for point-to-point
        )

        # Get new device index
        vxlan_idx = None
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == device_name:
                vxlan_idx = link["index"]
                break

        if vxlan_idx is None:
            raise RuntimeError(f"Failed to create VXLAN device {device_name}")

        # Set MTU and bring up
        ipr.link("set", index=vxlan_idx, mtu=self.mtu, state="up")

        # Assign IP to interface (this also adds route for runner subnet)
        self._ensure_vxlan_ip_sync(
            ipr, vxlan_idx, host_ip_on_runner_subnet, runner_prefix
        )

        # Add to firewalld trusted zone if firewalld is running
        self._add_interface_to_trusted_zone(device_name)

        logger.info(
            f"Created VXLAN {device_name} with IP {host_ip_on_runner_subnet}/{runner_prefix}"
        )
        return device_name

    def _add_interface_to_trusted_zone(self, interface_name: str) -> None:
        """
        Add interface to firewalld trusted zone if firewalld is running.

        This allows traffic to flow freely through the interface without
        being blocked by firewalld rules.
        """
        import shutil
        import subprocess

        # Check if firewall-cmd exists
        if shutil.which("firewall-cmd") is None:
            logger.debug("firewall-cmd not found, skipping firewalld configuration")
            return

        # Check if firewalld is running
        try:
            result = subprocess.run(
                ["firewall-cmd", "--state"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0 or "running" not in result.stdout:
                logger.debug(
                    "firewalld is not running, skipping firewalld configuration"
                )
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.debug("Could not check firewalld state, skipping")
            return

        # Add interface to trusted zone (non-permanent, will be re-added on restart)
        try:
            result = subprocess.run(
                ["firewall-cmd", "--zone=trusted", f"--add-interface={interface_name}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info(f"Added {interface_name} to firewalld trusted zone")
            else:
                # May already be in zone, or zone doesn't exist
                logger.debug(f"firewall-cmd output: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout adding {interface_name} to firewalld trusted zone")
        except Exception as e:
            logger.warning(f"Failed to add {interface_name} to firewalld: {e}")

    def _ensure_vxlan_ip_sync(
        self, ipr, vxlan_idx: int, ip_addr: str, prefixlen: int
    ) -> None:
        """Ensure VXLAN interface has the correct IP assigned."""
        # Check existing addresses
        existing_addrs = list(ipr.get_addr(index=vxlan_idx))
        has_ip = False
        for addr in existing_addrs:
            if addr.get_attr("IFA_ADDRESS") == ip_addr:
                has_ip = True
                break

        if not has_ip:
            # Add IP with configured prefix - kernel will auto-add route
            logger.info(f"Adding IP {ip_addr}/{prefixlen} to VXLAN interface")
            ipr.addr("add", index=vxlan_idx, address=ip_addr, prefixlen=prefixlen)

    async def mark_runner_inactive(self, runner_name: str) -> None:
        """Mark a runner's overlay allocation as inactive."""
        async with self._lock:
            if runner_name in self._allocations:
                self._allocations[runner_name].is_active = False
                logger.info(f"Marked overlay allocation inactive: {runner_name}")

    async def mark_runner_active(self, runner_name: str) -> None:
        """Mark a runner's overlay allocation as active."""
        async with self._lock:
            if runner_name in self._allocations:
                alloc = self._allocations[runner_name]
                alloc.is_active = True
                alloc.last_used = datetime.now()

    async def release_runner(self, runner_name: str) -> bool:
        """
        Manually release an overlay allocation.

        This removes the VXLAN tunnel and frees the runner_id.
        Use with caution - containers may lose connectivity.
        """
        async with self._lock:
            return await self._release_runner_internal(runner_name)

    async def _release_runner_internal(self, runner_name: str) -> bool:
        """Internal release without lock (caller must hold lock)."""
        if runner_name not in self._allocations:
            return False

        alloc = self._allocations[runner_name]

        # Delete VXLAN device
        await asyncio.to_thread(self._delete_vxlan_sync, alloc.vxlan_device)

        # Remove from state
        del self._allocations[runner_name]
        if alloc.runner_id in self._id_to_runner:
            del self._id_to_runner[alloc.runner_id]

        logger.info(
            f"Released overlay allocation: {runner_name} (runner_id={alloc.runner_id})"
        )
        return True

    def _delete_vxlan_sync(self, device_name: str) -> None:
        """Delete a VXLAN device (synchronous)."""
        ipr = self._get_ipr()

        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == device_name:
                ipr.link("del", index=link["index"])
                logger.info(f"Deleted VXLAN device: {device_name}")
                return

        logger.warning(f"VXLAN device {device_name} not found for deletion")

    def _find_lru_inactive(self) -> str | None:
        """Find the least recently used INACTIVE allocation."""
        inactive = [
            (name, alloc)
            for name, alloc in self._allocations.items()
            if not alloc.is_active
        ]
        if not inactive:
            return None
        # Sort by last_used ascending (oldest first)
        inactive.sort(key=lambda x: x[1].last_used)
        return inactive[0][0]

    async def cleanup_inactive(self) -> int:
        """Force cleanup of all inactive allocations. Returns count of cleaned."""
        async with self._lock:
            inactive_runners = [
                name for name, alloc in self._allocations.items() if not alloc.is_active
            ]
            cleaned = 0
            for runner_name in inactive_runners:
                if await self._release_runner_internal(runner_name):
                    cleaned += 1
            return cleaned

    async def get_allocation(self, runner_name: str) -> OverlayAllocation | None:
        """Get allocation for a specific runner."""
        async with self._lock:
            return self._allocations.get(runner_name)

    async def get_all_allocations(self) -> list[OverlayAllocation]:
        """Get all current allocations."""
        async with self._lock:
            return list(self._allocations.values())

    async def get_stats(self) -> dict:
        """Get overlay network statistics."""
        async with self._lock:
            active_count = sum(1 for a in self._allocations.values() if a.is_active)
            inactive_count = len(self._allocations) - active_count
            return {
                "total_allocations": len(self._allocations),
                "active_allocations": active_count,
                "inactive_allocations": inactive_count,
                "available_ids": self.subnet_config.max_runners
                - len(self._allocations),
                "max_runners": self.subnet_config.max_runners,
                "subnet_config": str(self.subnet_config),
                "overlay_network": self.subnet_config.get_overlay_network_cidr(),
                "host_ip": f"{self.host_ip}/{self.host_prefix}",
                "base_vxlan_id": self.base_vxlan_id,
                "vxlan_port": self.vxlan_port,
                "mtu": self.mtu,
            }

    def close(self) -> None:
        """Close the IPRoute connection."""
        if self._ipr is not None:
            self._ipr.close()
            self._ipr = None
