"""
IP Reservation System for Overlay Network.

Allows users to reserve container IPs before task submission, enabling
multi-node distributed training scenarios where master address must be
known before launching worker tasks.

Token Design:
- Tokens are encrypted and self-contained (include IP, node, expiry)
- Tokens can be decrypted by Host to validate without database lookup
- Format: base64(encrypt(json{ip, runner_name, expires_at}))
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from kohakuriver.utils.logger import get_logger

if TYPE_CHECKING:
    from kohakuriver.host.services.overlay_manager import OverlayNetworkManager

logger = get_logger(__name__)


# Default reservation TTL in seconds (5 minutes)
DEFAULT_RESERVATION_TTL = 300


@dataclass
class IPReservation:
    """Represents an IP address reservation."""

    ip: str
    runner_name: str
    runner_id: int
    token: str
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default_factory=lambda: datetime.now())
    container_id: str | None = None  # Set when used by a container

    def is_expired(self) -> bool:
        """Check if reservation has expired."""
        return datetime.now() > self.expires_at

    def is_used(self) -> bool:
        """Check if reservation is currently in use by a container."""
        return self.container_id is not None


class IPReservationManager:
    """
    Manages IP address reservations for the overlay network.

    Reservations are stored in-memory and cleaned up periodically.
    Tokens are cryptographically signed to prevent tampering.
    """

    def __init__(
        self,
        overlay_manager: OverlayNetworkManager,
        secret_key: str | None = None,
        default_ttl: int = DEFAULT_RESERVATION_TTL,
    ):
        """
        Initialize IP reservation manager.

        Args:
            overlay_manager: Reference to overlay network manager
            secret_key: Secret for token signing (auto-generated if not provided)
            default_ttl: Default reservation TTL in seconds
        """
        self.overlay_manager = overlay_manager
        self.secret_key = secret_key or secrets.token_hex(32)
        self.default_ttl = default_ttl

        # ip -> IPReservation
        self._reservations: dict[str, IPReservation] = {}
        # token -> ip (for quick lookup)
        self._token_to_ip: dict[str, str] = {}
        self._lock = asyncio.Lock()

        # Track used IPs per runner (allocated to running containers)
        # These are IPs actually assigned to containers, not just reserved
        self._used_ips: dict[str, set[str]] = {}  # runner_name -> set of IPs

        logger.info("IP reservation manager initialized")

    def _generate_token(self, ip: str, runner_name: str, expires_at: datetime) -> str:
        """
        Generate a signed token for an IP reservation.

        Token format: base64(json_payload.signature)
        The signature ensures the token hasn't been tampered with.
        """
        payload = {
            "ip": ip,
            "runner": runner_name,
            "exp": int(expires_at.timestamp()),
        }
        payload_json = json.dumps(payload, separators=(",", ":"))

        # Create HMAC signature
        signature = hashlib.sha256(
            (payload_json + self.secret_key).encode()
        ).hexdigest()[:16]

        # Combine and encode
        token_data = f"{payload_json}.{signature}"
        return base64.urlsafe_b64encode(token_data.encode()).decode()

    def _verify_token(self, token: str) -> dict | None:
        """
        Verify and decode a token.

        Returns:
            Decoded payload if valid, None if invalid or expired.
        """
        try:
            token_data = base64.urlsafe_b64decode(token.encode()).decode()
            payload_json, signature = token_data.rsplit(".", 1)

            # Verify signature
            expected_sig = hashlib.sha256(
                (payload_json + self.secret_key).encode()
            ).hexdigest()[:16]

            if signature != expected_sig:
                logger.warning("Token signature verification failed")
                return None

            payload = json.loads(payload_json)

            # Check expiry
            if payload["exp"] < time.time():
                logger.debug(f"Token expired for IP {payload['ip']}")
                return None

            return payload

        except Exception as e:
            logger.warning(f"Token verification error: {e}")
            return None

    def _get_available_ips_for_runner(self, runner_name: str) -> list[str]:
        """
        Get list of available IPs for a runner.

        Excludes:
        - Reserved IPs (not yet expired)
        - Used IPs (assigned to running containers)
        """
        # Get runner allocation
        allocation = self.overlay_manager._allocations.get(runner_name)
        if not allocation:
            return []

        runner_id = allocation.runner_id
        subnet_config = self.overlay_manager.subnet_config

        # Get IP range for this runner
        first_ip_str, last_ip_str = subnet_config.get_container_ip_range(runner_id)
        first_ip = ipaddress.IPv4Address(first_ip_str)
        last_ip = ipaddress.IPv4Address(last_ip_str)

        # Get reserved and used IPs
        reserved_ips = {
            r.ip
            for r in self._reservations.values()
            if r.runner_name == runner_name and not r.is_expired()
        }
        used_ips = self._used_ips.get(runner_name, set())
        unavailable = reserved_ips | used_ips

        # Also exclude .254 (host on runner subnet)
        host_ip = subnet_config.get_host_ip_on_runner_subnet(runner_id)

        available = []
        current = first_ip
        while current <= last_ip:
            ip_str = str(current)
            if ip_str not in unavailable and ip_str != host_ip:
                available.append(ip_str)
            current += 1

        return available

    async def get_available_ips(
        self,
        runner_name: str | None = None,
        limit: int = 100,
    ) -> dict[str, list[str]]:
        """
        Get available IPs, optionally filtered by runner.

        Args:
            runner_name: Specific runner to query (None for all)
            limit: Max IPs to return per runner

        Returns:
            Dict of runner_name -> list of available IPs
        """
        async with self._lock:
            result = {}

            if runner_name:
                runners = [runner_name]
            else:
                runners = list(self.overlay_manager._allocations)

            for name in runners:
                ips = self._get_available_ips_for_runner(name)
                result[name] = ips[:limit]

            return result

    async def reserve_ip(
        self,
        runner_name: str,
        ip: str | None = None,
        ttl: int | None = None,
    ) -> IPReservation | None:
        """
        Reserve an IP address on a specific runner.

        Args:
            runner_name: Runner to reserve IP on
            ip: Specific IP to reserve (None for random available)
            ttl: Time-to-live in seconds (None for default)

        Returns:
            IPReservation if successful, None if IP unavailable
        """
        async with self._lock:
            # Cleanup expired reservations first
            self._cleanup_expired_sync()

            # Verify runner exists
            allocation = self.overlay_manager._allocations.get(runner_name)
            if not allocation:
                logger.warning(f"Cannot reserve IP: runner '{runner_name}' not found")
                return None

            runner_id = allocation.runner_id
            ttl = ttl or self.default_ttl

            # Get or validate IP
            if ip is None:
                # Pick a random available IP
                available = self._get_available_ips_for_runner(runner_name)
                if not available:
                    logger.warning(f"No available IPs for runner '{runner_name}'")
                    return None
                # Pick a random one for better distribution
                ip = secrets.choice(available)
            else:
                # Validate the requested IP
                available = self._get_available_ips_for_runner(runner_name)
                if ip not in available:
                    logger.warning(
                        f"IP {ip} is not available on runner '{runner_name}'"
                    )
                    return None

            # Create reservation
            expires_at = datetime.now() + timedelta(seconds=ttl)
            token = self._generate_token(ip, runner_name, expires_at)

            reservation = IPReservation(
                ip=ip,
                runner_name=runner_name,
                runner_id=runner_id,
                token=token,
                expires_at=expires_at,
            )

            self._reservations[ip] = reservation
            self._token_to_ip[token] = ip

            logger.info(
                f"Reserved IP {ip} on runner '{runner_name}' "
                f"(expires in {ttl}s, token={token[:16]}...)"
            )

            return reservation

    async def validate_token(
        self,
        token: str,
        expected_runner: str | None = None,
    ) -> IPReservation | None:
        """
        Validate a reservation token and return the reservation.

        Args:
            token: Reservation token to validate
            expected_runner: If provided, verify token is for this runner

        Returns:
            IPReservation if valid and not expired, None otherwise
        """
        # First verify token signature and expiry
        payload = self._verify_token(token)
        if not payload:
            return None

        async with self._lock:
            ip = self._token_to_ip.get(token)
            if not ip:
                # Token valid but reservation was released/expired
                logger.debug(f"Token valid but reservation not found")
                return None

            reservation = self._reservations.get(ip)
            if not reservation:
                return None

            # Verify runner if specified
            if expected_runner and reservation.runner_name != expected_runner:
                logger.warning(
                    f"Token runner mismatch: expected '{expected_runner}', "
                    f"got '{reservation.runner_name}'"
                )
                return None

            # Check if already used
            if reservation.is_used():
                logger.warning(f"Reservation for {ip} is already in use")
                return None

            return reservation

    async def use_reservation(
        self,
        token: str,
        container_id: str,
        expected_runner: str | None = None,
    ) -> str | None:
        """
        Mark a reservation as used by a container.

        Args:
            token: Reservation token
            container_id: Container ID using this IP
            expected_runner: If provided, verify token is for this runner

        Returns:
            Reserved IP if successful, None otherwise
        """
        async with self._lock:
            # Validate token first
            payload = self._verify_token(token)
            if not payload:
                return None

            ip = self._token_to_ip.get(token)
            if not ip:
                return None

            reservation = self._reservations.get(ip)
            if not reservation:
                return None

            if expected_runner and reservation.runner_name != expected_runner:
                logger.warning(f"Token runner mismatch during use")
                return None

            if reservation.is_used():
                logger.warning(
                    f"Reservation for {ip} already used by another container"
                )
                return None

            # Mark as used
            reservation.container_id = container_id

            # Add to used IPs tracking
            if reservation.runner_name not in self._used_ips:
                self._used_ips[reservation.runner_name] = set()
            self._used_ips[reservation.runner_name].add(ip)

            logger.info(
                f"Reservation {ip} on '{reservation.runner_name}' "
                f"now used by container {container_id}"
            )

            return ip

    async def release_by_container(self, container_id: str) -> list[str]:
        """
        Release all reservations used by a container.

        Called when a container exits to free up IPs.

        Args:
            container_id: Container ID

        Returns:
            List of released IPs
        """
        async with self._lock:
            released = []

            for ip, reservation in list(self._reservations.items()):
                if reservation.container_id == container_id:
                    # Remove from tracking
                    if reservation.runner_name in self._used_ips:
                        self._used_ips[reservation.runner_name].discard(ip)

                    # Remove reservation
                    del self._reservations[ip]
                    if reservation.token in self._token_to_ip:
                        del self._token_to_ip[reservation.token]

                    released.append(ip)
                    logger.info(
                        f"Released IP {ip} from container {container_id} "
                        f"on runner '{reservation.runner_name}'"
                    )

            return released

    async def release_by_token(self, token: str) -> bool:
        """
        Release a reservation by token.

        Args:
            token: Reservation token

        Returns:
            True if released, False if not found or in use
        """
        async with self._lock:
            ip = self._token_to_ip.get(token)
            if not ip:
                return False

            reservation = self._reservations.get(ip)
            if not reservation:
                return False

            # Don't allow release if in use
            if reservation.is_used():
                logger.warning(
                    f"Cannot release reservation {ip}: in use by container "
                    f"{reservation.container_id}"
                )
                return False

            # Release
            del self._reservations[ip]
            del self._token_to_ip[token]

            logger.info(f"Released reservation for {ip} on '{reservation.runner_name}'")
            return True

    async def mark_ip_used(self, runner_name: str, ip: str, container_id: str) -> None:
        """
        Mark an IP as used by a container (without reservation).

        Called when containers are assigned IPs dynamically.

        Args:
            runner_name: Runner hosting the container
            ip: IP address assigned
            container_id: Container ID
        """
        async with self._lock:
            if runner_name not in self._used_ips:
                self._used_ips[runner_name] = set()
            self._used_ips[runner_name].add(ip)
            logger.debug(f"Marked IP {ip} as used by {container_id} on {runner_name}")

    async def mark_ip_free(self, runner_name: str, ip: str) -> None:
        """
        Mark an IP as free (container exited).

        Args:
            runner_name: Runner that hosted the container
            ip: IP address to free
        """
        async with self._lock:
            if runner_name in self._used_ips:
                self._used_ips[runner_name].discard(ip)
                logger.debug(f"Marked IP {ip} as free on {runner_name}")

            # Also clean up any reservation for this IP
            if ip in self._reservations:
                reservation = self._reservations[ip]
                if reservation.token in self._token_to_ip:
                    del self._token_to_ip[reservation.token]
                del self._reservations[ip]

    async def get_reservations(
        self,
        runner_name: str | None = None,
        include_used: bool = True,
    ) -> list[IPReservation]:
        """
        Get all active reservations.

        Args:
            runner_name: Filter by runner (None for all)
            include_used: Include reservations in use

        Returns:
            List of reservations
        """
        async with self._lock:
            self._cleanup_expired_sync()

            reservations = list(self._reservations.values())

            if runner_name:
                reservations = [r for r in reservations if r.runner_name == runner_name]

            if not include_used:
                reservations = [r for r in reservations if not r.is_used()]

            return reservations

    async def get_ip_info(self, runner_name: str) -> dict:
        """
        Get IP allocation info for a runner.

        Returns:
            Dict with total, available, reserved, used counts and ranges
        """
        async with self._lock:
            allocation = self.overlay_manager._allocations.get(runner_name)
            if not allocation:
                return {"error": f"Runner '{runner_name}' not found"}

            runner_id = allocation.runner_id
            subnet_config = self.overlay_manager.subnet_config

            first_ip, last_ip = subnet_config.get_container_ip_range(runner_id)
            first_int = int(ipaddress.IPv4Address(first_ip))
            last_int = int(ipaddress.IPv4Address(last_ip))
            total = last_int - first_int + 1

            reserved_count = sum(
                1
                for r in self._reservations.values()
                if r.runner_name == runner_name
                and not r.is_expired()
                and not r.is_used()
            )
            used_count = len(self._used_ips.get(runner_name, set()))
            available_count = total - reserved_count - used_count

            return {
                "runner_name": runner_name,
                "runner_id": runner_id,
                "subnet": allocation.subnet,
                "gateway": allocation.gateway,
                "ip_range": {"first": first_ip, "last": last_ip},
                "total_ips": total,
                "available": available_count,
                "reserved": reserved_count,
                "used": used_count,
            }

    def _cleanup_expired_sync(self) -> int:
        """
        Remove expired reservations (sync version, call within lock).

        Returns:
            Number of cleaned up reservations
        """
        expired = [
            (ip, r)
            for ip, r in self._reservations.items()
            if r.is_expired() and not r.is_used()
        ]

        for ip, reservation in expired:
            del self._reservations[ip]
            if reservation.token in self._token_to_ip:
                del self._token_to_ip[reservation.token]
            logger.debug(f"Cleaned up expired reservation for {ip}")

        return len(expired)

    async def cleanup_expired(self) -> int:
        """
        Remove expired reservations.

        Returns:
            Number of cleaned up reservations
        """
        async with self._lock:
            return self._cleanup_expired_sync()

    async def get_stats(self) -> dict:
        """Get reservation statistics."""
        async with self._lock:
            self._cleanup_expired_sync()

            total_reserved = len(self._reservations)
            in_use = sum(1 for r in self._reservations.values() if r.is_used())
            pending = total_reserved - in_use

            total_used_ips = sum(len(ips) for ips in self._used_ips.values())

            return {
                "total_reservations": total_reserved,
                "pending_reservations": pending,
                "in_use_reservations": in_use,
                "total_used_ips": total_used_ips,
                "runners_with_used_ips": len(self._used_ips),
            }
