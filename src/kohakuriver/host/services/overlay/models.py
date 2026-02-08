"""Data models for overlay network management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OverlayAllocation:
    """Represents an overlay network allocation for a runner."""

    runner_name: str
    runner_id: int
    physical_ip: str
    subnet: str  # "10.X.0.0/16"
    gateway: str  # "10.X.0.1"
    vxlan_device: str  # "vxlan_kohakuriver_xxx"
    last_used: datetime = field(default_factory=datetime.now)
    is_active: bool = False
