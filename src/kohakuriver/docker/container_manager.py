"""
Container lifecycle management mixin for DockerManager.

This module provides the ContainerManagerMixin class with methods for:
    - Container existence checks and retrieval
    - Container creation (generic, task, VPS)
    - Container lifecycle (start, stop, kill, pause, unpause, remove)
    - Container queries (port lookup, listing, cleanup)
"""

from docker.errors import APIError, ContainerError, ImageNotFound, NotFound
from docker.models.containers import Container
from docker.models.images import Image
from docker.types import DeviceRequest, Mount

from kohakuriver.docker.exceptions import (
    ContainerCreationError,
    ContainerNotFoundError,
)
from kohakuriver.docker.naming import (
    LABEL_MANAGED,
    make_labels,
    task_container_name,
    vps_container_name,
)
from kohakuriver.utils.logger import get_logger

log = get_logger(__name__)


class ContainerManagerMixin:
    """
    Mixin providing container lifecycle management methods.

    Expects ``self.client`` to be a docker-py client instance.
    """

    # =========================================================================
    # Container Existence and Retrieval
    # =========================================================================

    def container_exists(self, name: str) -> bool:
        """
        Check if a container exists.

        Args:
            name: Container name.

        Returns:
            True if container exists, False otherwise.
        """
        try:
            self.client.containers.get(name)
            return True
        except NotFound:
            return False

    def get_container(self, name: str) -> Container:
        """
        Get a container by name.

        Args:
            name: Container name.

        Returns:
            Container object.

        Raises:
            ContainerNotFoundError: If container doesn't exist.
        """
        try:
            return self.client.containers.get(name)
        except NotFound:
            raise ContainerNotFoundError(name)

    # =========================================================================
    # Container Creation
    # =========================================================================

    def create_container(
        self,
        image: str,
        name: str,
        command: str | list[str] = "sleep infinity",
        detach: bool = True,
        **kwargs,
    ) -> Container:
        """
        Create and start a container.

        Args:
            image: Docker image name/tag.
            name: Container name.
            command: Command to run.
            detach: Run in detached mode.
            **kwargs: Additional arguments passed to containers.run().

        Returns:
            Container object.

        Raises:
            ContainerCreationError: If container creation fails.
        """
        try:
            return self.client.containers.run(
                image,
                command,
                name=name,
                detach=detach,
                **kwargs,
            )
        except ImageNotFound:
            log.info(f"Image {image} not found locally, pulling...")
            self.client.images.pull(image)
            return self.client.containers.run(
                image,
                command,
                name=name,
                detach=detach,
                **kwargs,
            )
        except APIError as e:
            log.error(f"Failed to create container {name}: {e}")
            raise ContainerCreationError(str(e), name) from e

    def create_task_container(
        self,
        task_id: int,
        image: str,
        command: list[str],
        cpuset_cpus: str | None = None,
        cpuset_mems: str | None = None,
        mem_limit: str | None = None,
        gpu_ids: list[int] | None = None,
        mounts: list[Mount] | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str = "/shared",
        privileged: bool = False,
        node: str | None = None,
    ) -> Container:
        """
        Create a container for task execution.

        Args:
            task_id: Task ID.
            image: Docker image name/tag.
            command: Command to run.
            cpuset_cpus: CPUs to use (e.g., "0-3" or "0,1,2").
            cpuset_mems: NUMA nodes to use (e.g., "0" or "0,1").
            mem_limit: Memory limit (e.g., "2g").
            gpu_ids: List of GPU IDs to use.
            mounts: List of Mount objects.
            environment: Environment variables.
            working_dir: Working directory inside container.
            privileged: Run in privileged mode.
            node: Node hostname (for labeling).

        Returns:
            Container object.
        """
        container_name = task_container_name(task_id)
        labels = make_labels(task_id, "command", node)

        kwargs = self._build_container_kwargs(
            labels=labels,
            cpuset_cpus=cpuset_cpus,
            cpuset_mems=cpuset_mems,
            mem_limit=mem_limit,
            gpu_ids=gpu_ids,
            mounts=mounts,
            environment=environment,
            working_dir=working_dir,
            privileged=privileged,
            task_id=task_id,
        )
        kwargs["network_mode"] = "host"

        log.debug(f"Creating task container {container_name} with image {image}")
        return self.create_container(image, container_name, command, **kwargs)

    def create_vps_container(
        self,
        task_id: int,
        image: str,
        ssh_port: int,
        public_key: str | None = None,
        cpuset_cpus: str | None = None,
        cpuset_mems: str | None = None,
        mem_limit: str | None = None,
        gpu_ids: list[int] | None = None,
        mounts: list[Mount] | None = None,
        working_dir: str = "/shared",
        privileged: bool = False,
        node: str | None = None,
    ) -> Container:
        """
        Create a VPS container with SSH access.

        Args:
            task_id: Task ID.
            image: Docker image name/tag.
            ssh_port: Host port for SSH (mapped to container port 22).
            public_key: SSH public key (None = passwordless login).
            cpuset_cpus: CPUs to use.
            cpuset_mems: NUMA nodes to use.
            mem_limit: Memory limit.
            gpu_ids: List of GPU IDs.
            mounts: List of Mount objects.
            working_dir: Working directory.
            privileged: Run in privileged mode.
            node: Node hostname.

        Returns:
            Container object.
        """
        container_name = vps_container_name(task_id)
        labels = make_labels(task_id, "vps", node)

        setup_cmd = self._build_ssh_setup_command(image, public_key, task_id)

        kwargs = self._build_container_kwargs(
            labels=labels,
            cpuset_cpus=cpuset_cpus,
            cpuset_mems=cpuset_mems,
            mem_limit=mem_limit,
            gpu_ids=gpu_ids,
            mounts=mounts,
            environment=None,
            working_dir=working_dir,
            privileged=privileged,
            task_id=task_id,
        )
        kwargs["ports"] = {"22/tcp": ssh_port}
        kwargs["restart_policy"] = {"Name": "unless-stopped"}

        log.debug(f"Creating VPS container {container_name} with image {image}")
        return self.create_container(
            image,
            container_name,
            ["/bin/sh", "-c", setup_cmd],
            **kwargs,
        )

    def _build_container_kwargs(
        self,
        labels: dict[str, str],
        cpuset_cpus: str | None,
        cpuset_mems: str | None,
        mem_limit: str | None,
        gpu_ids: list[int] | None,
        mounts: list[Mount] | None,
        environment: dict[str, str] | None,
        working_dir: str,
        privileged: bool,
        task_id: int,
    ) -> dict:
        """Build common container creation kwargs."""
        kwargs: dict = {
            "labels": labels,
            "working_dir": working_dir,
        }

        if cpuset_cpus:
            kwargs["cpuset_cpus"] = cpuset_cpus
        if cpuset_mems:
            kwargs["cpuset_mems"] = cpuset_mems
        if mem_limit:
            kwargs["mem_limit"] = mem_limit
        if mounts:
            kwargs["mounts"] = mounts
        if environment:
            kwargs["environment"] = environment

        if privileged:
            kwargs["privileged"] = True
            log.warning(f"Task {task_id}: Running with --privileged flag")
        else:
            kwargs["cap_add"] = ["SYS_NICE"]

        if gpu_ids:
            kwargs["device_requests"] = [
                DeviceRequest(
                    device_ids=[str(gid) for gid in gpu_ids],
                    capabilities=[["gpu"]],
                )
            ]

        return kwargs

    def _build_ssh_setup_command(
        self,
        image: str,
        public_key: str | None,
        task_id: int,
    ) -> str:
        """Build SSH setup command based on detected package manager."""
        pkg_manager = self._detect_package_manager(image)
        install_cmd = self._get_ssh_install_command(pkg_manager)
        auth_config = self._get_ssh_auth_config(public_key, task_id)

        return (
            f"{install_cmd} && "
            "ssh-keygen -A && "
            f"{auth_config} && "
            "mkdir -p /run/sshd && "
            "chmod 0755 /run/sshd && "
            "/usr/sbin/sshd -D -e"
        )

    def _get_ssh_install_command(self, pkg_manager: str) -> str:
        """Get SSH server install command for package manager."""
        match pkg_manager:
            case "apk":
                return "apk update && apk add --no-cache openssh"
            case "apt" | "apt-get":
                return (
                    f"{pkg_manager} update && {pkg_manager} install -y openssh-server"
                )
            case "dnf":
                return "dnf install -y openssh-server"
            case "yum":
                return "yum install -y openssh-server"
            case "zypper":
                return "zypper refresh && zypper install -y openssh"
            case "pacman":
                return "pacman -Syu --noconfirm openssh"
            case _:
                return "echo 'SSH server should be pre-installed'"

    def _get_ssh_auth_config(self, public_key: str | None, task_id: int) -> str:
        """Get SSH authentication configuration."""
        if public_key:
            return (
                "echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config && "
                "echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config && "
                "mkdir -p /root/.ssh && "
                f"echo '{public_key}' > /root/.ssh/authorized_keys && "
                "chmod 700 /root/.ssh && "
                "chmod 600 /root/.ssh/authorized_keys"
            )
        return (
            "echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config && "
            "echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config && "
            f"echo 'root:{task_id}' | chpasswd"
        )

    def _detect_package_manager(self, image: str) -> str:
        """Detect package manager in an image."""
        managers = ["apk", "apt-get", "apt", "dnf", "yum", "zypper", "pacman"]

        for manager in managers:
            try:
                result = self.client.containers.run(
                    image,
                    ["which", manager],
                    remove=True,
                    detach=False,
                )
                if result:
                    log.debug(f"Detected package manager: {manager}")
                    return manager
            except (ContainerError, Exception):
                continue

        log.debug("Could not detect package manager, assuming SSH pre-installed")
        return "unknown"

    # =========================================================================
    # Container Lifecycle
    # =========================================================================

    def stop_container(self, name: str, timeout: int = 10) -> bool:
        """
        Stop a container.

        Args:
            name: Container name.
            timeout: Seconds to wait before killing.

        Returns:
            True if stopped successfully, False otherwise.
        """
        try:
            container = self.client.containers.get(name)
            container.stop(timeout=timeout)
            log.info(f"Container {name} stopped")
            return True
        except NotFound:
            log.warning(f"Container {name} not found")
            return False
        except APIError as e:
            log.error(f"Failed to stop container {name}: {e}")
            return False

    def start_container(self, name: str) -> bool:
        """
        Start a stopped container.

        Args:
            name: Container name.

        Returns:
            True if started successfully, False otherwise.
        """
        try:
            container = self.client.containers.get(name)
            container.start()
            log.info(f"Container {name} started")
            return True
        except NotFound:
            log.warning(f"Container {name} not found")
            return False
        except APIError as e:
            log.error(f"Failed to start container {name}: {e}")
            return False

    def remove_container(self, name: str, force: bool = True) -> bool:
        """
        Remove a container.

        Args:
            name: Container name.
            force: Force removal even if running.

        Returns:
            True if removed successfully, False otherwise.
        """
        try:
            container = self.client.containers.get(name)
            container.remove(force=force)
            log.info(f"Container {name} removed")
            return True
        except NotFound:
            log.debug(f"Container {name} already removed")
            return True
        except APIError as e:
            log.error(f"Failed to remove container {name}: {e}")
            return False

    def pause_container(self, name: str) -> bool:
        """
        Pause a container.

        Args:
            name: Container name.

        Returns:
            True if paused successfully, False otherwise.

        Raises:
            ContainerNotFoundError: If container doesn't exist.
        """
        try:
            container = self.client.containers.get(name)
            container.pause()
            log.info(f"Container {name} paused")
            return True
        except NotFound:
            raise ContainerNotFoundError(name)
        except APIError as e:
            log.error(f"Failed to pause container {name}: {e}")
            return False

    def unpause_container(self, name: str) -> bool:
        """
        Unpause a container.

        Args:
            name: Container name.

        Returns:
            True if unpaused successfully, False otherwise.

        Raises:
            ContainerNotFoundError: If container doesn't exist.
        """
        try:
            container = self.client.containers.get(name)
            container.unpause()
            log.info(f"Container {name} unpaused")
            return True
        except NotFound:
            raise ContainerNotFoundError(name)
        except APIError as e:
            log.error(f"Failed to unpause container {name}: {e}")
            return False

    def kill_container(self, name: str, signal: str = "SIGKILL") -> bool:
        """
        Kill a container with a signal.

        Args:
            name: Container name.
            signal: Signal to send (default: SIGKILL).

        Returns:
            True if killed successfully, False otherwise.
        """
        try:
            container = self.client.containers.get(name)
            container.kill(signal=signal)
            log.info(f"Container {name} killed with {signal}")
            return True
        except NotFound:
            log.warning(f"Container {name} not found")
            return False
        except APIError as e:
            log.error(f"Failed to kill container {name}: {e}")
            return False

    # =========================================================================
    # Container Queries
    # =========================================================================

    def get_container_port(self, name: str, container_port: int = 22) -> int | None:
        """
        Get host port mapped to a container port.

        Args:
            name: Container name.
            container_port: Container port to look up.

        Returns:
            Host port number, or None if not found.
        """
        try:
            container = self.client.containers.get(name)
            ports = container.attrs["NetworkSettings"]["Ports"]
            port_key = f"{container_port}/tcp"
            if port_key in ports and ports[port_key]:
                return int(ports[port_key][0]["HostPort"])
            return None
        except (NotFound, KeyError, IndexError, TypeError):
            return None

    def list_kohakuriver_containers(self, all: bool = False) -> list[Container]:
        """
        List all HakuRiver-managed containers.

        Args:
            all: Include stopped containers.

        Returns:
            List of Container objects.
        """
        return self.client.containers.list(
            all=all,
            filters={"label": f"{LABEL_MANAGED}=true"},
        )

    def list_containers(
        self,
        all: bool = False,
        filters: dict | None = None,
    ) -> list[Container]:
        """
        List containers with optional filters.

        Args:
            all: Include stopped containers.
            filters: Docker filters dict.

        Returns:
            List of Container objects.
        """
        return self.client.containers.list(all=all, filters=filters)

    def cleanup_stopped_containers(self) -> int:
        """
        Remove stopped HakuRiver containers.

        Returns:
            Number of containers removed.
        """
        removed = 0
        for container in self.list_kohakuriver_containers(all=True):
            if container.status in ("exited", "dead"):
                try:
                    container.remove()
                    removed += 1
                    log.info(f"Removed stopped container {container.name}")
                except APIError:
                    pass
        return removed
