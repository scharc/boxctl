# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Utility functions for CLI helpers."""

import functools
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable, NamedTuple, Optional

from rich.console import Console
from rich.panel import Panel

if TYPE_CHECKING:
    from boxctl.container import ContainerManager

_console = Console()


# Custom exception classes for clean error handling
class ContainerError(Exception):
    """Raised when container operations fail.

    This exception bubbles up to handle_errors which formats it nicely.
    """

    def __init__(self, message: str, hint: str = None):
        super().__init__(message)
        self.hint = hint


class NotInitializedError(Exception):
    """Raised when a command is run in an uninitialized directory.

    This exception is caught by handle_errors and shown as a formatted panel.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        super().__init__(f"Directory not initialized: {project_dir}")


class ProjectContext(NamedTuple):
    """Container for common project context values."""

    manager: "ContainerManager"
    project_dir: Path
    boxctl_dir: Path
    project_name: str
    container_name: str


def _get_project_context(
    manager: Optional["ContainerManager"] = None,
    project: Optional[str] = None,
) -> ProjectContext:
    """Get common project context values including ContainerManager.

    This reduces boilerplate for the common pattern:
        manager = ContainerManager()
        project_dir = resolve_project_dir()
        boxctl_dir = get_boxctl_dir(project_dir)
        project_name = manager.get_project_name(project_dir)
        container_name = resolve_container_name(project_dir)

    Args:
        manager: ContainerManager instance. Created if not provided.
        project: Optional project name override.

    Returns:
        ProjectContext with manager, project_dir, boxctl_dir, project_name, container_name
    """
    from boxctl.container import ContainerManager
    from boxctl.utils.project import resolve_project_dir, get_boxctl_dir
    from boxctl import container_naming

    if manager is None:
        manager = ContainerManager()

    project_dir = resolve_project_dir()
    boxctl_dir = get_boxctl_dir(project_dir)

    if project:
        # Explicit project name override - use simple name generation
        project_name = container_naming.sanitize_name(project)
        container_name = f"{container_naming.CONTAINER_PREFIX}{project_name}"
    else:
        # Default: use collision-aware resolution based on project directory
        project_name = manager.get_project_name(project_dir)
        container_name = container_naming.resolve_container_name(project_dir)

    return ProjectContext(
        manager=manager,
        project_dir=project_dir,
        boxctl_dir=boxctl_dir,
        project_name=project_name,
        container_name=container_name,
    )


def _require_container_running(manager: "ContainerManager", container_name: str) -> None:
    """Require container to be running, raise ClickException if not.

    Args:
        manager: ContainerManager instance
        container_name: Name of container to check

    Raises:
        click.ClickException: If container is not running
    """
    import click

    if not manager.is_running(container_name):
        raise click.ClickException(
            f"Container {container_name} is not running. Start it with: boxctl start"
        )


def _require_boxctl_dir(boxctl_dir: Path, project_dir: Path) -> None:
    """Require .boxctl directory to exist, raise ClickException if not.

    Args:
        boxctl_dir: Path to .boxctl directory
        project_dir: Path to project directory (for error message)

    Raises:
        click.ClickException: If .boxctl directory doesn't exist
    """
    import click

    if not boxctl_dir.exists():
        raise click.ClickException(f".boxctl/ not found in {project_dir}. Run: boxctl init")


def show_error_panel(title: str, message: str, hint: str = None) -> None:
    """Display a formatted error panel.

    Args:
        title: Panel title (shown in red)
        message: Main error message
        hint: Optional hint text (shown with blue "Hint:" prefix)
    """
    content = message
    if hint:
        content += f"\n\n[blue]Hint:[/blue] {hint}"
    _console.print(Panel(content, title=f"[red]{title}[/red]", border_style="red"))


def require_initialized(project_dir: Path = None) -> Path:
    """Check if project is initialized, show nice error if not.

    Shows the current directory and suggests running abox init.

    Args:
        project_dir: Project directory to check. If None, resolves from cwd.

    Returns:
        Path to the project directory if initialized.

    Raises:
        NotInitializedError: If .boxctl/ directory doesn't exist.
    """
    if project_dir is None:
        from boxctl.utils.project import resolve_project_dir

        project_dir = resolve_project_dir()

    boxctl_dir = project_dir / ".boxctl"
    if not boxctl_dir.exists():
        raise NotInitializedError(project_dir)

    return project_dir


def handle_errors(func: Callable) -> Callable:
    """Decorator that wraps CLI commands with standard error handling.

    Catches exceptions, prints error with nice formatting, and exits with code 1.
    Special handling for:
    - NotInitializedError: Shows "Not Initialized" panel with directory and init hint
    - ContainerError: Shows "Container Error" panel with hint if provided
    - ClickException: Shows panel with error message
    - Other exceptions: Shows generic error panel

    Usage:
        @command.command()
        @handle_errors
        def my_command():
            # code that might raise exceptions
            ...
    """
    import click

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SystemExit:
            raise  # Let sys.exit() pass through
        except NotInitializedError as exc:
            content = (
                f"[bold]Directory:[/bold] {exc.project_dir}\n\n"
                "This directory is not set up for boxctl.\n\n"
                "[blue]To get started, run:[/blue]\n"
                "  abox init"
            )
            _console.print(Panel(content, title="[red]Not Initialized[/red]", border_style="red"))
            sys.exit(1)
        except ContainerError as exc:
            content = str(exc)
            if exc.hint:
                content += f"\n\n[blue]Try:[/blue]\n  {exc.hint}"
            _console.print(Panel(content, title="[red]Container Error[/red]", border_style="red"))
            sys.exit(1)
        except click.ClickException as exc:
            # Let Click handle its own exceptions (they already have formatting)
            raise
        except Exception as exc:
            # Generic error panel for unexpected exceptions
            show_error_panel("Error", str(exc))
            sys.exit(1)

    return wrapper


def _sanitize_mount_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in name).strip("-")


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dictionary.

    Handles:
    - KEY=value format
    - Quoted values (single and double quotes)
    - Comments (lines starting with #)
    - Empty lines
    - Inline comments after values

    Args:
        env_path: Path to .env file

    Returns:
        Dictionary of environment variables
    """
    env_vars: dict[str, str] = {}

    if not env_path.exists():
        return env_vars

    try:
        content = env_path.read_text()
    except OSError:
        return env_vars

    for line in content.splitlines():
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Parse KEY=value
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()

        if not key:
            continue

        value = value.strip()

        # Remove surrounding quotes if present
        if len(value) >= 2:
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]

        # Handle inline comments (only for unquoted values)
        if " #" in value and not (value.startswith('"') or value.startswith("'")):
            value = value.split(" #")[0].strip()

        env_vars[key] = value

    return env_vars


def safe_rmtree(path: Path) -> bool:
    """Safely remove a directory tree, handling symlinks securely.

    If path is a symlink, only the symlink is removed (not the target).
    If path is a directory, it's removed recursively.

    Args:
        path: Path to remove

    Returns:
        True if something was removed, False if path didn't exist
    """
    if path.is_symlink():
        path.unlink()
        return True
    elif path.exists():
        shutil.rmtree(path)
        return True
    return False


def _merge_directory(src: Path, dst: Path) -> None:
    """Recursively merge source directory into destination.

    Copies all files and subdirectories from src to dst.
    Existing files in dst are overwritten, but files only in dst are preserved.
    Skips special directories like .git, .boxctl, __pycache__, etc.

    Args:
        src: Source directory
        dst: Destination directory
    """
    # Directories to skip when syncing MCPs
    skip_dirs = {
        ".git",
        ".boxctl",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".eggs",
        "*.egg-info",
    }

    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        # Skip special directories
        if item.name in skip_dirs or item.name.endswith(".egg-info"):
            continue

        src_item = item
        dst_item = dst / item.name

        if src_item.is_dir():
            # Recursively merge subdirectories
            _merge_directory(src_item, dst_item)
        elif src_item.is_file():
            # Copy file, overwriting if exists (skip symlinks that point to missing files)
            try:
                shutil.copy2(src_item, dst_item)
            except FileNotFoundError:
                # Symlink target doesn't exist, skip
                pass


def _sync_mcp_dir(
    source_dir: Path,
    boxctl_dir: Path,
    source_label: str,
    quiet: bool = False,
    installed_mcps: set | None = None,
) -> None:
    """Sync MCP servers from a source directory to project.

    Args:
        source_dir: Source directory containing MCP subdirectories
        boxctl_dir: Project's .boxctl directory
        source_label: Label for output messages ("library" or "custom")
        quiet: Suppress output messages
        installed_mcps: Set of installed MCP names (for command syncing)
    """
    import shutil
    from boxctl.cli.helpers.command_ops import _sync_mcp_commands

    if not source_dir.exists():
        return

    # Get project_dir for command syncing (parent of .boxctl)
    project_dir = boxctl_dir.parent

    # Custom MCPs override library MCPs for ab- symlinks
    is_custom = source_label == "custom"

    # Sort for deterministic processing order
    for mcp_path in sorted(source_dir.iterdir(), key=lambda p: p.name):
        if mcp_path.is_dir():
            target_path = boxctl_dir / "mcp" / mcp_path.name
            existed = target_path.exists()

            # Copy entire directory tree, preserving user-added files
            # Use copytree with dirs_exist_ok to merge with existing
            if existed:
                # Merge: copy new/updated files without deleting user files
                _merge_directory(mcp_path, target_path)
            else:
                # Fresh copy - use same skip patterns as _merge_directory
                skip_dirs = {
                    ".git",
                    ".boxctl",
                    "__pycache__",
                    ".pytest_cache",
                    "node_modules",
                    ".venv",
                    "venv",
                    ".tox",
                    ".mypy_cache",
                    ".ruff_cache",
                    ".eggs",
                }

                def ignore_patterns(directory, files):
                    """Ignore runtime/cache directories and egg-info."""
                    ignored = set()
                    for f in files:
                        if f in skip_dirs or f.endswith(".egg-info"):
                            ignored.add(f)
                    return ignored

                shutil.copytree(mcp_path, target_path, dirs_exist_ok=True, ignore=ignore_patterns)

            # Print update message first
            if not quiet:
                if existed:
                    _console.print(
                        f"  [yellow]Updated MCP ({source_label}): {mcp_path.name}[/yellow]"
                    )
                else:
                    _console.print(f"  [green]Copied MCP ({source_label}): {mcp_path.name}[/green]")

            # Sync slash commands if this MCP is installed
            # Always call sync even if commands/ doesn't exist - this ensures stale
            # commands are removed when a custom MCP overrides a library MCP
            if installed_mcps is not None and mcp_path.name in installed_mcps:
                synced_cmds = _sync_mcp_commands(
                    mcp_path, project_dir, mcp_path.name, is_custom=is_custom
                )
                if synced_cmds and not quiet:
                    _console.print(f"    [dim]Synced commands: {', '.join(synced_cmds)}[/dim]")


def _sync_library_mcps(boxctl_dir: Path, quiet: bool = False) -> None:
    """Sync MCP servers from library and custom directories to project.

    This updates the project's .boxctl/mcp/ directory with the latest
    versions from the boxctl library and user's custom MCPs.
    Custom MCPs override library MCPs with the same name.
    User-added files (like .env) in the project are preserved.
    Also syncs slash commands for installed MCPs.
    """
    from boxctl.library import LibraryManager
    from boxctl.cli.helpers.config_ops import _load_mcp_meta

    lib_manager = LibraryManager()

    # Load installed MCPs from meta to know which ones need command syncing
    meta = _load_mcp_meta(boxctl_dir)
    installed_mcps = set(meta.get("servers", {}).keys())

    # First sync library MCPs
    _sync_mcp_dir(lib_manager.mcp_dir, boxctl_dir, "library", quiet, installed_mcps)

    # Then sync custom MCPs (override library if same name)
    _sync_mcp_dir(lib_manager.user_mcp_dir, boxctl_dir, "custom", quiet, installed_mcps)


def _sync_library_skills(boxctl_dir: Path, quiet: bool = False) -> None:
    """Sync skill commands from library and custom directories to project.

    This syncs slash commands for installed skills, similar to how
    _sync_library_mcps syncs MCP commands.
    """
    from boxctl.library import LibraryManager
    from boxctl.cli.helpers.command_ops import _sync_skill_commands

    lib_manager = LibraryManager()
    project_dir = boxctl_dir.parent

    # Get installed skills from unified skills directory
    installed_skills = set()
    skills_dir = boxctl_dir / "skills"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                installed_skills.add(skill_dir.name)

    if not installed_skills:
        return

    # Sync library skills first
    for skill_name in sorted(installed_skills):
        skill_source = lib_manager.skills_dir / skill_name
        is_custom = False

        # Check if custom skill exists (takes precedence)
        custom_source = lib_manager.user_skills_dir / skill_name
        if custom_source.exists():
            skill_source = custom_source
            is_custom = True

        if skill_source.exists():
            # Always call sync even if commands/ doesn't exist - this ensures stale
            # commands are removed when a custom skill overrides a library skill
            synced_cmds = _sync_skill_commands(
                skill_source, project_dir, skill_name, is_custom=is_custom
            )
            if synced_cmds and not quiet:
                source_label = "custom" if is_custom else "library"
                _console.print(
                    f"  [dim]Synced skill commands ({source_label}): {skill_name} -> {', '.join(synced_cmds)}[/dim]"
                )


def _rebuild_container(
    manager: "ContainerManager",
    project_name: str,
    project_dir: Path,
    container_name: str,
    quiet: bool = False,
) -> None:
    """Rebuild container by removing existing and creating fresh one.

    This is the single rebuild path for all container recreation. It:
    1. Checks for missing devices (interactive prompt)
    2. Removes existing container (if any)
    3. Syncs MCP servers from library
    4. Creates fresh container

    Args:
        manager: ContainerManager instance
        project_name: Project name for container
        project_dir: Path to project directory
        container_name: Name of container to rebuild
        quiet: If True, suppress output messages
    """
    # Check for missing devices before rebuilding
    if not quiet:
        from boxctl.cli.helpers.tmux_ops import _warn_if_devices_missing

        _warn_if_devices_missing(project_dir)

    if manager.container_exists(container_name):
        if not quiet:
            _console.print(f"[yellow]Removing container {container_name}...[/yellow]")
        manager.remove_container(container_name, force=True)

    # Sync MCP servers and skill commands from library
    boxctl_dir = project_dir / ".boxctl"
    if boxctl_dir.exists():
        if not quiet:
            _console.print("[blue]Syncing from library...[/blue]")
        _sync_library_mcps(boxctl_dir, quiet=True)
        _sync_library_skills(boxctl_dir, quiet=True)

    if not quiet:
        _console.print("[green]Creating container...[/green]")
    container = manager.create_container(project_name=project_name, project_dir=project_dir)

    # Wait for container to be ready (shows live status)
    # 180s matches Docker HEALTHCHECK start-period for heavy installs
    if not quiet and container:
        if not wait_for_container_ready(manager, container.name, timeout_s=180.0):
            _console.print("[yellow]Warning: Container may still be initializing[/yellow]")
            _console.print(f"  Check logs: docker logs {container.name}")

    # Update boxctl version in config
    from boxctl.config import ProjectConfig
    from boxctl import __version__ as BOXCTL_VERSION

    config = ProjectConfig(project_dir)
    if config.exists():
        config.boxctl_version = BOXCTL_VERSION
        config.save(quiet=True)


# Phase descriptions for container init status display
_INIT_PHASE_DESCRIPTIONS = {
    "starting": "Starting container",
    "user": "Creating user",
    "ssh": "Configuring SSH",
    "mcp_packages": "Installing MCP dependencies",
    "project_packages": "Installing project packages",
    "mcp_servers": "Starting MCP servers",
    "container_client": "Starting container client",
    "ready": "Ready",
    "unknown": "Initializing",
}


def wait_for_container_ready(
    manager: "ContainerManager",
    container_name: str,
    timeout_s: float = 90.0,
) -> bool:
    """Wait for container to be ready with live status display.

    Shows initialization progress as a checklist of packages being installed.

    Args:
        manager: ContainerManager instance
        container_name: Name of container to wait for
        timeout_s: Maximum time to wait (default 90s)

    Returns:
        True if container is healthy, False if timeout/error/unhealthy
    """
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text
    import time
    import json

    current_phase = "starting"
    current_details = ""
    install_progress = {"items": []}

    def get_install_progress() -> dict:
        """Read install progress from container."""
        try:
            container = manager.get_container(container_name)
            if container:
                result = container.exec_run(["cat", "/tmp/install-progress.json"], user="root")
                if result.exit_code == 0:
                    return json.loads(result.output.decode("utf-8"))
        except Exception:
            pass
        return {"items": []}

    def render_status() -> Table:
        """Render status with checklist."""
        table = Table.grid(padding=(0, 1))
        table.add_column(width=3)
        table.add_column()

        # Show current phase with spinner
        desc = _INIT_PHASE_DESCRIPTIONS.get(current_phase, current_phase)
        if current_phase == "ready":
            table.add_row("[green]✓[/green]", f"[green]{desc}[/green]")
        else:
            table.add_row(Spinner("dots", style="cyan"), f"[bold cyan]{desc}[/bold cyan]")

        # Show install checklist if available
        if install_progress.get("items"):
            for item in install_progress["items"]:
                status = item.get("status", "pending")
                name = item.get("name", "unknown")
                pkg_type = item.get("type", "")

                if status == "done":
                    icon = "[green]✓[/green]"
                    style = "green"
                elif status == "failed":
                    icon = "[red]✗[/red]"
                    style = "red"
                elif status == "installing":
                    icon = Spinner("dots", style="yellow")
                    style = "yellow"
                else:  # pending
                    icon = "[dim]○[/dim]"
                    style = "dim"

                label = f"[{style}]{pkg_type}: {name}[/{style}]"
                table.add_row(icon, label)

        return table

    with Live(render_status(), refresh_per_second=10, transient=True) as live:
        deadline = time.time() + timeout_s
        last_status = None

        while time.time() < deadline:
            container = manager.get_container(container_name)

            # Container must be running
            if container is None or container.status != "running":
                return False

            # Refresh container state
            container.reload()

            # Get health status
            health = container.attrs.get("State", {}).get("Health", {})
            health_status = health.get("Status", "none")

            # Read init status
            init_phase, init_details = manager.get_container_init_status(container_name)
            current_phase = init_phase
            current_details = init_details

            # Read install progress
            install_progress = get_install_progress()

            # Always update display
            live.update(render_status())

            if health_status == "healthy":
                return True
            elif health_status == "unhealthy":
                return False

            time.sleep(0.5)

        return False
