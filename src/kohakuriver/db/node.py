"""
Node database model for HakuRiver.

This module defines the Node model which represents compute nodes
in the cluster, storing metadata, health status, and resource information.
"""

import datetime
import json

import peewee

from kohakuriver.db.base import BaseModel
from kohakuriver.models.enums import NodeStatus


# =============================================================================
# Node Model
# =============================================================================


class Node(BaseModel):
    """
    Represents a compute node in the cluster.

    Stores node metadata, health status, and resource information.
    Nodes register with the host and send periodic heartbeats.

    Attributes:
        hostname: Unique node identifier (primary key).
        url: Runner API URL for communication.
        total_cores: Number of CPU cores available.
        status: Current node status ('online' or 'offline').
    """

    # -------------------------------------------------------------------------
    # Primary Identification
    # -------------------------------------------------------------------------

    hostname = peewee.CharField(unique=True, primary_key=True)
    url = peewee.CharField()  # Runner URL, e.g., http://192.168.1.101:8001

    # -------------------------------------------------------------------------
    # Hardware Resources
    # -------------------------------------------------------------------------

    total_cores = peewee.IntegerField()
    memory_total_bytes = peewee.BigIntegerField(null=True)

    # -------------------------------------------------------------------------
    # Status and Health
    # -------------------------------------------------------------------------

    status = peewee.CharField(default=NodeStatus.ONLINE.value)
    last_heartbeat = peewee.DateTimeField(default=datetime.datetime.now)

    # -------------------------------------------------------------------------
    # Runtime Metrics (updated via heartbeat)
    # -------------------------------------------------------------------------

    cpu_percent = peewee.FloatField(null=True)
    memory_percent = peewee.FloatField(null=True)
    memory_used_bytes = peewee.BigIntegerField(null=True)
    current_avg_temp = peewee.FloatField(null=True)
    current_max_temp = peewee.FloatField(null=True)

    # -------------------------------------------------------------------------
    # Topology (stored as JSON)
    # -------------------------------------------------------------------------

    numa_topology = peewee.TextField(null=True)
    gpu_info = peewee.TextField(null=True)

    # -------------------------------------------------------------------------
    # VM Capability
    # -------------------------------------------------------------------------

    vm_capable = peewee.BooleanField(default=False)
    vfio_gpus = peewee.TextField(null=True)  # JSON list of VFIO-capable GPUs

    # -------------------------------------------------------------------------
    # Runner Version
    # -------------------------------------------------------------------------

    runner_version = peewee.CharField(null=True)  # KohakuRiver version string

    class Meta:
        table_name = "nodes"

    # =========================================================================
    # JSON Field Accessors
    # =========================================================================

    def get_numa_topology(self) -> dict[int, list[int]] | None:
        """
        Parse stored NUMA topology JSON into a dictionary.

        Returns:
            Dict mapping NUMA node ID to list of CPU core IDs,
            or None if not set or invalid.
        """
        if not self.numa_topology:
            return None
        try:
            data = json.loads(self.numa_topology)
            return {int(k): v for k, v in data.items()}
        except (json.JSONDecodeError, ValueError):
            return None

    def set_numa_topology(self, topology: dict[int, list[int]] | None) -> None:
        """Store NUMA topology as JSON."""
        if topology is None:
            self.numa_topology = None
        else:
            self.numa_topology = json.dumps(topology)

    def get_gpu_info(self) -> list[dict]:
        """
        Parse stored GPU info JSON into a list of dictionaries.

        Returns:
            List of GPU info dicts, or empty list if not set or invalid.
        """
        if not self.gpu_info:
            return []
        try:
            return json.loads(self.gpu_info)
        except json.JSONDecodeError:
            return []

    def set_gpu_info(self, gpus: list[dict] | None) -> None:
        """Store GPU info as JSON."""
        if gpus is None:
            self.gpu_info = None
        else:
            self.gpu_info = json.dumps(gpus)

    def get_vfio_gpus(self) -> list[dict]:
        """Parse stored VFIO GPU info JSON into a list of dictionaries."""
        if not self.vfio_gpus:
            return []
        try:
            return json.loads(self.vfio_gpus)
        except json.JSONDecodeError:
            return []

    def set_vfio_gpus(self, gpus: list[dict] | None) -> None:
        """Store VFIO GPU info as JSON."""
        if gpus is None:
            self.vfio_gpus = None
        else:
            self.vfio_gpus = json.dumps(gpus)

    # =========================================================================
    # Status Helpers
    # =========================================================================

    def is_online(self) -> bool:
        """Check if node is online."""
        return self.status == NodeStatus.ONLINE.value

    def is_offline(self) -> bool:
        """Check if node is offline."""
        return self.status == NodeStatus.OFFLINE.value

    def mark_online(self) -> None:
        """Mark node as online."""
        self.status = NodeStatus.ONLINE.value

    def mark_offline(self) -> None:
        """Mark node as offline."""
        self.status = NodeStatus.OFFLINE.value

    def update_heartbeat(self) -> None:
        """Update last heartbeat time to now."""
        self.last_heartbeat = datetime.datetime.now()

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> dict:
        """Convert node to dictionary for API responses."""
        return {
            "hostname": self.hostname,
            "url": self.url,
            "total_cores": self.total_cores,
            "memory_total_bytes": self.memory_total_bytes,
            "status": self.status,
            "last_heartbeat": (
                self.last_heartbeat.isoformat() if self.last_heartbeat else None
            ),
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "memory_used_bytes": self.memory_used_bytes,
            "current_avg_temp": self.current_avg_temp,
            "current_max_temp": self.current_max_temp,
            "numa_topology": self.get_numa_topology(),
            "gpu_info": self.get_gpu_info(),
            "vm_capable": self.vm_capable,
            "vfio_gpus": self.get_vfio_gpus(),
            "runner_version": self.runner_version,
        }
