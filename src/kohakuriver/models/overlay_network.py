"""
Overlay Network Definition model.

Defines the configuration for an overlay network instance.
Multiple overlay networks can coexist, each with different subnets,
VXLAN IDs, and masquerade settings.

Example configurations:
    - Private overlay (NAT for internet access):
        OverlayNetworkDefinition(
            name="private",
            subnet="10.128.0.0/12/6/14",
            vxlan_id_base=100,
            masquerade=True,
        )

    - Public overlay (direct public IPs, no NAT):
        OverlayNetworkDefinition(
            name="public",
            subnet="163.227.172.128/26",
            vxlan_id_base=200,
            masquerade=False,
        )
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OverlayNetworkDefinition:
    """
    Definition of a single overlay network.

    Each overlay network gets its own set of VXLAN tunnels, Docker bridge
    networks, and IP pools. The masquerade flag controls whether container
    traffic is NATed (for private subnets) or passes through with the
    original source IP (for public subnets).

    Attributes:
        name: Unique identifier for this network (e.g., "private", "public").
        subnet: Subnet configuration string. Two formats supported:
            - Flexible: "BASE_IP/PREFIX/NODE_BITS/SUBNET_BITS" (e.g., "10.128.0.0/12/6/14")
              for networks that need per-runner subnet splitting.
            - Simple CIDR: "BASE_IP/PREFIX" (e.g., "163.227.172.128/26")
              for flat networks where all runners share the same subnet.
        vxlan_id_base: Base VXLAN Network Identifier. Each runner gets
            VNI = vxlan_id_base + runner_id. Must not overlap with other networks.
        masquerade: If True, apply NAT masquerade for outbound traffic.
            Use True for private subnets (container needs internet via NAT).
            Use False for public subnets (container has real public IP).
        vxlan_port: UDP port for VXLAN traffic. Can be shared across networks
            since VNIs are unique.
        mtu: MTU for the overlay network (typically 1500 - 50 = 1450 for
            VXLAN overhead).
    """

    name: str
    subnet: str
    vxlan_id_base: int
    masquerade: bool = True
    vxlan_port: int = 4789
    mtu: int = 1450

    def is_simple_cidr(self) -> bool:
        """
        Check if subnet is a simple CIDR (e.g., "163.227.172.128/26")
        vs the flexible format (e.g., "10.128.0.0/12/6/14").
        """
        return len(self.subnet.strip().split("/")) == 2

    def validate(self) -> None:
        """
        Validate the network definition.

        Raises:
            ValueError: If the configuration is invalid.
        """
        if not self.name:
            raise ValueError("Network name cannot be empty")

        if not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Network name '{self.name}' must be alphanumeric "
                f"(hyphens and underscores allowed)"
            )

        if self.vxlan_id_base < 1:
            raise ValueError(
                f"vxlan_id_base must be positive, got {self.vxlan_id_base}"
            )

        if self.mtu < 576:
            raise ValueError(f"MTU must be at least 576, got {self.mtu}")

        # Validate subnet format
        parts = self.subnet.strip().split("/")
        if len(parts) not in (2, 4):
            raise ValueError(
                f"Invalid subnet format '{self.subnet}'. "
                f"Expected 'IP/PREFIX' or 'IP/PREFIX/NODE_BITS/SUBNET_BITS'"
            )

    @classmethod
    def from_dict(cls, data: dict) -> OverlayNetworkDefinition:
        """Create from a dict (e.g., from config file)."""
        return cls(
            name=data["name"],
            subnet=data["subnet"],
            vxlan_id_base=data["vxlan_id_base"],
            masquerade=data.get("masquerade", True),
            vxlan_port=data.get("vxlan_port", 4789),
            mtu=data.get("mtu", 1450),
        )

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "name": self.name,
            "subnet": self.subnet,
            "vxlan_id_base": self.vxlan_id_base,
            "masquerade": self.masquerade,
            "vxlan_port": self.vxlan_port,
            "mtu": self.mtu,
        }
