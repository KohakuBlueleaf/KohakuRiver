"""VXLAN interface creation, deletion, and configuration operations."""

from __future__ import annotations

import shutil
import subprocess

from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


def create_vxlan_sync(
    ipr,
    runner_id: int,
    physical_ip: str,
    device_name: str,
    vni: int,
    host_ip_on_runner_subnet: str,
    runner_prefix: int,
    local_ip: str,
    vxlan_port: int,
    mtu: int,
) -> str:
    """
    Create or update VXLAN tunnel to runner (synchronous).

    L3 Routing approach:
    - Each VXLAN has unique VNI = base_vxlan_id + runner_id
    - Each VXLAN interface gets IP 10.{runner_id}.0.254/16
    - Kernel auto-adds route for 10.{runner_id}.0.0/16 via this interface
    - No bridge needed - host routes between interfaces

    Edge cases handled:
    1. Interface does not exist -> create new with IP
    2. Interface exists with correct config (VNI + remote) -> reuse, ensure IP assigned
    3. Interface exists with wrong config -> delete and recreate
    """
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
            ipr.link("set", index=vxlan_idx, mtu=mtu, state="up")
            ensure_vxlan_ip_sync(
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
    logger.info(
        f"Creating VXLAN: {device_name}, VNI={vni}, local={local_ip}, "
        f"remote={physical_ip}, port={vxlan_port}"
    )
    ipr.link(
        "add",
        ifname=device_name,
        kind="vxlan",
        vxlan_id=vni,
        vxlan_local=local_ip,  # Bind to Host's reachable address
        vxlan_group=physical_ip,  # Unicast remote
        vxlan_port=vxlan_port,
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
    ipr.link("set", index=vxlan_idx, mtu=mtu, state="up")

    # Assign IP to interface (this also adds route for runner subnet)
    ensure_vxlan_ip_sync(ipr, vxlan_idx, host_ip_on_runner_subnet, runner_prefix)

    # Add to firewalld trusted zone if firewalld is running
    add_interface_to_trusted_zone(device_name)

    logger.info(
        f"Created VXLAN {device_name} with IP {host_ip_on_runner_subnet}/{runner_prefix}"
    )
    return device_name


def delete_vxlan_sync(ipr, device_name: str) -> None:
    """Delete a VXLAN device (synchronous)."""
    for link in ipr.get_links():
        if link.get_attr("IFLA_IFNAME") == device_name:
            ipr.link("del", index=link["index"])
            logger.info(f"Deleted VXLAN device: {device_name}")
            return

    logger.warning(f"VXLAN device {device_name} not found for deletion")


def ensure_vxlan_ip_sync(ipr, vxlan_idx: int, ip_addr: str, prefixlen: int) -> None:
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


def add_interface_to_trusted_zone(interface_name: str) -> None:
    """
    Add interface to firewalld trusted zone if firewalld is running.

    This allows traffic to flow freely through the interface without
    being blocked by firewalld rules.
    """
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
            logger.debug("firewalld is not running, skipping firewalld configuration")
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
