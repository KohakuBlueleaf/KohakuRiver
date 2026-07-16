"""Local inspection and teardown of KohakuRiver overlay network artifacts.

Runs directly on a host or runner machine via pyroute2 / the Docker SDK — no
host API or running service required. Used to check what overlay state actually
exists on the box, and to wipe it when it drifts from the manager's view
(e.g. an ``EEXIST (17, 'File exists')`` on allocation).

Covers both roles, since either set of interfaces may be present:
- Host:   ``vxkr*`` / ``vx<n>_*`` VXLAN devices, ``kohaku-host`` dummy
- Runner: ``vxlan0`` / ``vxlan-*`` VXLAN, ``kohaku-overlay`` / ``kohaku-*``
          bridges, ``kohaku-br0`` VM NAT bridge, ``kohakuriver-*`` Docker nets
"""

from __future__ import annotations

import re

from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# Host VXLAN devices: "vxkr<id>" (default) and "vx<net>_<id>" (multi-network).
_HOST_VXLAN_RE = re.compile(r"^vx(kr|[0-9a-z]_)")
# Runner VXLAN: "vxlan0" (default) and "vxlan-<name>" (multi-network).
_RUNNER_VXLAN_RE = re.compile(r"^vxlan(0$|-)")
# Bridges/dummy in the kohaku- namespace: kohaku-host, kohaku-overlay,
# kohaku-br0, kohaku-<name>.
_KOHAKU_IFACE_RE = re.compile(r"^kohaku-")

# "kohakuriver-net" is the non-overlay per-node bridge and is preserved.
_DOCKER_KEEP = {"kohakuriver-net"}

_IFF_UP = 1


def _is_overlay_interface(name: str) -> bool:
    return bool(
        _HOST_VXLAN_RE.match(name)
        or _RUNNER_VXLAN_RE.match(name)
        or _KOHAKU_IFACE_RE.match(name)
    )


# =============================================================================
# Inspection
# =============================================================================


def inspect_overlay_interfaces() -> list[dict]:
    """Return details of every KohakuRiver overlay interface on this machine.

    Each dict has: name, kind, state, up, mtu, addrs, and (for VXLAN) vni,
    local, remote, port.
    """
    from pyroute2 import IPRoute

    interfaces: list[dict] = []
    with IPRoute() as ipr:
        for link in ipr.get_links():
            name = link.get_attr("IFLA_IFNAME")
            if not name or not _is_overlay_interface(name):
                continue

            idx = link["index"]
            info = {
                "name": name,
                "kind": None,
                "state": link.get_attr("IFLA_OPERSTATE"),
                "up": bool(link["flags"] & _IFF_UP),
                "mtu": link.get_attr("IFLA_MTU"),
                "addrs": [],
                "vni": None,
                "local": None,
                "remote": None,
                "port": None,
            }

            linkinfo = link.get_attr("IFLA_LINKINFO")
            if linkinfo:
                info["kind"] = linkinfo.get_attr("IFLA_INFO_KIND")
                data = linkinfo.get_attr("IFLA_INFO_DATA")
                if data is not None and info["kind"] == "vxlan":
                    info["vni"] = data.get_attr("IFLA_VXLAN_ID")
                    info["local"] = data.get_attr("IFLA_VXLAN_LOCAL")
                    info["remote"] = data.get_attr("IFLA_VXLAN_GROUP") or data.get_attr(
                        "IFLA_VXLAN_REMOTE"
                    )
                    info["port"] = data.get_attr("IFLA_VXLAN_PORT")

            for addr in ipr.get_addr(index=idx):
                address = addr.get_attr("IFA_ADDRESS")
                if address:
                    info["addrs"].append(f"{address}/{addr['prefixlen']}")

            interfaces.append(info)

    interfaces.sort(key=lambda d: d["name"])
    return interfaces


def inspect_overlay_docker_networks() -> list[dict]:
    """Return KohakuRiver overlay Docker networks and their config.

    Each dict has: name, driver, subnet, gateway, bridge, containers.
    ``kohakuriver-net`` (the non-overlay bridge) is included for visibility.
    """
    networks: list[dict] = []
    try:
        import docker

        client = docker.from_env()
        listing = client.networks.list()
    except Exception as e:
        logger.debug(f"Docker not available, skipping network inspection: {e}")
        return networks

    for summary in listing:
        if not summary.name.startswith("kohakuriver-"):
            continue
        # list() omits the Containers map; fetch the full object for the count.
        try:
            attrs = client.networks.get(summary.id).attrs
        except Exception:
            attrs = summary.attrs

        ipam = (attrs.get("IPAM") or {}).get("Config") or [{}]
        options = attrs.get("Options") or {}
        networks.append(
            {
                "name": summary.name,
                "driver": attrs.get("Driver"),
                "subnet": ipam[0].get("Subnet"),
                "gateway": ipam[0].get("Gateway"),
                "bridge": options.get("com.docker.network.bridge.name"),
                "containers": len(attrs.get("Containers") or {}),
            }
        )

    networks.sort(key=lambda d: d["name"])
    return networks


# =============================================================================
# Connectivity check
# =============================================================================


def _ping(target: str, source_iface: str | None = None, timeout: int = 1) -> bool:
    """Send one ICMP echo to ``target``; True if it replies.

    ``source_iface`` binds egress to that device (SO_BINDTODEVICE) so an
    overlay ping is forced over the VXLAN rather than a stray route.
    """
    import subprocess

    cmd = ["ping", "-c", "1", "-W", str(timeout)]
    if source_iface:
        cmd += ["-I", source_iface]
    cmd.append(target)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout + 2)
        return result.returncode == 0
    except Exception:
        return False


def _overlay_peer_gateway(addr_cidr: str) -> str | None:
    """Peer overlay gateway (network+1) for our address, or None if we are it."""
    import ipaddress

    try:
        iface = ipaddress.ip_interface(addr_cidr)
    except ValueError:
        return None
    if iface.version != 4:
        return None
    gateway = iface.network.network_address + 1
    if iface.ip == gateway:
        return None
    return str(gateway)


def _collect_overlay_ping_targets(ipr) -> dict[tuple[str, str], None]:
    """Map (egress overlay interface, target IP) for every reachable overlay peer.

    Two sources, covering both roles:
    - connected subnets: ping the subnet's gateway (network+1) — lets the host
      reach each runner's gateway across its ``vxkr*`` device.
    - routed subnets: ping the via-gateway of any route leaving an overlay
      interface — lets a runner reach the host's overlay router (its containers
      live on the bridge, so the meaningful peer is the route's next hop).
    """
    import socket

    overlay_ifaces = {
        link["index"]: name
        for link in ipr.get_links()
        if (name := link.get_attr("IFLA_IFNAME")) and _is_overlay_interface(name)
    }

    targets: dict[tuple[str, str], None] = {}

    for idx, name in overlay_ifaces.items():
        for addr in ipr.get_addr(index=idx, family=socket.AF_INET):
            address = addr.get_attr("IFA_ADDRESS")
            if not address:
                continue
            peer = _overlay_peer_gateway(f"{address}/{addr['prefixlen']}")
            if peer:
                targets[(name, peer)] = None

    for route in ipr.get_routes(family=socket.AF_INET):
        oif = route.get_attr("RTA_OIF")
        gateway = route.get_attr("RTA_GATEWAY")
        if gateway and oif in overlay_ifaces:
            targets[(overlay_ifaces[oif], gateway)] = None

    return targets


def check_overlay_connectivity(timeout: int = 1) -> list[dict]:
    """Ping every overlay peer reachable from this machine, over the overlay.

    Each ping is bound to its overlay egress interface so it traverses the
    tunnel rather than a stray route. Returns {interface, target, ok}.
    """
    from pyroute2 import IPRoute

    with IPRoute() as ipr:
        targets = _collect_overlay_ping_targets(ipr)

    return [
        {
            "interface": name,
            "target": target,
            "ok": _ping(target, name, timeout=timeout),
        }
        for name, target in sorted(targets)
    ]


# =============================================================================
# Teardown
# =============================================================================


def reset_overlay_interfaces() -> list[str]:
    """Delete every KohakuRiver overlay interface present on this machine.

    Routes via these interfaces are removed by the kernel on deletion.

    Returns:
        Names of the interfaces that were removed.
    """
    from pyroute2 import IPRoute

    removed: list[str] = []
    with IPRoute() as ipr:
        targets = [
            (name, link["index"])
            for link in ipr.get_links()
            if (name := link.get_attr("IFLA_IFNAME")) and _is_overlay_interface(name)
        ]
        for name, idx in targets:
            try:
                ipr.link("del", index=idx)
                removed.append(name)
                logger.info(f"Removed overlay interface: {name}")
            except Exception as e:
                logger.warning(f"Failed to remove interface {name}: {e}")
    return removed


def reset_overlay_docker_networks() -> list[str]:
    """Remove KohakuRiver overlay Docker networks (keeps ``kohakuriver-net``).

    Returns:
        Names of the Docker networks that were removed.
    """
    removed: list[str] = []
    try:
        import docker

        client = docker.from_env()
    except Exception as e:
        logger.debug(f"Docker not available, skipping network cleanup: {e}")
        return removed

    for net in client.networks.list():
        if net.name in _DOCKER_KEEP or not net.name.startswith("kohakuriver-"):
            continue
        try:
            net.remove()
            removed.append(net.name)
            logger.info(f"Removed Docker network: {net.name}")
        except Exception as e:
            logger.warning(f"Failed to remove Docker network {net.name}: {e}")
    return removed
