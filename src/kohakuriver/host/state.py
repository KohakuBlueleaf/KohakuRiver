"""
Shared state accessors for host modules.

Avoids circular imports between host/app.py and host/endpoints/*.
The app module sets these references during initialization; endpoint
and background modules read them via the getters.
"""

from kohakuriver.host.config import config

_overlay_manager = None
_ip_reservation_manager = None


def set_overlay_manager(manager):
    global _overlay_manager
    _overlay_manager = manager


def set_ip_reservation_manager(manager):
    global _ip_reservation_manager
    _ip_reservation_manager = manager


def get_overlay_manager():
    """Get the overlay network manager instance (or None)."""
    if not config.OVERLAY_ENABLED:
        return None
    return _overlay_manager


def get_ip_reservation_manager():
    """Get the IP reservation manager instance (or None)."""
    if not config.OVERLAY_ENABLED:
        return None
    return _ip_reservation_manager
