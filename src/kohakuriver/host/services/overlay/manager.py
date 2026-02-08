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
from datetime import datetime
from typing import TYPE_CHECKING

from kohakuriver.host.services.overlay.models import OverlayAllocation
from kohakuriver.host.services.overlay.recovery import (
    recover_state_from_interfaces_sync,
)
from kohakuriver.host.services.overlay.routing import setup_host_routing_sync
from kohakuriver.host.services.overlay.vxlan import (
    create_vxlan_sync,
    delete_vxlan_sync,
)
from kohakuriver.models.overlay_subnet import OverlaySubnetConfig
from kohakuriver.utils.logger import get_logger

if TYPE_CHECKING:
    from kohakuriver.host.config import HostConfig

logger = get_logger(__name__)


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
        """Set up host for L3 routing between VXLAN interfaces."""
        setup_host_routing_sync(
            ipr=self._get_ipr(),
            host_ip=self.host_ip,
            host_prefix=self.host_prefix,
            subnet_config=self.subnet_config,
        )

    def _recover_state_from_interfaces_sync(self) -> None:
        """Rebuild in-memory state from existing network interfaces."""
        recover_state_from_interfaces_sync(
            ipr=self._get_ipr(),
            vxlan_prefix=self.VXLAN_PREFIX,
            base_vxlan_id=self.base_vxlan_id,
            subnet_config=self.subnet_config,
            allocations=self._allocations,
            id_to_runner=self._id_to_runner,
            parse_device_name_fn=self._parse_vxlan_device_name,
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
            used_ids = set(self._id_to_runner)
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
        Delegates to vxlan module.
        """
        ipr = self._get_ipr()
        device_name = self._get_vxlan_device_name(runner_id)
        vni = self.base_vxlan_id + runner_id
        host_ip_on_runner_subnet = self.subnet_config.get_host_ip_on_runner_subnet(
            runner_id
        )
        runner_prefix = self.subnet_config.runner_prefix

        return create_vxlan_sync(
            ipr=ipr,
            runner_id=runner_id,
            physical_ip=physical_ip,
            device_name=device_name,
            vni=vni,
            host_ip_on_runner_subnet=host_ip_on_runner_subnet,
            runner_prefix=runner_prefix,
            local_ip=self.config.HOST_REACHABLE_ADDRESS,
            vxlan_port=self.vxlan_port,
            mtu=self.mtu,
        )

    def _delete_vxlan_sync(self, device_name: str) -> None:
        """Delete a VXLAN device (synchronous). Delegates to vxlan module."""
        delete_vxlan_sync(self._get_ipr(), device_name)

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
