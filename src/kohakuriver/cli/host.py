"""
CLI entry point for the KohakuRiver Host server.

Usage:
    kohakuriver.host [--config PATH]

If no --config is specified, automatically loads ~/.kohakuriver/host_config.py if it exists.
"""

import os
from typing import Annotated

import typer

from kohakuriver.utils.logger import get_logger

app = typer.Typer(help="KohakuRiver Host server")
logger = get_logger(__name__)

DEFAULT_HOST_CONFIG = os.path.expanduser("~/.kohakuriver/host_config.py")


def load_config(config_path: str) -> bool:
    """Load configuration from a KohakuEngine config file.

    Returns True if config was loaded successfully, False otherwise.
    """
    try:
        from kohakuengine import Config as KohakuConfig

        kohaku_config = KohakuConfig.from_file(config_path)

        # Apply globals to our config instance
        from kohakuriver.host.config import config as host_config

        for key, value in kohaku_config.globals_dict.items():
            if hasattr(host_config, key):
                setattr(host_config, key, value)

        return True

    except ImportError:
        print("WARNING: KohakuEngine not found, config file ignored.")
        return False
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return False


@app.command()
def run(
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to a Python configuration file (KohakuEngine format).",
        ),
    ] = None,
):
    """Run the KohakuRiver Host server."""
    # Determine which config to load
    config_path = config

    if config_path:
        # Explicitly specified config
        print(f"Loading configuration from: {config_path}")
        if not os.path.exists(config_path):
            print(f"ERROR: Config file not found: {config_path}")
            raise typer.Exit(1)
        if not load_config(config_path):
            raise typer.Exit(1)
    elif os.path.exists(DEFAULT_HOST_CONFIG):
        # Auto-load default config if exists
        print(f"Loading default configuration from: {DEFAULT_HOST_CONFIG}")
        if not load_config(DEFAULT_HOST_CONFIG):
            print("WARNING: Failed to load default config, using built-in defaults.")
    else:
        print("No config file specified and no default config found.")
        print(
            f"Using built-in defaults. Run 'kohakuriver init config --host' to generate config."
        )

    # Pre-flight: verify native extensions load on this CPU
    from kohakuriver.utils.preflight import check_native_extensions

    try:
        check_native_extensions()
    except RuntimeError as e:
        print(f"ERROR: {e}")
        raise typer.Exit(1)

    # Run the server
    try:
        print("Starting KohakuRiver Host server...")
        from kohakuriver.host.app import run as run_server

        run_server()

    except Exception as e:
        logger.critical(f"FATAL: Host server failed to start: {e}", exc_info=True)
        raise typer.Exit(1)


def main():
    """Entry point for kohakuriver.host."""
    app()


if __name__ == "__main__":
    main()
