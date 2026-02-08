"""
Backward-compatibility shim.

The overlay manager has been split into the ``overlay`` subpackage.
This module re-exports the public names so that existing imports like::

    from kohakuriver.host.services.overlay_manager import OverlayNetworkManager

continue to work unchanged.
"""

from kohakuriver.host.services.overlay import OverlayAllocation, OverlayNetworkManager

__all__ = ["OverlayNetworkManager", "OverlayAllocation"]
