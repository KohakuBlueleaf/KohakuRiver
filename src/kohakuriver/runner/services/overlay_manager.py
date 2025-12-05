"""
VXLAN Overlay Network Manager for Runner node.

This module manages the Runner's side of the VXLAN hub architecture,
setting up the VXLAN tunnel to Host and creating the Docker overlay network.

Key Features:
- Creates VXLAN tunnel to Host
- Creates kohaku-overlay bridge on Runner
- Creates Docker network using the overlay bridge
- Handles setup/teardown on runner restart
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kohakuriver.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass
class OverlayConfig:
    """Overlay configuration received from Host during registration."""

    runner_id: int
    subnet: str  # "10.X.0.0/16"
    gateway: str  # "10.X.0.1"
    host_overlay_ip: str  # "10.0.0.1"
    host_physical_ip: str  # Physical IP of Host for VXLAN tunnel
    runner_physical_ip: str  # Physical IP of this Runner for VXLAN local binding


class RunnerOverlayManager:
    """
    Manages the VXLAN overlay network on the Runner node.

    Creates a VXLAN tunnel to the Host and a Docker network that uses
    the overlay bridge for container networking.
    """

    # Network configuration
    BRIDGE_NAME = "kohaku-overlay"
    VXLAN_NAME = "vxlan0"
    DOCKER_NETWORK_NAME = "kohakuriver-overlay"

    def __init__(
        self,
        base_vxlan_id: int = 100,
        vxlan_port: int = 4789,
        mtu: int = 1450,
    ):
        """Initialize runner overlay manager."""
        self.base_vxlan_id = base_vxlan_id
        self.vxlan_port = vxlan_port
        self.mtu = mtu

        self._config: OverlayConfig | None = None
        self._ipr = None
        self._setup_complete = False

    def _get_ipr(self):
        """Get or create IPRoute instance."""
        if self._ipr is None:
            from pyroute2 import IPRoute

            self._ipr = IPRoute()
        return self._ipr

    async def setup(self, config: OverlayConfig) -> None:
        """
        Set up the overlay network on this Runner.

        1. Create VXLAN tunnel to Host
        2. Create kohaku-overlay bridge
        3. Attach VXLAN to bridge
        4. Assign runner's gateway IP to bridge
        5. Create Docker network using the bridge

        Args:
            config: Overlay configuration from Host registration response
        """
        self._config = config

        logger.info(
            f"Setting up overlay network: runner_id={config.runner_id}, "
            f"subnet={config.subnet}, host={config.host_physical_ip}"
        )

        # Run network operations in executor
        await asyncio.to_thread(self._setup_network_sync)

        # Create Docker network
        await asyncio.to_thread(self._setup_docker_network_sync)

        self._setup_complete = True
        logger.info(f"Overlay network setup complete: Docker network={self.DOCKER_NETWORK_NAME}")

    def _setup_network_sync(self) -> None:
        """Set up VXLAN and bridge (synchronous)."""
        ipr = self._get_ipr()
        config = self._config

        if config is None:
            raise RuntimeError("OverlayConfig not set")

        vni = self.base_vxlan_id + config.runner_id  # Unique VNI per runner

        # Check/create bridge
        bridge_idx = None
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == self.BRIDGE_NAME:
                bridge_idx = link["index"]
                logger.info(f"Bridge {self.BRIDGE_NAME} already exists")
                break

        if bridge_idx is None:
            logger.info(f"Creating bridge: {self.BRIDGE_NAME}")
            ipr.link("add", ifname=self.BRIDGE_NAME, kind="bridge")

            for link in ipr.get_links():
                if link.get_attr("IFLA_IFNAME") == self.BRIDGE_NAME:
                    bridge_idx = link["index"]
                    break

        # Bring bridge up
        ipr.link("set", index=bridge_idx, state="up", mtu=self.mtu)

        # Add gateway IP to bridge if not present
        existing_addrs = list(ipr.get_addr(index=bridge_idx))
        has_ip = False
        for addr in existing_addrs:
            if addr.get_attr("IFA_ADDRESS") == config.gateway:
                has_ip = True
                break

        if not has_ip:
            # Extract prefix from subnet (e.g., "10.1.0.0/16" -> 16)
            prefix = int(config.subnet.split("/")[1])
            logger.info(f"Adding IP {config.gateway}/{prefix} to {self.BRIDGE_NAME}")
            ipr.addr("add", index=bridge_idx, address=config.gateway, prefixlen=prefix)

        # Check/create VXLAN
        vxlan_idx = None
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == self.VXLAN_NAME:
                vxlan_idx = link["index"]
                logger.info(f"VXLAN {self.VXLAN_NAME} already exists, checking config")

                # Verify VNI matches
                linkinfo = link.get_attr("IFLA_LINKINFO")
                if linkinfo:
                    vxlan_data = linkinfo.get_attr("IFLA_INFO_DATA")
                    if vxlan_data:
                        existing_vni = vxlan_data.get_attr("IFLA_VXLAN_ID")
                        if existing_vni != vni:
                            logger.warning(
                                f"Existing VXLAN VNI {existing_vni} doesn't match expected {vni}, recreating"
                            )
                            ipr.link("del", index=vxlan_idx)
                            vxlan_idx = None
                break

        if vxlan_idx is None:
            logger.info(
                f"Creating VXLAN: {self.VXLAN_NAME}, VNI={vni}, "
                f"local={config.runner_physical_ip}, remote={config.host_physical_ip}, "
                f"port={self.vxlan_port}"
            )
            ipr.link(
                "add",
                ifname=self.VXLAN_NAME,
                kind="vxlan",
                vxlan_id=vni,
                vxlan_local=config.runner_physical_ip,  # Bind to Runner's physical IP
                vxlan_group=config.host_physical_ip,  # Unicast to Host
                vxlan_port=self.vxlan_port,
                vxlan_learning=False,
            )

            for link in ipr.get_links():
                if link.get_attr("IFLA_IFNAME") == self.VXLAN_NAME:
                    vxlan_idx = link["index"]
                    break

        if vxlan_idx is None:
            raise RuntimeError(f"Failed to create VXLAN device {self.VXLAN_NAME}")

        # Set MTU and bring up
        ipr.link("set", index=vxlan_idx, mtu=self.mtu, state="up")

        # Attach to bridge if not already
        link_info = None
        for link in ipr.get_links():
            if link["index"] == vxlan_idx:
                link_info = link
                break

        if link_info:
            master = link_info.get_attr("IFLA_MASTER")
            if master != bridge_idx:
                logger.info(f"Attaching {self.VXLAN_NAME} to {self.BRIDGE_NAME}")
                ipr.link("set", index=vxlan_idx, master=bridge_idx)

        # Add route to other overlay subnets via host
        # Host IP on this runner's subnet is 10.{runner_id}.0.254
        # Route 10.0.0.0/8 via this gateway (host will route to other runners)
        host_gateway = f"10.{config.runner_id}.0.254"
        self._ensure_overlay_routes(ipr, bridge_idx, host_gateway, config.runner_id)

        # Set up iptables and firewalld rules for overlay forwarding
        self._setup_firewall_rules()

        logger.info(f"Network setup complete: {self.VXLAN_NAME} -> {self.BRIDGE_NAME}")

    def _ensure_overlay_routes(
        self, ipr, bridge_idx: int, host_gateway: str, runner_id: int
    ) -> None:
        """
        Ensure routes exist for cross-runner communication.

        We need to route 10.0.0.0/8 (except our own 10.{runner_id}.0.0/16) via the host.
        Since our local subnet 10.{runner_id}.0.0/16 has a more specific route (via bridge),
        we can add a catch-all 10.0.0.0/8 via host_gateway.
        """
        try:
            # Add route for 10.0.0.0/8 via host gateway
            # The local 10.{runner_id}.0.0/16 route is more specific, so local traffic stays local
            routes = list(ipr.get_routes(dst="10.0.0.0", dst_len=8))
            route_exists = False
            for route in routes:
                if route.get_attr("RTA_GATEWAY") == host_gateway:
                    route_exists = True
                    break

            if not route_exists:
                logger.info(f"Adding route 10.0.0.0/8 via {host_gateway}")
                ipr.route("add", dst="10.0.0.0", dst_len=8, gateway=host_gateway)

        except Exception as e:
            # Route may already exist
            logger.debug(f"Overlay route handling: {e}")

    def _setup_firewall_rules(self) -> None:
        """
        Set up iptables and firewalld rules to allow overlay traffic forwarding
        and NAT for external network access.

        This ensures:
        1. Cross-node communication works even when firewalld blocks forwarding
        2. Containers can access external networks (internet) via NAT/masquerade
        """
        import shutil
        import subprocess

        # Set up iptables FORWARD rules (insert at top of FORWARD chain)
        forward_rules = [
            ["-I", "FORWARD", "1", "-s", "10.0.0.0/8", "-j", "ACCEPT"],
            ["-I", "FORWARD", "2", "-d", "10.0.0.0/8", "-j", "ACCEPT"],
        ]

        for rule in forward_rules:
            # Check if rule exists (convert -I to -C for checking)
            check_rule = ["-C", "FORWARD", "-s" if "-s" in rule else "-d",
                          "10.0.0.0/8", "-j", "ACCEPT"]
            check_cmd = ["iptables"] + check_rule
            try:
                subprocess.run(check_cmd, check=True, capture_output=True)
                logger.debug(f"iptables rule already exists: {' '.join(rule)}")
            except subprocess.CalledProcessError:
                # Rule doesn't exist, add it
                add_cmd = ["iptables"] + rule
                try:
                    subprocess.run(add_cmd, check=True, capture_output=True)
                    logger.info(f"Added iptables rule: {' '.join(rule)}")
                except subprocess.CalledProcessError as e:
                    logger.warning(f"Failed to add iptables rule {rule}: {e}")

        # Set up NAT/masquerade for external network access
        # This allows containers to reach the internet through the Runner
        # Only masquerade traffic going to non-overlay destinations
        nat_rule = ["-t", "nat", "-A", "POSTROUTING",
                    "-s", "10.0.0.0/8", "!", "-d", "10.0.0.0/8",
                    "-j", "MASQUERADE"]
        nat_check = ["-t", "nat", "-C", "POSTROUTING",
                     "-s", "10.0.0.0/8", "!", "-d", "10.0.0.0/8",
                     "-j", "MASQUERADE"]

        try:
            subprocess.run(["iptables"] + nat_check, check=True, capture_output=True)
            logger.debug("NAT masquerade rule already exists")
        except subprocess.CalledProcessError:
            try:
                subprocess.run(["iptables"] + nat_rule, check=True, capture_output=True)
                logger.info("Added NAT masquerade rule for external network access")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to add NAT masquerade rule: {e}")

        # Check if firewall-cmd exists and firewalld is running
        if shutil.which("firewall-cmd") is None:
            logger.debug("firewall-cmd not found, skipping firewalld configuration")
            return

        try:
            result = subprocess.run(
                ["firewall-cmd", "--state"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0 or "running" not in result.stdout:
                logger.debug("firewalld is not running, skipping firewalld configuration")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.debug("Could not check firewalld state, skipping")
            return

        # Add overlay interfaces to trusted zone
        for interface in [self.BRIDGE_NAME, self.VXLAN_NAME]:
            try:
                result = subprocess.run(
                    ["firewall-cmd", "--zone=trusted", f"--add-interface={interface}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    logger.info(f"Added {interface} to firewalld trusted zone")
                else:
                    logger.debug(f"firewall-cmd output: {result.stderr.strip()}")
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout adding {interface} to firewalld trusted zone")
            except Exception as e:
                logger.warning(f"Failed to add {interface} to firewalld: {e}")

    def _setup_docker_network_sync(self) -> None:
        """Create Docker network using the overlay bridge (synchronous)."""
        import docker

        client = docker.from_env()
        config = self._config

        if config is None:
            raise RuntimeError("OverlayConfig not set")

        # Check if network exists
        try:
            network = client.networks.get(self.DOCKER_NETWORK_NAME)
            logger.info(f"Docker network {self.DOCKER_NETWORK_NAME} already exists")

            # Verify it's using our bridge
            network_config = network.attrs.get("Options", {})
            bridge_name = network_config.get("com.docker.network.bridge.name")
            if bridge_name != self.BRIDGE_NAME:
                logger.warning(
                    f"Existing network uses bridge '{bridge_name}', expected '{self.BRIDGE_NAME}'. Recreating."
                )
                network.remove()
                raise docker.errors.NotFound("Recreating network")

            return
        except docker.errors.NotFound:
            pass

        # Create network using our bridge
        # Use the runner's subnet for IPAM
        logger.info(
            f"Creating Docker network {self.DOCKER_NETWORK_NAME} "
            f"on bridge {self.BRIDGE_NAME} with subnet {config.subnet}"
        )

        ipam_pool = docker.types.IPAMPool(
            subnet=config.subnet,
            gateway=config.gateway,
        )
        ipam_config = docker.types.IPAMConfig(pool_configs=[ipam_pool])

        client.networks.create(
            self.DOCKER_NETWORK_NAME,
            driver="bridge",
            ipam=ipam_config,
            options={
                "com.docker.network.bridge.name": self.BRIDGE_NAME,
                "com.docker.network.driver.mtu": str(self.mtu),
                # Disable iptables isolation to allow VXLAN traffic through bridge
                "com.docker.network.bridge.enable_icc": "true",
                "com.docker.network.bridge.enable_ip_masquerade": "false",
            },
        )

        logger.info(f"Created Docker network {self.DOCKER_NETWORK_NAME}")

    async def teardown(self) -> None:
        """
        Tear down the overlay network.

        Removes Docker network, VXLAN tunnel, and bridge.
        Use with caution - running containers will lose connectivity.
        """
        if not self._setup_complete:
            return

        logger.info("Tearing down overlay network...")

        # Remove Docker network first
        await asyncio.to_thread(self._teardown_docker_network_sync)

        # Remove network interfaces
        await asyncio.to_thread(self._teardown_network_sync)

        self._setup_complete = False
        logger.info("Overlay network teardown complete")

    def _teardown_docker_network_sync(self) -> None:
        """Remove Docker network (synchronous)."""
        import docker

        try:
            client = docker.from_env()
            network = client.networks.get(self.DOCKER_NETWORK_NAME)
            network.remove()
            logger.info(f"Removed Docker network {self.DOCKER_NETWORK_NAME}")
        except docker.errors.NotFound:
            pass
        except Exception as e:
            logger.warning(f"Failed to remove Docker network: {e}")

    def _teardown_network_sync(self) -> None:
        """Remove VXLAN and bridge (synchronous)."""
        ipr = self._get_ipr()

        # Remove VXLAN
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == self.VXLAN_NAME:
                ipr.link("del", index=link["index"])
                logger.info(f"Removed VXLAN {self.VXLAN_NAME}")
                break

        # Remove bridge
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == self.BRIDGE_NAME:
                ipr.link("del", index=link["index"])
                logger.info(f"Removed bridge {self.BRIDGE_NAME}")
                break

    async def is_healthy(self) -> bool:
        """Check if overlay network is healthy."""
        if not self._setup_complete or self._config is None:
            return False

        try:
            return await asyncio.to_thread(self._check_health_sync)
        except Exception as e:
            logger.warning(f"Overlay health check failed: {e}")
            return False

    def _check_health_sync(self) -> bool:
        """Check health (synchronous)."""
        ipr = self._get_ipr()

        # Check bridge exists and is up
        bridge_up = False
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == self.BRIDGE_NAME:
                flags = link.get_attr("IFLA_OPERSTATE")
                bridge_up = flags == "UP" or link["flags"] & 1  # IFF_UP
                break

        if not bridge_up:
            logger.warning("Overlay bridge is not up")
            return False

        # Check VXLAN exists and is up
        vxlan_up = False
        for link in ipr.get_links():
            if link.get_attr("IFLA_IFNAME") == self.VXLAN_NAME:
                flags = link.get_attr("IFLA_OPERSTATE")
                vxlan_up = flags == "UP" or link["flags"] & 1
                break

        if not vxlan_up:
            logger.warning("Overlay VXLAN is not up")
            return False

        # Check Docker network exists
        import docker

        try:
            client = docker.from_env()
            client.networks.get(self.DOCKER_NETWORK_NAME)
        except docker.errors.NotFound:
            logger.warning("Overlay Docker network not found")
            return False

        return True

    async def get_status(self) -> dict:
        """Get overlay network status."""
        config = self._config
        return {
            "setup_complete": self._setup_complete,
            "bridge_name": self.BRIDGE_NAME,
            "vxlan_name": self.VXLAN_NAME,
            "docker_network": self.DOCKER_NETWORK_NAME,
            "runner_id": config.runner_id if config else None,
            "subnet": config.subnet if config else None,
            "gateway": config.gateway if config else None,
            "host_overlay_ip": config.host_overlay_ip if config else None,
            "healthy": await self.is_healthy() if self._setup_complete else False,
        }

    def get_docker_network_name(self) -> str:
        """Get the Docker network name to use for containers."""
        return self.DOCKER_NETWORK_NAME

    def close(self) -> None:
        """Close the IPRoute connection."""
        if self._ipr is not None:
            self._ipr.close()
            self._ipr = None
