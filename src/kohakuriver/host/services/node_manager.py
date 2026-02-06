"""
Node Management Service.

Handles node resource calculations and scheduling queries.
"""

import json
from collections import defaultdict

import peewee

from kohakuriver.db.node import Node
from kohakuriver.db.task import Task
from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Resource Calculations
# =============================================================================


def get_node_available_cores(node: Node) -> int:
    """
    Calculate available cores for a node.

    Args:
        node: Node to check.

    Returns:
        Number of available cores (total - running tasks).
    """
    running_cores = (
        Task.select(peewee.fn.SUM(Task.required_cores))
        .where(
            (Task.assigned_node == node.hostname)
            & (Task.status.in_(["running", "assigning"]))
        )
        .scalar()
    )
    used = running_cores or 0
    return node.total_cores - used


def get_node_available_gpus(node: Node) -> set[int]:
    """
    Calculate available GPU indices for a node.

    Args:
        node: Node to check.

    Returns:
        Set of available GPU indices (integers).
    """
    # Get all GPU indices from node info
    gpu_info = node.get_gpu_info()
    all_gpu_ids = set(gpu.get("gpu_id", i) for i, gpu in enumerate(gpu_info))

    # Get GPUs in use by running tasks
    running_tasks = Task.select().where(
        (Task.assigned_node == node.hostname)
        & (Task.status.in_(["running", "assigning"]))
    )

    used_gpus = set()
    for task in running_tasks:
        if task.required_gpus:
            gpus = json.loads(task.required_gpus)
            used_gpus.update(gpus)

    available = all_gpu_ids - used_gpus
    logger.debug(
        f"Node {node.hostname}: all_gpus={all_gpu_ids}, "
        f"used={used_gpus}, available={available}"
    )
    return available


def get_node_available_memory(node: Node) -> int:
    """
    Calculate available memory for a node.

    Args:
        node: Node to check.

    Returns:
        Available memory in bytes.
    """
    # Get memory reserved by running tasks
    running_memory = (
        Task.select(peewee.fn.SUM(Task.required_memory_bytes))
        .where(
            (Task.assigned_node == node.hostname)
            & (Task.status.in_(["running", "assigning"]))
        )
        .scalar()
    )
    reserved = running_memory or 0

    # Available = total - max(reserved, currently_used)
    currently_used = node.memory_used_bytes or 0
    total = node.memory_total_bytes or 0

    return max(0, total - max(reserved, currently_used))


# =============================================================================
# Node Selection
# =============================================================================


def find_suitable_node(
    required_cores: int,
    required_gpus: list[str] | None = None,
    required_memory_bytes: int | None = None,
    target_hostname: str | None = None,
    target_numa_node_id: int | None = None,
) -> Node | None:
    """
    Find a suitable node for task execution.

    Args:
        required_cores: Number of cores needed.
        required_gpus: List of specific GPU UUIDs needed.
        required_memory_bytes: Memory needed in bytes.
        target_hostname: Specific hostname to use.
        target_numa_node_id: Specific NUMA node to use.

    Returns:
        Suitable Node or None if not found.
    """
    # Start with online nodes
    query = Node.select().where(Node.status == "online")

    if target_hostname:
        query = query.where(Node.hostname == target_hostname)

    nodes: list[Node] = list(query)

    if not nodes:
        logger.warning("No online nodes available")
        return None

    # Filter by resource requirements
    suitable_nodes = []

    for node in nodes:
        if not _node_meets_requirements(
            node,
            required_cores,
            required_gpus,
            required_memory_bytes,
            target_numa_node_id,
        ):
            continue

        available_cores = get_node_available_cores(node)
        suitable_nodes.append((node, available_cores))

    if not suitable_nodes:
        logger.warning(
            f"No suitable nodes found for requirements: "
            f"cores={required_cores}, gpus={required_gpus}, "
            f"memory={required_memory_bytes}"
        )
        return None

    # Sort by available cores (prefer nodes with more free resources)
    suitable_nodes.sort(key=lambda x: x[1], reverse=True)
    return suitable_nodes[0][0]


def find_suitable_node_for_vm(
    required_cores: int,
    required_gpus: list[int] | None = None,
    required_memory_bytes: int | None = None,
    target_hostname: str | None = None,
) -> Node | None:
    """
    Find a suitable VM-capable node for QEMU VPS.

    Filters for nodes with vm_capable=True and matching VFIO GPUs.

    Args:
        required_cores: Number of cores needed.
        required_gpus: List of GPU IDs needed (matched against VFIO-capable GPUs).
        required_memory_bytes: Memory needed in bytes.
        target_hostname: Specific hostname to use.

    Returns:
        Suitable Node or None if not found.
    """
    query = Node.select().where((Node.status == "online") & (Node.vm_capable == True))

    if target_hostname:
        query = query.where(Node.hostname == target_hostname)

    nodes: list[Node] = list(query)

    if not nodes:
        logger.warning("No VM-capable online nodes available")
        return None

    suitable_nodes = []

    for node in nodes:
        # Check cores
        available_cores = get_node_available_cores(node)
        if available_cores < required_cores:
            continue

        # Check memory
        if required_memory_bytes:
            available_memory = get_node_available_memory(node)
            if available_memory < required_memory_bytes:
                continue

        # Check VFIO GPUs if required
        if required_gpus:
            vfio_gpus = node.get_vfio_gpus()
            vfio_gpu_ids = {g.get("gpu_id") for g in vfio_gpus}
            available_gpus = get_node_available_gpus(node)
            # GPU must be both VFIO-capable and not in use
            available_vfio = vfio_gpu_ids & available_gpus
            if not all(gpu in available_vfio for gpu in required_gpus):
                continue

        suitable_nodes.append((node, available_cores))

    if not suitable_nodes:
        logger.warning(
            f"No suitable VM-capable nodes found for requirements: "
            f"cores={required_cores}, gpus={required_gpus}, "
            f"memory={required_memory_bytes}"
        )
        return None

    suitable_nodes.sort(key=lambda x: x[1], reverse=True)
    return suitable_nodes[0][0]


def _node_meets_requirements(
    node: Node,
    required_cores: int,
    required_gpus: list[str] | None,
    required_memory_bytes: int | None,
    target_numa_node_id: int | None,
) -> bool:
    """Check if a node meets the specified requirements."""
    # Check cores
    available_cores = get_node_available_cores(node)
    if available_cores < required_cores:
        return False

    # Check GPUs if required
    if required_gpus:
        available_gpus = get_node_available_gpus(node)
        if not all(gpu in available_gpus for gpu in required_gpus):
            return False

    # Check memory if required
    if required_memory_bytes:
        available_memory = get_node_available_memory(node)
        if available_memory < required_memory_bytes:
            return False

    # Check NUMA node if specified
    if target_numa_node_id is not None:
        numa_topology = node.get_numa_topology()
        numa_nodes = numa_topology.get("numa_nodes", [])
        numa_ids = [n.get("id") for n in numa_nodes]
        if target_numa_node_id not in numa_ids:
            return False

    return True


# =============================================================================
# Status Queries
# =============================================================================


def get_all_nodes_status() -> list[dict]:
    """
    Get status of all nodes with resource usage.

    Returns:
        List of node status dictionaries.
    """
    nodes: list[Node] = list(Node.select())
    cores_in_use = _calculate_cores_in_use(nodes)

    return [_build_node_status(node, cores_in_use) for node in nodes]


def _calculate_cores_in_use(nodes: list[Node]) -> dict[str, int]:
    """Calculate cores in use for all online nodes."""
    online_hostnames = [n.hostname for n in nodes if n.status == "online"]

    if not online_hostnames:
        return {}

    cores_in_use: dict[str, int] = defaultdict(int)

    running_tasks_usage = (
        Task.select(
            Task.assigned_node,
            peewee.fn.SUM(Task.required_cores).alias("used_cores"),
        )
        .where(
            (Task.status.in_(["running", "assigning"]))
            & (Task.assigned_node << online_hostnames)
        )
        .group_by(Task.assigned_node)
    )

    for usage in running_tasks_usage:
        if usage.assigned_node:
            cores_in_use[usage.assigned_node] = usage.used_cores or 0

    return cores_in_use


def _build_node_status(node: Node, cores_in_use: dict[str, int]) -> dict:
    """Build status dictionary for a single node."""
    available = 0
    used = "N/A"

    if node.status == "online":
        used = cores_in_use.get(node.hostname, 0)
        available = node.total_cores - used

    return {
        "hostname": node.hostname,
        "url": node.url,
        "total_cores": node.total_cores,
        "cores_in_use": used,
        "available_cores": available,
        "status": node.status,
        "last_heartbeat": (
            node.last_heartbeat.isoformat() if node.last_heartbeat else None
        ),
        "numa_topology": node.get_numa_topology(),
        "gpu_info": node.get_gpu_info(),
        "cpu_percent": node.cpu_percent,
        "memory_percent": node.memory_percent,
        "memory_used_bytes": node.memory_used_bytes,
        "memory_total_bytes": node.memory_total_bytes,
        "current_avg_temp": node.current_avg_temp,
        "current_max_temp": node.current_max_temp,
        "vm_capable": node.vm_capable,
        "vfio_gpus": node.get_vfio_gpus(),
        "runner_version": node.runner_version,
    }
