"""
API client for CLI commands.

Provides functions to interact with the HakuRiver host API.
Returns structured data instead of printing.

This module is a backwards-compatibility shim that re-exports everything
from the ``kohakuriver.cli.api`` subpackage so that existing imports of
the form ``from kohakuriver.cli import client`` / ``client.X()`` continue
to work unchanged.
"""

# Re-export everything from the new api subpackage
from kohakuriver.cli.api._base import *  # noqa: F401,F403
from kohakuriver.cli.api.docker import *  # noqa: F401,F403
from kohakuriver.cli.api.nodes import *  # noqa: F401,F403
from kohakuriver.cli.api.tasks import *  # noqa: F401,F403
from kohakuriver.cli.api.vps import *  # noqa: F401,F403
