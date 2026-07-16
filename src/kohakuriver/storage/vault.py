"""
Persistent storage for HakuRiver using KohakuVault.

This module provides persistent state storage for runner nodes using the
KohakuVault library. It enables state recovery after runner restarts and
tracks running tasks, VPS sessions, and paused tasks.

Storage Classes:
    - RunnerStateStore: Base dict-like storage interface
    - TaskStateStore: Tracks running task containers
    - VPSStateStore: Tracks VPS sessions
    - PausedTaskStore: Tracks paused tasks
"""

from kohakuvault import KVault

from kohakuriver.exceptions import StorageError

# =============================================================================
# Base Storage Class
# =============================================================================


class RunnerStateStore:
    """
    Persistent state storage using KohakuVault (SQLite-backed).

    Provides a dict-like interface for storing and retrieving task state.
    Used for recovery after runner restart.

    Attributes:
        vault: The underlying KohakuVault instance.
        _table: The database table name for this store.
    """

    def __init__(self, db_path: str, table: str = "runner_state"):
        """
        Initialize the state store.

        Args:
            db_path: Path to the SQLite database file.
            table: Table name for this store instance.

        Raises:
            StorageError: If the database cannot be initialized.
        """
        try:
            self.vault = KVault(db_path, table=table)
        except Exception as e:
            raise StorageError(f"Failed to initialize storage at {db_path}: {e}") from e
        self._table = table

    # -------------------------------------------------------------------------
    # Dict-Like Interface
    # -------------------------------------------------------------------------

    def __getitem__(self, key: str) -> dict:
        """Get a value by key."""
        return self.vault[key]

    def __setitem__(self, key: str, value: dict) -> None:
        """Set a value by key."""
        self.vault[key] = value

    def __delitem__(self, key: str) -> None:
        """Delete a value by key."""
        del self.vault[key]

    def __contains__(self, key: str) -> bool:
        """Check if key exists."""
        try:
            _ = self.vault[key]
            return True
        except KeyError:
            return False

    def __iter__(self):
        """Iterate over keys."""
        return iter(self.vault)

    def __len__(self) -> int:
        """Return number of items."""
        return len(list(self.vault))

    # -------------------------------------------------------------------------
    # Dict Methods
    # -------------------------------------------------------------------------

    def get(self, key: str, default: dict | None = None) -> dict | None:
        """
        Get a value with optional default.

        Args:
            key: The key to retrieve.
            default: Value to return if key doesn't exist.

        Returns:
            The stored value, or default if not found.
        """
        try:
            return self.vault[key]
        except KeyError:
            return default

    def keys(self) -> list[str]:
        """Return all keys in the store."""
        return list(self.vault)

    def items(self) -> list[tuple[str, dict]]:
        """Return all key-value pairs."""
        return [(k, self.vault[k]) for k in self.vault]

    def values(self) -> list[dict]:
        """Return all values."""
        return [self.vault[k] for k in self.vault]

    def clear(self) -> None:
        """Remove all items from the store."""
        for key in list(self.vault):
            del self.vault[key]

    def pop(self, key: str, default: dict | None = None) -> dict | None:
        """
        Remove and return a value.

        Args:
            key: The key to remove.
            default: Value to return if key doesn't exist.

        Returns:
            The removed value, or default if not found.
        """
        try:
            value = self.vault[key]
            del self.vault[key]
            return value
        except KeyError:
            return default


# =============================================================================
# Specialized Storage Classes
# =============================================================================


class TaskStateStore(RunnerStateStore):
    """
    Storage for tracking running task containers.

    Persists task state including container name, allocated resources,
    and NUMA node binding for recovery after runner restart.
    """

    def __init__(self, db_path: str):
        """
        Initialize the task state store.

        Args:
            db_path: Path to the SQLite database file.
        """
        super().__init__(db_path, table="running_tasks")

    def add_task(
        self,
        task_id: int,
        container_name: str,
        allocated_cores: list[int] | None = None,
        allocated_gpus: list[int] | None = None,
        numa_node: int | None = None,
    ) -> None:
        """
        Add a running task to the store.

        Args:
            task_id: Unique task identifier.
            container_name: Docker container name.
            allocated_cores: List of allocated CPU core IDs.
            allocated_gpus: List of allocated GPU IDs.
            numa_node: NUMA node ID if bound to specific node.
        """
        self[str(task_id)] = {
            "task_id": task_id,
            "container_name": container_name,
            "allocated_cores": allocated_cores or [],
            "allocated_gpus": allocated_gpus or [],
            "numa_node": numa_node,
        }

    def remove_task(self, task_id: int) -> dict | None:
        """
        Remove a task and return its data.

        Args:
            task_id: The task ID to remove.

        Returns:
            The task data, or None if not found.
        """
        return self.pop(str(task_id))

    def get_task(self, task_id: int) -> dict | None:
        """
        Get task data by ID.

        Args:
            task_id: The task ID to retrieve.

        Returns:
            The task data, or None if not found.
        """
        return self.get(str(task_id))

    def list_tasks(self) -> list[dict]:
        """Return all running tasks."""
        return self.values()

    def get_all_task_ids(self) -> list[int]:
        """Return all running task IDs as integers."""
        return [int(k) for k in self.keys()]


class VPSStateStore(RunnerStateStore):
    """
    Storage for tracking VPS (Virtual Private Server) sessions.

    Persists VPS state including SSH port, authentication mode,
    and allocated resources for recovery after runner restart.
    """

    def __init__(self, db_path: str):
        """
        Initialize the VPS state store.

        Args:
            db_path: Path to the SQLite database file.
        """
        super().__init__(db_path, table="vps_sessions")

    def add_vps(
        self,
        task_id: int,
        container_name: str,
        ssh_port: int,
        has_key: bool = False,
        allocated_cores: list[int] | None = None,
        allocated_gpus: list[int] | None = None,
        numa_node: int | None = None,
    ) -> None:
        """
        Add a VPS session to the store.

        Args:
            task_id: Unique task identifier.
            container_name: Docker container name.
            ssh_port: SSH port mapped on the host.
            has_key: Whether SSH key authentication was configured.
            allocated_cores: List of allocated CPU core IDs.
            allocated_gpus: List of allocated GPU IDs.
            numa_node: NUMA node ID if bound to specific node.
        """
        self[str(task_id)] = {
            "task_id": task_id,
            "container_name": container_name,
            "ssh_port": ssh_port,
            "has_key": has_key,
            "allocated_cores": allocated_cores or [],
            "allocated_gpus": allocated_gpus or [],
            "numa_node": numa_node,
        }

    def remove_vps(self, task_id: int) -> dict | None:
        """
        Remove a VPS session and return its data.

        Args:
            task_id: The task ID to remove.

        Returns:
            The VPS data, or None if not found.
        """
        return self.pop(str(task_id))

    def get_vps(self, task_id: int) -> dict | None:
        """
        Get VPS session data by ID.

        Args:
            task_id: The task ID to retrieve.

        Returns:
            The VPS data, or None if not found.
        """
        return self.get(str(task_id))

    def list_vps(self) -> list[dict]:
        """Return all VPS sessions."""
        return self.values()


class PausedTaskStore(RunnerStateStore):
    """
    Storage for tracking paused tasks.

    Simple store that tracks which tasks are currently paused,
    enabling proper state recovery after runner restart.
    """

    def __init__(self, db_path: str):
        """
        Initialize the paused task store.

        Args:
            db_path: Path to the SQLite database file.
        """
        super().__init__(db_path, table="paused_tasks")

    def add_paused(self, task_id: int, container_name: str) -> None:
        """
        Add a paused task to the store.

        Args:
            task_id: The task ID that was paused.
            container_name: Docker container name.
        """
        self[str(task_id)] = {
            "task_id": task_id,
            "container_name": container_name,
        }

    def remove_paused(self, task_id: int) -> dict | None:
        """
        Remove a paused task and return its data.

        Args:
            task_id: The task ID to remove.

        Returns:
            The paused task data, or None if not found.
        """
        return self.pop(str(task_id))

    def is_paused(self, task_id: int) -> bool:
        """
        Check if a task is currently paused.

        Args:
            task_id: The task ID to check.

        Returns:
            True if the task is paused, False otherwise.
        """
        return str(task_id) in self
