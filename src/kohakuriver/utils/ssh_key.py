"""
SSH key management utilities for HakuRiver.

This module provides functions for reading, generating, and managing
SSH keys used for VPS authentication.
"""

import os
import subprocess

from kohakuriver.utils.logger import get_logger

log = get_logger(__name__)


# =============================================================================
# Public Key Reading
# =============================================================================


def read_public_key_file(file_path: str) -> str:
    """
    Read an SSH public key from a file.

    Args:
        file_path: Path to the public key file (supports ~ expansion).

    Returns:
        The public key string, stripped of whitespace.

    Raises:
        FileNotFoundError: If the key file does not exist.
        IOError: If the file cannot be read.
        ValueError: If the file is empty.
    """
    path = os.path.expanduser(file_path)

    try:
        with open(path) as f:
            key = f.read().strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"Public key file not found: '{file_path}'") from None
    except IOError as e:
        raise IOError(f"Error reading public key file '{file_path}': {e}") from e

    if not key:
        raise ValueError(f"Public key file '{file_path}' is empty.")

    if not key.startswith("ssh-"):
        log.warning(
            f"Public key in '{file_path}' does not start with 'ssh-'. "
            "Is this a valid public key?"
        )

    return key


# =============================================================================
# Key Generation
# =============================================================================


def generate_ssh_keypair(
    private_key_path: str,
    key_type: str = "ed25519",
    comment: str = "",
) -> tuple[str, str]:
    """
    Generate an SSH keypair using ssh-keygen.

    Creates a new SSH key pair at the specified location. If keys already
    exist at that path, they will be replaced.

    Args:
        private_key_path: Path to save the private key (public key will be
                          saved with .pub extension).
        key_type: Key type to generate ('ed25519' or 'rsa').
        comment: Optional comment to embed in the key.

    Returns:
        Tuple of (private_key_path, public_key_string).

    Raises:
        RuntimeError: If key generation fails or ssh-keygen is not available.
    """
    private_key_path = os.path.expanduser(private_key_path)
    public_key_path = f"{private_key_path}.pub"

    _ensure_parent_directory(private_key_path)
    _remove_existing_keys(private_key_path, public_key_path)
    _run_ssh_keygen(private_key_path, key_type, comment)

    try:
        public_key = read_public_key_file(public_key_path)
    except Exception as e:
        raise RuntimeError(f"Failed to read generated public key: {e}") from e

    _set_key_permissions(private_key_path, public_key_path)

    log.info(f"Generated SSH keypair: {private_key_path}")

    return private_key_path, public_key


def _ensure_parent_directory(path: str) -> None:
    """Ensure the parent directory of a path exists."""
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)


def _remove_existing_keys(private_path: str, public_path: str) -> None:
    """Remove existing key files if they exist."""
    for path in [private_path, public_path]:
        if os.path.exists(path):
            os.remove(path)


def _run_ssh_keygen(private_key_path: str, key_type: str, comment: str) -> None:
    """Run ssh-keygen to generate a new keypair."""
    cmd = [
        "ssh-keygen",
        "-t",
        key_type,
        "-f",
        private_key_path,
        "-N",
        "",  # Empty passphrase
        "-q",  # Quiet mode
    ]

    if comment:
        cmd.extend(["-C", comment])

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to generate SSH key: {e.stderr}") from e
    except FileNotFoundError:
        raise RuntimeError("ssh-keygen not found. Please install OpenSSH.") from None


def _set_key_permissions(private_path: str, public_path: str) -> None:
    """Set proper file permissions for SSH keys."""
    os.chmod(private_path, 0o600)  # Owner read/write only
    os.chmod(public_path, 0o644)  # Owner read/write, others read


# =============================================================================
# Path Utilities
# =============================================================================


def save_generated_ssh_keys(
    result: dict,
    key_out_file: str | None = None,
    console=None,
) -> None:
    """
    Save generated SSH keys from a VPS creation result to disk.

    If the result dict contains an ``ssh_private_key`` field, the private key
    is written to *key_out_file* (or the default path derived from the task ID)
    with mode 0600.  When a matching ``ssh_public_key`` is present the public
    key is written alongside with a ``.pub`` suffix and mode 0644.

    Args:
        result: VPS creation response dict.  Must contain ``task_id``.
            Optionally contains ``ssh_private_key`` and ``ssh_public_key``.
        key_out_file: Explicit output path for the private key.  When *None*
            the default ``~/.ssh/id-kohakuriver-<task_id>`` path is used.
        console: Optional Rich console for printing status messages.
    """
    if not result.get("ssh_private_key"):
        return

    task_id = result["task_id"]
    out_path = key_out_file or get_default_key_output_path(task_id)
    out_path = os.path.expanduser(out_path)

    # Ensure directory exists
    ssh_dir = os.path.dirname(out_path)
    if ssh_dir:
        os.makedirs(ssh_dir, exist_ok=True)

    # Write private key
    with open(out_path, "w") as f:
        f.write(result["ssh_private_key"])
    os.chmod(out_path, 0o600)

    # Write public key
    if result.get("ssh_public_key"):
        pub_path = f"{out_path}.pub"
        with open(pub_path, "w") as f:
            f.write(result["ssh_public_key"])
        os.chmod(pub_path, 0o644)

    if console is not None:
        console.print(f"\n[green]SSH private key saved to:[/green] {out_path}")
        console.print(f"[green]SSH public key saved to:[/green] {out_path}.pub")

    log.info(f"Saved generated SSH keys to: {out_path}")


def get_default_key_output_path(task_id: int | str) -> str:
    """
    Get the default path for a generated SSH key.

    Keys are stored in the user's .ssh directory with a kohakuriver prefix.

    Args:
        task_id: Task ID to include in the key filename.

    Returns:
        Path like ~/.ssh/id-kohakuriver-<task_id>

    Example:
        >>> get_default_key_output_path(12345)
        '/home/user/.ssh/id-kohakuriver-12345'
    """
    ssh_dir = os.path.expanduser("~/.ssh")
    return os.path.join(ssh_dir, f"id-kohakuriver-{task_id}")
