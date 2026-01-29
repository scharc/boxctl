"""Unified logging and debug infrastructure for boxctl.

This module provides:
1. Centralized logging configuration
2. Debug mode via BOXCTL_DEBUG env var or programmatic flag
3. Log levels via BOXCTL_LOG_LEVEL env var
4. Dual output: Rich console for CLI, file logging for debugging
5. Daemon mode: stderr-only for background processes

Usage:
    from boxctl.utils.logging import get_logger, configure_logging

    # In CLI entry point:
    configure_logging(debug=args.debug)

    # In any module:
    logger = get_logger(__name__)
    logger.info("Starting operation")
    logger.debug("Detailed debug info")
    logger.error("Something failed", exc=exception)

Environment Variables:
    BOXCTL_DEBUG=1        Enable debug mode (verbose output)
    BOXCTL_LOG_LEVEL=DEBUG  Set log level (DEBUG, INFO, WARNING, ERROR)
    BOXCTL_LOG_FILE=/path  Override log file location
"""

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from rich.console import Console

# Global state
_configured = False
_debug_mode = False
_daemon_mode = False
_log_file: Optional[Path] = None

# Shared Rich console instance
console = Console()

# Custom log level for success messages
SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")


def _get_log_dir() -> Path:
    """Get the log directory, creating it if needed."""
    # Check for explicit log file path
    env_log_file = os.environ.get("BOXCTL_LOG_FILE")
    if env_log_file:
        return Path(env_log_file).parent

    # Use .boxctl/logs in workspace (boxctl requires .boxctl to exist)
    workspace = Path(os.environ.get("BOXCTL_PROJECT_DIR", Path.cwd()))
    log_dir = workspace / ".boxctl" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _get_log_file() -> Path:
    """Get the log file path."""
    global _log_file
    if _log_file:
        return _log_file

    env_log_file = os.environ.get("BOXCTL_LOG_FILE")
    if env_log_file:
        _log_file = Path(env_log_file)
    else:
        _log_file = _get_log_dir() / "boxctl.log"

    return _log_file


def is_debug_mode() -> bool:
    """Check if debug mode is enabled."""
    return _debug_mode or os.environ.get("BOXCTL_DEBUG", "").lower() in ("1", "true", "yes")


def configure_logging(
    debug: bool = False,
    daemon: bool = False,
    log_level: Optional[str] = None,
    log_file: Optional[Path] = None,
) -> None:
    """Configure the logging system.

    Should be called once at application startup (CLI entry point or daemon start).

    Args:
        debug: Enable debug mode (verbose output, debug to console)
        daemon: Daemon mode (stderr only, no Rich formatting)
        log_level: Override log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Override log file path
    """
    global _configured, _debug_mode, _daemon_mode, _log_file

    if _configured:
        return

    _debug_mode = debug or is_debug_mode()
    _daemon_mode = daemon

    if log_file:
        _log_file = log_file

    # Determine log level
    if log_level:
        level_name = log_level.upper()
    else:
        level_name = os.environ.get("BOXCTL_LOG_LEVEL", "DEBUG" if _debug_mode else "INFO").upper()

    level = getattr(logging, level_name, logging.INFO)

    # Get root boxctl logger
    root_logger = logging.getLogger("boxctl")
    root_logger.setLevel(level)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # File handler with rotation (always enabled, captures all logs)
    try:
        file_handler = RotatingFileHandler(
            _get_log_file(),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # Capture everything to file
        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError):
        # Can't write log file, continue without it
        pass

    # Stderr handler for daemons (simple format, no colors)
    if _daemon_mode:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(level)
        stderr_formatter = logging.Formatter("%(name)s: %(levelname)s: %(message)s")
        stderr_handler.setFormatter(stderr_formatter)
        root_logger.addHandler(stderr_handler)

    _configured = True

    # Log startup info
    root_logger.debug(
        f"Logging configured: level={level_name}, debug={_debug_mode}, daemon={_daemon_mode}"
    )
    if _log_file:
        root_logger.debug(f"Log file: {_log_file}")


class boxctlLogger:
    """Unified logging with Rich console output.

    Provides:
    - Standard log levels (debug, info, warning, error)
    - Success level for green checkmark messages
    - Automatic Rich formatting for CLI output
    - File logging for debugging
    - Debug output to console when debug mode enabled
    """

    def __init__(self, name: str):
        """Create a logger for the given module name.

        Args:
            name: Module name (typically __name__)
        """
        self.name = name
        self.logger = logging.getLogger(name)
        self.console = console

    def debug(self, message: str, console_output: bool = False) -> None:
        """Log debug message.

        By default, debug only goes to log file. Set console_output=True
        or enable BOXCTL_DEBUG to see in console.

        Args:
            message: Debug message
            console_output: Force output to console
        """
        self.logger.debug(message)
        if console_output or is_debug_mode():
            if _daemon_mode:
                print(f"DEBUG: {message}", file=sys.stderr)
            else:
                self.console.print(f"[dim][DEBUG] {message}[/dim]")

    def info(self, message: str, console_output: bool = True) -> None:
        """Log info message.

        Args:
            message: Info message
            console_output: Output to console (default True for CLI)
        """
        self.logger.info(message)
        if console_output and not _daemon_mode:
            self.console.print(f"[blue]{message}[/blue]")
        elif console_output and _daemon_mode:
            print(f"INFO: {message}", file=sys.stderr)

    def success(self, message: str, console_output: bool = True) -> None:
        """Log success message (green output).

        Args:
            message: Success message
            console_output: Output to console
        """
        self.logger.log(SUCCESS_LEVEL, message)
        if console_output and not _daemon_mode:
            self.console.print(f"[green]✓ {message}[/green]")
        elif console_output and _daemon_mode:
            print(f"SUCCESS: {message}", file=sys.stderr)

    def warning(self, message: str, console_output: bool = True) -> None:
        """Log warning message (yellow output).

        Args:
            message: Warning message
            console_output: Output to console
        """
        self.logger.warning(message)
        if console_output and not _daemon_mode:
            self.console.print(f"[yellow]⚠ {message}[/yellow]")
        elif console_output and _daemon_mode:
            print(f"WARNING: {message}", file=sys.stderr)

    def error(
        self,
        message: str,
        exc: Optional[Exception] = None,
        console_output: bool = True,
    ) -> None:
        """Log error message (red output).

        Args:
            message: Error message
            exc: Optional exception to include in log
            console_output: Output to console
        """
        if exc:
            self.logger.error(f"{message}: {exc}", exc_info=exc)
            error_msg = f"{message}: {exc}"
        else:
            self.logger.error(message)
            error_msg = message

        if console_output and not _daemon_mode:
            self.console.print(f"[red]✗ {error_msg}[/red]")
        elif console_output and _daemon_mode:
            print(f"ERROR: {error_msg}", file=sys.stderr)

    def exception(self, message: str, console_output: bool = True) -> None:
        """Log exception with full traceback.

        Call this from within an except block.

        Args:
            message: Error message
            console_output: Output to console
        """
        self.logger.exception(message)
        if console_output and not _daemon_mode:
            self.console.print(f"[red]✗ {message}[/red]")
            if is_debug_mode():
                self.console.print_exception()
        elif console_output and _daemon_mode:
            print(f"ERROR: {message}", file=sys.stderr)

    def print(self, message: str, style: Optional[str] = None) -> None:
        """Print to console without logging.

        Use for user-facing output that shouldn't be in logs.

        Args:
            message: Message to print
            style: Optional Rich style (e.g., "bold", "red", "dim")
        """
        if _daemon_mode:
            print(message, file=sys.stderr)
        elif style:
            self.console.print(f"[{style}]{message}[/{style}]")
        else:
            self.console.print(message)


def get_logger(name: str) -> boxctlLogger:
    """Get or create a logger for a module.

    Args:
        name: Module name (typically __name__)

    Returns:
        boxctlLogger instance

    Example:
        logger = get_logger(__name__)
        logger.info("Operation started")
    """
    # Ensure logging is configured with defaults if not already done
    if not _configured:
        configure_logging()

    # Ensure name is under boxctl namespace
    if not name.startswith("boxctl"):
        name = f"boxctl.{name}"

    return boxctlLogger(name)


# Convenience function for daemon processes
def get_daemon_logger(name: str) -> boxctlLogger:
    """Get a logger configured for daemon mode.

    Args:
        name: Daemon name

    Returns:
        boxctlLogger configured for daemon output
    """
    configure_logging(daemon=True)
    return get_logger(name)


# Debug utilities
def log_startup_info() -> None:
    """Log startup diagnostic information (call from main entry points)."""
    logger = get_logger("boxctl.startup")
    logger.debug(f"Python: {sys.version}")
    logger.debug(f"Platform: {sys.platform}")
    logger.debug(f"CWD: {os.getcwd()}")
    logger.debug(f"Debug mode: {is_debug_mode()}")
    logger.debug(f"Log file: {_get_log_file()}")

    # Log relevant environment variables
    for var in ["BOXCTL_DEBUG", "BOXCTL_LOG_LEVEL", "BOXCTL_PROJECT_DIR"]:
        value = os.environ.get(var)
        if value:
            logger.debug(f"ENV {var}={value}")
