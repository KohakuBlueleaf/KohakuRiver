"""State recovery from existing network interfaces on host startup."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from kohakuriver.host.services.overlay.models import OverlayAllocation
from kohakuriver.host.services.overlay.vxlan import add_interface_to_trusted_zone
from kohakuriver.utils.logger import get_logger

if TYPE_CHECKING:
    from kohakuriver.models.overlay_subnet import OverlaySubnetConfig

logger = get_logger(__name__)


def recover_state_from_interfaces_sync(
    ipr,
    vxlan_prefix: str,
    base_vxlan_id: int,
    subnet_config: OverlaySubnetConfig,
    allocations: dict[str, OverlayAllocation],
    id_to_runner: dict[int, str],
    parse_device_name_fn,
) -> None:
    """
    Rebuild in-memory state from existing network interfaces.

    Called on every Host startup - ensures Host restart doesn't break anything.
    Network interfaces ARE the source of truth.

    Device naming: "vxkr{base36_id}" - runner_id is encoded in base36.
    VNI = base_vxlan_id + runner_id (e.g., 101 for runner_id=1)
    Invalid/old-format interfaces are deleted.

    Args:
        ipr: IPRoute instance
        vxlan_prefix: Device name prefix (e.g., "vxkr")
        base_vxlan_id: Base VXLAN ID
        subnet_config: Overlay subnet configuration
        allocations: Dict to populate with recovered allocations (mutated in place)
        id_to_runner: Dict to populate with runner_id -> runner_name mapping (mutated in place)
        parse_device_name_fn: Function to parse device name to runner_id
    """
    # Collect interfaces to process (can't modify while iterating)
    interfaces_to_delete = []
    interfaces_to_recover = []

    # Find all vxkr* interfaces (our VXLAN devices)
    for link in ipr.get_links():
        name = link.get_attr("IFLA_IFNAME")
        if not name or not name.startswith(vxlan_prefix):
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
        runner_id = parse_device_name_fn(name)

        # Check if valid: parseable name AND correct VNI (base + runner_id)
        expected_vni = base_vxlan_id + runner_id if runner_id else None
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
        if runner_id in id_to_runner:
            logger.warning(f"Duplicate runner_id {runner_id} found, skipping {name}")
            continue

        # Use runner_id as placeholder name until runner re-registers
        runner_name_placeholder = f"runner_{runner_id}"

        allocation = OverlayAllocation(
            runner_name=runner_name_placeholder,
            runner_id=runner_id,
            physical_ip=remote_ip or "unknown",
            subnet=subnet_config.get_runner_subnet(runner_id),
            gateway=subnet_config.get_runner_gateway(runner_id),
            vxlan_device=name,
            last_used=datetime.now(),
            is_active=False,  # Runner must re-register to become active
        )

        allocations[runner_name_placeholder] = allocation
        id_to_runner[runner_id] = runner_name_placeholder

        # Add recovered interface to firewalld trusted zone
        add_interface_to_trusted_zone(name)

        logger.debug(
            f"Recovered allocation: runner_id={runner_id}, "
            f"remote={remote_ip}, device={name}"
        )

    logger.info(
        f"Recovered {len(interfaces_to_recover)} overlay allocations, "
        f"deleted {len(interfaces_to_delete)} invalid interfaces"
    )
