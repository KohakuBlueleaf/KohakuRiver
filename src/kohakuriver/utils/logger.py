"""
Logging Utilities for HakuRiver using Loguru.

This module provides a comprehensive logging system with:
    - Hierarchical log levels (ERROR > WARNING > INFO > DEBUG)
    - Colored console output for easy visual parsing
    - Module name prefixes for easy source identification
    - Beautiful traceback formatting
    - Uvicorn/standard library logging interception

Log Format:
    TIME | LEVEL | MODULE - message
    Example: 14:32:05 | INFO     | kohakuriver.host.app - Server starting...

Usage:
    from kohakuriver.utils.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Application started")
    logger.error("Failed to connect")
    logger.debug("Processing request")
"""

import logging
import sys
import traceback

from loguru import logger as _loguru_logger

from kohakuriver.models.enums import LogLevel

# =============================================================================
# Format Configuration
# =============================================================================

# Format with module name from extra['name'] (set via bind or patcher)
# Uses {extra[name]} to get the bound module name
LOG_FORMAT = (
    "<dim>{time:HH:mm:ss}</dim> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[name]}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# Simpler format without function/line info
LOG_FORMAT_SIMPLE = (
    "<dim>{time:HH:mm:ss}</dim> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[name]}</cyan> - "
    "<level>{message}</level>"
)


# =============================================================================
# Module Name Patcher
# =============================================================================


def _name_patcher(record: dict) -> None:
    """
    Patch log records to include module name.

    If 'name' is not already bound, uses the module from the call frame.
    This ensures module names are always available in the log format.
    """
    if "name" not in record["extra"]:
        # Use the module name from the call frame
        record["extra"]["name"] = record["name"]


# =============================================================================
# Standard Library Interception
# =============================================================================

# Third-party loggers pinned to a floor level regardless of app log level.
# pyroute2 is the critical one: it logs every netlink message (each interface
# a ~2 KB nested dict), so one get_links() at DEBUG floods the journal.
NOISY_LIBRARY_LEVELS: dict[str, int] = {
    "pyroute2": logging.WARNING,
    "docker": logging.WARNING,
    "urllib3": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "asyncssh": logging.INFO,
    "asyncio": logging.WARNING,
}


class InterceptHandler(logging.Handler):
    """
    Intercept standard library logging and redirect to loguru.

    This handler captures logs from uvicorn, httpx, and other libraries
    that use the standard logging module, routing them through loguru
    for consistent formatting.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record by forwarding it to loguru.

        Args:
            record: The log record from standard logging.
        """
        # Get corresponding loguru level
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where the log originated
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        # Use the logger name from the standard logging record
        _loguru_logger.bind(name=record.name).opt(
            depth=depth, exception=record.exc_info
        ).log(level, record.getMessage())


def intercept_standard_logging(silence_peewee: bool = True) -> None:
    """
    Configure standard library logging to be intercepted by loguru.

    This should be called before uvicorn starts to capture its logs.

    Args:
        silence_peewee: If True, suppress peewee DB logging (default: True).
    """
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Intercept specific loggers used by our dependencies
    intercepted_loggers = [
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "fastapi",
        "httpx",
        "httpcore",
        "websockets",
    ]

    for logger_name in intercepted_loggers:
        target_logger = logging.getLogger(logger_name)
        target_logger.handlers = [InterceptHandler()]
        target_logger.propagate = False

    # Silence peewee by default (too noisy with SQL queries)
    peewee_logger = logging.getLogger("peewee")
    if silence_peewee:
        peewee_logger.handlers = []
        peewee_logger.addHandler(logging.NullHandler())
        peewee_logger.propagate = False
    else:
        peewee_logger.handlers = [InterceptHandler()]
        peewee_logger.propagate = False

    for noisy_name, min_level in NOISY_LIBRARY_LEVELS.items():
        logging.getLogger(noisy_name).setLevel(min_level)


# =============================================================================
# Configuration Functions
# =============================================================================

# Track if logging has been configured
_configured = False


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    simple_format: bool = True,
    intercept_stdlib: bool = True,
) -> None:
    """
    Configure HakuRiver logging with loguru.

    This function should be called at application startup to set up
    consistent logging across all components including uvicorn.

    Args:
        level: Log verbosity level.
        simple_format: Use simpler format without function/line info.
        intercept_stdlib: Intercept standard library logging (uvicorn, etc.).

    Example:
        from kohakuriver.utils.logger import configure_logging
        from kohakuriver.models.enums import LogLevel

        configure_logging(LogLevel.DEBUG)
    """
    global _configured

    # Map HakuRiver levels to loguru levels
    level_map = {
        LogLevel.FULL: "TRACE",
        LogLevel.DEBUG: "DEBUG",
        LogLevel.INFO: "INFO",
        LogLevel.WARNING: "WARNING",
    }
    log_level = level_map.get(level, "INFO")

    # Remove default handler
    _loguru_logger.remove()

    # Add new handler with custom format and patcher
    fmt = LOG_FORMAT_SIMPLE if simple_format else LOG_FORMAT
    _loguru_logger.configure(patcher=_name_patcher)
    _loguru_logger.add(
        sys.stderr,
        format=fmt,
        level=log_level,
        colorize=True,
        backtrace=level in (LogLevel.FULL, LogLevel.DEBUG),
        diagnose=level == LogLevel.FULL,
    )

    # Intercept standard library logging
    if intercept_stdlib:
        intercept_standard_logging()

    _configured = True
    _loguru_logger.bind(name="kohakuriver.logger").debug(
        f"Logging configured: level={log_level}"
    )


def get_logger(name: str):
    """
    Get a logger instance bound to a specific module name.

    This provides a consistent interface similar to logging.getLogger()
    but returns a loguru logger with the name bound for log prefixes.

    Args:
        name: Logger name, typically __name__ of the calling module.

    Returns:
        Loguru logger instance with the name bound.

    Example:
        from kohakuriver.utils.logger import get_logger

        logger = get_logger(__name__)
        logger.info("Module initialized")
        # Output: 14:32:05 | INFO     | mymodule.submodule - Module initialized
    """
    return _loguru_logger.bind(name=name)


# =============================================================================
# Traceback Formatting
# =============================================================================


def format_traceback(exc: BaseException | None = None) -> str:
    """
    Format a traceback in a detailed, readable format.

    Note: With loguru, tracebacks are automatically formatted beautifully
    when using logger.exception() or logger.opt(exception=True).
    This function is kept for backward compatibility and manual formatting.

    Args:
        exc: Exception to format. If None, uses current exception.

    Returns:
        Formatted traceback string.
    """
    if exc is None:
        _, exc_value, exc_tb = sys.exc_info()
        if exc_value is None:
            return ""
        exc = exc_value
    else:
        exc_tb = exc.__traceback__

    lines = ["=" * 60]
    tb_list = traceback.extract_tb(exc_tb)

    for frame in tb_list:
        lines.append(f"file: {frame.filename}")
        lines.append(f"line: {frame.lineno}")
        lines.append(f"method: {frame.name}")
        if frame.line:
            lines.append(f"code: {frame.line.strip()}")
        lines.append("-" * 40)

    lines.append(f"error: {type(exc).__name__}: {exc}")
    lines.append("=" * 60)

    return "\n".join(lines)


def format_traceback_compact(exc: BaseException | None = None) -> str:
    """
    Format a traceback in a compact single-line format.

    Args:
        exc: Exception to format. If None, uses current exception.

    Returns:
        Compact traceback string.
    """
    if exc is None:
        _, exc_value, exc_tb = sys.exc_info()
        if exc_value is None:
            return ""
        exc = exc_value
    else:
        exc_tb = exc.__traceback__

    tb_list = traceback.extract_tb(exc_tb)
    if not tb_list:
        return f"{type(exc).__name__}: {exc}"

    last_frame = tb_list[-1]
    return (
        f"{type(exc).__name__}: {exc} "
        f"(at {last_frame.filename}:{last_frame.lineno} in {last_frame.name})"
    )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "get_logger",
    "configure_logging",
    "intercept_standard_logging",
    "format_traceback",
    "format_traceback_compact",
    "InterceptHandler",
]
