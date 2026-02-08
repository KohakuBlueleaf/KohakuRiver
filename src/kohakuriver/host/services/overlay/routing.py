"""Host routing setup: IP forwarding, dummy interface, and iptables rules."""

from __future__ import annotations

import subprocess

from kohakuriver.models.overlay_subnet import OverlaySubnetConfig
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


def setup_host_routing_sync(
    ipr,
    host_ip: str,
    host_prefix: int,
    subnet_config: OverlaySubnetConfig,
) -> None:
    """
    Set up host for L3 routing between VXLAN interfaces.

    1. Enable IP forwarding
    2. Create dummy interface with host overlay IP (10.0.0.1)
       - This allows containers to reach host at consistent IP
    """
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
        if addr.get_attr("IFA_ADDRESS") == host_ip:
            has_ip = True
            break

    if not has_ip:
        # Use /8 prefix so host can receive packets for any 10.x.x.x
        logger.info(f"Adding IP {host_ip}/{host_prefix} to {dummy_name}")
        ipr.addr("add", index=dummy_idx, address=host_ip, prefixlen=host_prefix)

    logger.info(f"Host routing ready: {dummy_name} has {host_ip}/{host_prefix}")

    # Set up iptables rules for overlay forwarding
    setup_iptables_rules_sync(subnet_config)


def setup_iptables_rules_sync(subnet_config: OverlaySubnetConfig) -> None:
    """
    Set up iptables rules to allow forwarding between overlay interfaces.

    This ensures cross-runner communication works even when firewalld
    or default iptables policies block forwarding.
    """
    overlay_cidr = subnet_config.get_overlay_network_cidr()

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
