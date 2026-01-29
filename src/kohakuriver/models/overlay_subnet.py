"""
Overlay Subnet Configuration for VXLAN networking.

Parses and calculates IP addresses for the overlay network based on a
flexible subnet configuration format.

Format: BASE_IP/NETWORK_PREFIX/NODE_BITS/SUBNET_BITS
- NETWORK_PREFIX + NODE_BITS + SUBNET_BITS must equal 32
- NETWORK_PREFIX: Fixed bits defining the overlay network (e.g., 8 for 10.x.x.x)
- NODE_BITS: Bits for runner/node identification
- SUBNET_BITS: Bits for container IPs within each runner

Examples:
- 10.128.0.0/12/6/14 (default):
  - Network: 10.128.0.0/12 (10.128.0.0 - 10.143.255.255)
  - Node bits: 6 (up to 63 runners)
  - Subnet bits: 14 (~16,380 container IPs per runner)
  - Runner 1: 10.128.64.0/18, gateway 10.128.64.1, host IP 10.128.64.254
  - Host: 10.128.0.1

- 10.0.0.0/8/8/16:
  - Network: 10.0.0.0/8 (10.0.0.0 - 10.255.255.255)
  - Node bits: 8 (up to 255 runners)
  - Subnet bits: 16 (~65,532 container IPs per runner)
  - Runner 1: 10.1.0.0/16, gateway 10.1.0.1, host IP 10.1.0.254
  - Host: 10.0.0.1
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass


@dataclass
class OverlaySubnetConfig:
    """
    Overlay subnet configuration parsed from format string.

    Attributes:
        base_network: Base IP network (e.g., 10.0.0.0/8)
        total_prefix: Total prefix bits for the overlay network
        node_bits: Number of bits for node identification
        subnet_bits: Number of bits for in-runner subnet
    """

    base_network: ipaddress.IPv4Network
    total_prefix: int
    node_bits: int
    subnet_bits: int

    # Default configuration: 10.128.0.0/12/6/14
    # - 10.128.0.0/12 network (10.128.x.x - 10.143.x.x, avoids common 10.x.x.x ranges)
    # - 6 bits for runner ID (up to 63 runners)
    # - 14 bits for container subnet (16,380 IPs per runner)
    DEFAULT_CONFIG = "10.128.0.0/12/6/14"

    @classmethod
    def parse(cls, config_str: str) -> OverlaySubnetConfig:
        """
        Parse a subnet configuration string.

        Args:
            config_str: Format "BASE/TOTAL_PREFIX/NODE_BITS/SUBNET_BITS"
                        e.g., "10.0.0.0/8/8/16" or "10.16.0.0/12/6/14"

        Returns:
            OverlaySubnetConfig instance

        Raises:
            ValueError: If format is invalid or bits don't add up to 32
        """
        parts = config_str.strip().split("/")

        if len(parts) != 4:
            raise ValueError(
                f"Invalid overlay subnet format: '{config_str}'. "
                f"Expected format: BASE_IP/TOTAL_PREFIX/NODE_BITS/SUBNET_BITS "
                f"(e.g., '10.0.0.0/8/8/16')"
            )

        try:
            base_ip = parts[0]
            total_prefix = int(parts[1])
            node_bits = int(parts[2])
            subnet_bits = int(parts[3])
        except ValueError as e:
            raise ValueError(
                f"Invalid overlay subnet format: '{config_str}'. "
                f"Prefix values must be integers. Error: {e}"
            )

        # Validate bits add up to 32
        if total_prefix + node_bits + subnet_bits != 32:
            raise ValueError(
                f"Invalid overlay subnet config: '{config_str}'. "
                f"total_prefix({total_prefix}) + node_bits({node_bits}) + "
                f"subnet_bits({subnet_bits}) = {total_prefix + node_bits + subnet_bits}, "
                f"must equal 32."
            )

        # Validate ranges
        if total_prefix < 1 or total_prefix > 24:
            raise ValueError(
                f"Invalid total_prefix: {total_prefix}. Must be between 1 and 24."
            )

        if node_bits < 1 or node_bits > 16:
            raise ValueError(
                f"Invalid node_bits: {node_bits}. Must be between 1 and 16."
            )

        if subnet_bits < 8:
            raise ValueError(
                f"Invalid subnet_bits: {subnet_bits}. Must be at least 8 "
                f"(256 IPs per runner minimum)."
            )

        # Parse base network
        try:
            base_network = ipaddress.IPv4Network(
                f"{base_ip}/{total_prefix}", strict=False
            )
        except ipaddress.AddressValueError as e:
            raise ValueError(f"Invalid base IP address '{base_ip}': {e}")
        except ipaddress.NetmaskValueError as e:
            raise ValueError(f"Invalid network prefix: {e}")

        return cls(
            base_network=base_network,
            total_prefix=total_prefix,
            node_bits=node_bits,
            subnet_bits=subnet_bits,
        )

    @classmethod
    def default(cls) -> OverlaySubnetConfig:
        """Get the default configuration (10.0.0.0/8/8/16)."""
        return cls.parse(cls.DEFAULT_CONFIG)

    @property
    def max_runners(self) -> int:
        """Maximum number of runners supported (excluding host at ID 0)."""
        return (2**self.node_bits) - 1

    @property
    def ips_per_runner(self) -> int:
        """Number of usable IPs per runner subnet (excluding gateway, host, broadcast)."""
        # Total - gateway - host_ip_on_subnet - network - broadcast
        total = 2**self.subnet_bits
        return total - 4  # network, gateway, host_on_subnet, broadcast

    @property
    def runner_prefix(self) -> int:
        """Prefix length for runner subnets (e.g., 16 for /16)."""
        return 32 - self.subnet_bits

    @property
    def overlay_prefix(self) -> int:
        """Prefix length for the entire overlay network."""
        return self.total_prefix

    def get_host_ip(self) -> str:
        """
        Get the host's IP on the overlay network.

        Host always gets the .1 address in the first subnet (node_id=0).
        e.g., 10.0.0.1 for default config, 10.16.0.1 for 10.16.0.0/12/6/14
        """
        base_int = int(self.base_network.network_address)
        return str(ipaddress.IPv4Address(base_int + 1))

    def get_runner_subnet(self, runner_id: int) -> str:
        """
        Get the subnet for a runner.

        Args:
            runner_id: Runner ID (1 to max_runners)

        Returns:
            Subnet in CIDR notation (e.g., "10.1.0.0/16")
        """
        self._validate_runner_id(runner_id)

        base_int = int(self.base_network.network_address)
        # Shift runner_id to the correct position
        # Node bits sit between total_prefix and subnet_bits
        runner_offset = runner_id << self.subnet_bits
        subnet_addr = base_int + runner_offset

        return f"{ipaddress.IPv4Address(subnet_addr)}/{self.runner_prefix}"

    def get_runner_gateway(self, runner_id: int) -> str:
        """
        Get the gateway IP for a runner's subnet.

        The gateway is the .1 address within the runner's subnet.

        Args:
            runner_id: Runner ID (1 to max_runners)

        Returns:
            Gateway IP (e.g., "10.1.0.1")
        """
        self._validate_runner_id(runner_id)

        base_int = int(self.base_network.network_address)
        runner_offset = runner_id << self.subnet_bits
        gateway_addr = base_int + runner_offset + 1

        return str(ipaddress.IPv4Address(gateway_addr))

    def get_host_ip_on_runner_subnet(self, runner_id: int) -> str:
        """
        Get the host's IP within a runner's subnet.

        This is used for the VXLAN interface on the host side.
        Uses .254 relative to the subnet base (second to last before gateway range).

        Args:
            runner_id: Runner ID (1 to max_runners)

        Returns:
            Host IP on runner subnet (e.g., "10.1.0.254")
        """
        self._validate_runner_id(runner_id)

        base_int = int(self.base_network.network_address)
        runner_offset = runner_id << self.subnet_bits
        # Host IP is at offset 254 within the runner's subnet
        host_addr = base_int + runner_offset + 254

        return str(ipaddress.IPv4Address(host_addr))

    def get_container_ip_range(self, runner_id: int) -> tuple[str, str]:
        """
        Get the usable container IP range for a runner.

        Excludes: .0 (network), .1 (gateway), .254 (host), .255+ (broadcast region)

        Args:
            runner_id: Runner ID (1 to max_runners)

        Returns:
            Tuple of (first_ip, last_ip)
        """
        self._validate_runner_id(runner_id)

        base_int = int(self.base_network.network_address)
        runner_offset = runner_id << self.subnet_bits
        subnet_base = base_int + runner_offset

        # First usable: .2
        first_ip = ipaddress.IPv4Address(subnet_base + 2)

        # Last usable: depends on subnet size, but exclude .254 (host) and broadcast
        subnet_size = 2**self.subnet_bits
        # Max usable is one before broadcast, but also excluding .254
        # For /16: last would be .255.255 broadcast, so last usable is .255.253
        # But we also reserve .254 for host, so we need to handle gaps

        # Containers get .2 to .253, .255 to subnet_max-1 (excluding .254 and broadcast)
        # Simplified: report main range .2 to .253, rest is secondary
        # For now, report the full usable range excluding .254
        last_addr = (
            subnet_base + subnet_size - 2
        )  # -1 for broadcast, -1 to get last usable

        # If last_addr would be .254, skip it
        if (last_addr & 0xFF) == 254:
            last_addr -= 1

        last_ip = ipaddress.IPv4Address(last_addr)

        return (str(first_ip), str(last_ip))

    def get_overlay_network_cidr(self) -> str:
        """
        Get the full overlay network in CIDR notation.

        Used for routing rules (e.g., iptables -s 10.0.0.0/8).

        Returns:
            Network CIDR (e.g., "10.0.0.0/8")
        """
        return str(self.base_network)

    def _validate_runner_id(self, runner_id: int) -> None:
        """Validate runner ID is in valid range."""
        if runner_id < 1 or runner_id > self.max_runners:
            raise ValueError(
                f"Invalid runner_id: {runner_id}. "
                f"Must be between 1 and {self.max_runners}."
            )

    def __str__(self) -> str:
        """Return the configuration in format string."""
        base_ip = str(self.base_network.network_address)
        return f"{base_ip}/{self.total_prefix}/{self.node_bits}/{self.subnet_bits}"

    def __repr__(self) -> str:
        return (
            f"OverlaySubnetConfig({self}, "
            f"max_runners={self.max_runners}, "
            f"ips_per_runner={self.ips_per_runner})"
        )
