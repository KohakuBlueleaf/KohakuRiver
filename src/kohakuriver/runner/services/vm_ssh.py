"""
VM SSH connection management.

Provides:
- Runner SSH keypair generation (for authenticating to VMs)
- SSH connection helper using asyncssh
- SSH exec helper for running commands in VMs
- TCP port proxy for SSH forwarding from host
"""

import asyncio
import os
from pathlib import Path

import asyncssh

from kohakuriver.utils.logger import get_logger

logger = get_logger(__name__)

# --- Runner SSH Keypair ---

_runner_key_path: str | None = None


def _get_key_dir() -> str:
    """Get directory for runner SSH keys."""
    home = os.environ.get("HOME", "/root")
    key_dir = os.path.join(home, ".kohakuriver")
    os.makedirs(key_dir, exist_ok=True)
    return key_dir


def get_runner_private_key_path() -> str:
    """Get path to runner's SSH private key, generating if needed."""
    global _runner_key_path
    if _runner_key_path and os.path.exists(_runner_key_path):
        return _runner_key_path

    key_dir = _get_key_dir()
    key_path = os.path.join(key_dir, "runner_ssh_key")

    if not os.path.exists(key_path):
        logger.info(f"Generating runner SSH keypair at {key_path}")
        key = asyncssh.generate_private_key("ssh-ed25519")
        key.write_private_key(key_path)
        key.write_public_key(f"{key_path}.pub")
        os.chmod(key_path, 0o600)
        logger.info("Runner SSH keypair generated")

    _runner_key_path = key_path
    return key_path


def get_runner_public_key() -> str:
    """Get runner's SSH public key content (for injecting into VMs)."""
    key_path = get_runner_private_key_path()
    pub_path = f"{key_path}.pub"
    return Path(pub_path).read_text().strip()


# --- SSH Connections ---


async def ssh_connect(
    vm_ip: str,
    username: str = "root",
    timeout: float = 10.0,
) -> asyncssh.SSHClientConnection:
    """
    Create SSH connection to a VM using runner's key.

    Args:
        vm_ip: VM IP address.
        username: SSH username (default: root).
        timeout: Connection timeout in seconds.

    Returns:
        asyncssh.SSHClientConnection
    """
    key_path = get_runner_private_key_path()
    conn = await asyncio.wait_for(
        asyncssh.connect(
            vm_ip,
            username=username,
            client_keys=[key_path],
            known_hosts=None,  # VMs are ephemeral, skip host key checking
        ),
        timeout=timeout,
    )
    return conn


async def ssh_exec(
    vm_ip: str,
    cmd: str | list[str],
    username: str = "root",
    timeout: float = 30.0,
) -> tuple[int, str, str]:
    """
    Execute a command in VM via SSH.

    Args:
        vm_ip: VM IP address.
        cmd: Command string or list.
        username: SSH username.
        timeout: Execution timeout.

    Returns:
        (exit_code, stdout, stderr)
    """
    if isinstance(cmd, list):
        # Shell-escape and join
        import shlex

        cmd = " ".join(shlex.quote(c) for c in cmd)

    try:
        conn = await ssh_connect(vm_ip, username, timeout=timeout)
        async with conn:
            result = await asyncio.wait_for(
                conn.run(cmd, check=False),
                timeout=timeout,
            )
            return (
                result.exit_status or 0,
                result.stdout or "",
                result.stderr or "",
            )
    except asyncio.TimeoutError:
        return -1, "", "SSH command timed out"
    except (asyncssh.Error, OSError) as e:
        return -1, "", f"SSH error: {e}"


# --- TCP Port Proxy (for host SSH proxy) ---

# Active proxies: task_id -> (server, task)
_ssh_proxies: dict[int, tuple[asyncio.AbstractServer, asyncio.Task | None]] = {}


async def start_ssh_proxy(task_id: int, ssh_port: int, vm_ip: str) -> bool:
    """
    Start a TCP proxy on ssh_port that forwards to vm_ip:22.

    This allows the host SSH proxy to connect to runner_ip:ssh_port
    and reach the VM's SSH server.

    Args:
        task_id: VM task ID.
        ssh_port: Port to listen on (allocated by host).
        vm_ip: VM IP address.

    Returns:
        True if started successfully.
    """
    if task_id in _ssh_proxies:
        logger.warning(f"SSH proxy for VM {task_id} already running")
        return True

    async def handle_connection(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ):
        """Forward TCP connection to VM SSH."""
        client_addr = client_writer.get_extra_info("peername")
        logger.debug(f"SSH proxy VM {task_id}: connection from {client_addr}")

        try:
            vm_reader, vm_writer = await asyncio.wait_for(
                asyncio.open_connection(vm_ip, 22),
                timeout=10.0,
            )
        except Exception as e:
            logger.warning(f"SSH proxy VM {task_id}: cannot connect to {vm_ip}:22: {e}")
            client_writer.close()
            return

        async def forward(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                pass
            finally:
                try:
                    writer.close()
                except Exception:
                    pass

        t1 = asyncio.create_task(forward(client_reader, vm_writer))
        t2 = asyncio.create_task(forward(vm_reader, client_writer))
        await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
        t1.cancel()
        t2.cancel()

    try:
        server = await asyncio.start_server(handle_connection, "0.0.0.0", ssh_port)
        _ssh_proxies[task_id] = (server, None)
        logger.info(
            f"SSH proxy for VM {task_id}: listening on 0.0.0.0:{ssh_port} "
            f"-> {vm_ip}:22"
        )
        return True
    except OSError as e:
        logger.error(
            f"Failed to start SSH proxy for VM {task_id} on port {ssh_port}: {e}"
        )
        return False


async def stop_ssh_proxy(task_id: int) -> None:
    """Stop SSH proxy for a VM."""
    proxy = _ssh_proxies.pop(task_id, None)
    if proxy:
        server, _ = proxy
        server.close()
        await server.wait_closed()
        logger.info(f"SSH proxy for VM {task_id} stopped")


# --- TCP Port Proxy (for generic port forwarding) ---


async def start_port_proxy(
    task_id: int, vm_ip: str, port: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """
    Open a direct TCP connection to vm_ip:port.

    Used for port forwarding to VMs (replacing tunnel-client mechanism).

    Returns:
        (reader, writer) tuple or None on failure.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(vm_ip, port),
            timeout=10.0,
        )
        return reader, writer
    except Exception as e:
        logger.warning(f"Cannot connect to VM {task_id} at {vm_ip}:{port}: {e}")
        return None
