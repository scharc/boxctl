# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Agent command building and execution."""

import shlex
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

from boxctl.container import ContainerManager
from boxctl.cli.helpers.tmux_ops import (
    _sanitize_tmux_name,
    _resolve_tmux_prefix,
    _warn_if_base_outdated,
)
from boxctl.cli.helpers.utils import _sync_library_mcps, ContainerError
from boxctl.cli.helpers.port_utils import (
    check_configured_ports,
    format_conflict_message,
    release_port_from_container,
    PortConflict,
)
from boxctl.utils.terminal import reset_terminal
from boxctl.utils.project import resolve_project_dir, get_boxctl_dir
from boxctl import container_naming

console = Console()


def _resolve_container_and_args(
    manager: ContainerManager,
    project: Optional[str],
    args: tuple,
) -> tuple[str, tuple]:
    if project:
        # Check if explicit project container exists
        project_name = container_naming.sanitize_name(project)
        test_container = f"{container_naming.CONTAINER_PREFIX}{project_name}"
        if not manager.container_exists(test_container):
            args = (project,) + args
            project = None

    if project is None:
        # Use collision-aware resolution based on current directory
        container_name = container_naming.resolve_container_name()
    else:
        # Explicit project name - use simple name generation
        project_name = container_naming.sanitize_name(project)
        container_name = f"{container_naming.CONTAINER_PREFIX}{project_name}"

    return container_name, args


def _build_agent_command(
    container_name: str,
    command: str,
    args: tuple,
    extra_args: Optional[list[str]] = None,
    label: Optional[str] = None,
    reuse_tmux_session: bool = False,
    session_key: Optional[str] = None,
    persist_session: bool = False,
    extra_env: Optional[dict[str, str]] = None,
    custom_session_name: Optional[str] = None,
    workdir: Optional[str] = None,
) -> tuple[list[str], str, str, str]:
    cmd = [command]
    if extra_args:
        cmd.extend(extra_args)
    if args:
        cmd.extend(args)

    display = label or command
    escaped_cmd = " ".join(shlex.quote(part) for part in cmd)
    title = f"BOXCTL {container_name} | {display}"
    title_cmd = f"printf '\\033]0;{title}\\007'"
    if persist_session:
        inner_cmd = f"{title_cmd}; {escaped_cmd}; exec /bin/bash"
    else:
        inner_cmd = f"{title_cmd}; exec {escaped_cmd}"

    # Use custom session name if provided, otherwise use existing logic
    if custom_session_name:
        session_name = _sanitize_tmux_name(custom_session_name)
    else:
        session_suffix = "" if reuse_tmux_session else f"-{int(time.time())}"
        session_token = session_key or command
        session_raw = f"{session_token}{session_suffix}"
        session_name = _sanitize_tmux_name(session_raw)

    tmux_prefix = _resolve_tmux_prefix()

    tmux_prefix_option = ""
    if tmux_prefix:
        tmux_prefix_option = (
            f"tmux set-option -t {shlex.quote(session_name)} "
            f"prefix {shlex.quote(tmux_prefix)}; "
        )

    tmux_options = (
        f"{tmux_prefix_option}tmux set-option -t {shlex.quote(session_name)} status on; "
        f"tmux set-option -t {shlex.quote(session_name)} status-position top; "
        f"tmux set-option -t {shlex.quote(session_name)} status-style 'bg=colour226,fg=colour232'; "
        # Mouse mode disabled - let terminal (foot) handle selection directly to PRIMARY buffer
        f"tmux set-option -t {shlex.quote(session_name)} mouse off; "
        f"tmux set-option -t {shlex.quote(session_name)} history-limit 50000; "
        # PageUp/PageDown for scrolling without prefix key
        f"tmux bind-key -n PPage copy-mode -eu; "  # PageUp enters copy mode and scrolls up
        f"tmux bind-key -T copy-mode PPage send-keys -X page-up; "
        f"tmux bind-key -T copy-mode NPage send-keys -X page-down; "
        f"tmux bind-key -T copy-mode-vi PPage send-keys -X page-up; "
        f"tmux bind-key -T copy-mode-vi NPage send-keys -X page-down; "
        f"tmux set-option -t {shlex.quote(session_name)} status-left "
        f"{shlex.quote(' BOXCTL ' + container_name + ' | ' + display + ' ')}; "
        f"tmux set-option -t {shlex.quote(session_name)} status-right ''; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-status top; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-style 'fg=colour226'; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-format "
        f"{shlex.quote(' BOXCTL ' + container_name + ' | ' + display + ' ')}; "
    )

    # Use = prefix for exact session matching (prevents tmux prefix matching)
    exact_session = f"={session_name}"
    if reuse_tmux_session:
        tmux_setup = (
            # Use exact_session for has-session check too, to prevent prefix matching
            # (e.g., "superclaude" matching "superclaude-1234567890")
            f"if tmux has-session -t {shlex.quote(exact_session)} 2>/dev/null; then "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(exact_session)}; "
            f"else "
            f"tmux new-session -d -s {shlex.quote(session_name)} "
            f"/bin/bash -lc {shlex.quote(inner_cmd)}; "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(exact_session)}; "
            f"fi"
        )
    else:
        tmux_setup = (
            f"tmux new-session -d -s {shlex.quote(session_name)} "
            f"/bin/bash -lc {shlex.quote(inner_cmd)}; "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(exact_session)}"
        )

    agent_cmd = [
        "docker",
        "exec",
        "-it",
        "-u",
        "abox",
        "-w",
        workdir or "/workspace",
        "-e",
        "HOME=/home/abox",
        "-e",
        "USER=abox",
    ]
    if extra_env:
        for key, value in extra_env.items():
            agent_cmd.extend(["-e", f"{key}={value}"])
    agent_cmd.extend(
        [
            "-e",
            f"BOXCTL_AGENT_LABEL={display}",
            "-e",
            f"BOXCTL_SESSION_NAME={session_name}",
            "-e",
            f"BOXCTL_CONTAINER={container_name}",
        ]
    )
    agent_cmd.extend(
        [
            container_name,
            "/bin/bash",
            "-lc",
            tmux_setup,
        ]
    )

    return agent_cmd, tmux_setup, display, session_name


def _require_config_migrated(project_dir: Path) -> bool:
    """Check if config needs migration and block if so.

    Args:
        project_dir: Project directory path

    Returns:
        True if config is up to date, False if migrations needed (blocks start)
    """
    from boxctl.config import ProjectConfig
    from boxctl.migrations import MigrationRunner, get_migration

    config = ProjectConfig(project_dir)
    if not config.exists():
        return True

    runner = MigrationRunner(
        raw_config=config.config,
        project_dir=project_dir,
        interactive=False,
        auto_migrate=False,
    )

    results = runner.check_all()
    applicable = [r for r in results if r.applicable]

    if not applicable:
        return True

    # Show what needs to be migrated
    console.print("\n[red bold]Config migration required[/red bold]")
    console.print("[yellow]Your .boxctl/config.yml uses deprecated settings:[/yellow]\n")

    for result in applicable:
        migration = get_migration(result.migration_id)
        console.print(f"  • {migration.description}")

    console.print("\n[blue]Run this command to update your config:[/blue]")
    console.print("  abox config migrate\n")

    return False


def _handle_port_conflicts(project_dir: Path, container_name: str) -> bool:
    """Check for port conflicts and handle them interactively.

    Args:
        project_dir: Path to the project directory
        container_name: Name of the container being started

    Returns:
        True if we should proceed with container start, False to abort
    """
    import click

    conflicts = check_configured_ports(project_dir, container_name)
    if not conflicts:
        return True

    console.print("\n[yellow]Port conflicts detected:[/yellow]")
    for conflict in conflicts:
        console.print(f"  • {format_conflict_message(conflict)}")
    console.print()

    # Group by blocker type for resolution
    boxctl_conflicts = [c for c in conflicts if c.blocker_type == "boxctl"]
    external_conflicts = [c for c in conflicts if c.blocker_type == "external"]

    # Handle boxctl conflicts - offer to release
    for conflict in boxctl_conflicts:
        msg = format_conflict_message(conflict)
        display_name = (
            container_naming.extract_project_name(conflict.blocker_container)
            or conflict.blocker_container
        )

        console.print(f"\n[bold]{msg}[/bold]")
        console.print(f"  0. Abort")
        console.print(f"  1. Release port {conflict.port} from {display_name}")
        console.print(f"  2. Use different port for {conflict.port}")
        console.print(f"  3. Skip this port")

        choice = click.prompt("Choose option", type=int, default=1)

        if choice == 0:
            console.print("[red]Aborted[/red]")
            return False
        elif choice == 1:
            # Release the port
            success = release_port_from_container(
                conflict.blocker_container,
                conflict.port,
                conflict.direction,
            )
            if success:
                console.print(f"[green]Released port {conflict.port}[/green]")
            else:
                console.print(f"[red]Failed to release port {conflict.port}[/red]")
                return False
        elif choice == 2:
            # Use different port
            new_port = click.prompt(
                f"Enter new host port for container:{conflict.container_port}", type=int
            )
            _update_port_config(project_dir, conflict, new_port)
            console.print(
                f"[green]Updated config: host:{new_port} → container:{conflict.container_port}[/green]"
            )
        elif choice == 3:
            # Skip - remove from config temporarily
            console.print(f"[yellow]Skipping port {conflict.port}[/yellow]")
            _remove_port_from_config(project_dir, conflict)
            return False

    # Handle external conflicts - can only skip or use different port
    for conflict in external_conflicts:
        msg = format_conflict_message(conflict)

        console.print(f"\n[bold]{msg}[/bold]")
        console.print(f"  0. Abort")
        console.print(f"  1. Use different port for {conflict.port}")
        console.print(f"  2. Skip this port")

        choice = click.prompt("Choose option", type=int, default=1)

        if choice == 0:
            console.print("[red]Aborted[/red]")
            return False
        elif choice == 1:
            # Use different port
            new_port = click.prompt(
                f"Enter new host port for container:{conflict.container_port}", type=int
            )
            _update_port_config(project_dir, conflict, new_port)
            console.print(
                f"[green]Updated config: host:{new_port} → container:{conflict.container_port}[/green]"
            )
        elif choice == 2:
            # Skip
            console.print(f"[yellow]Skipping port {conflict.port}[/yellow]")
            _remove_port_from_config(project_dir, conflict)

    return True


def _update_port_config(project_dir: Path, conflict: PortConflict, new_port: int) -> None:
    """Update the port config to use a different host port."""
    from boxctl.config import ProjectConfig

    config = ProjectConfig(project_dir)

    if conflict.direction == "exposed":
        # Update ports.host
        new_ports = []
        for port_spec in config.ports_host:
            host_port, container_port = _parse_port_spec_simple(port_spec)
            if host_port == conflict.port:
                new_ports.append(f"{new_port}:{container_port}")
            else:
                new_ports.append(port_spec)
        config.ports = {"host": new_ports, "container": config.ports_container}
    else:
        # Update ports.container
        new_ports = []
        for port_config in config.ports_container:
            if isinstance(port_config, dict):
                if port_config.get("port") == conflict.port:
                    port_config = dict(port_config)
                    port_config["port"] = new_port
                new_ports.append(port_config)
            else:
                host_port, container_port = _parse_port_spec_simple(port_config)
                if host_port == conflict.port:
                    new_ports.append({"port": new_port, "container_port": container_port})
                else:
                    new_ports.append(port_config)
        config.ports = {"host": config.ports_host, "container": new_ports}

    config.save()


def _remove_port_from_config(project_dir: Path, conflict: PortConflict) -> None:
    """Remove a conflicting port from config."""
    from boxctl.config import ProjectConfig

    config = ProjectConfig(project_dir)

    if conflict.direction == "exposed":
        new_ports = []
        for port_spec in config.ports_host:
            host_port, _ = _parse_port_spec_simple(port_spec)
            if host_port != conflict.port:
                new_ports.append(port_spec)
        config.ports = {"host": new_ports, "container": config.ports_container}
    else:
        new_ports = []
        for port_config in config.ports_container:
            if isinstance(port_config, dict):
                if port_config.get("port") != conflict.port:
                    new_ports.append(port_config)
            else:
                host_port, _ = _parse_port_spec_simple(port_config)
                if host_port != conflict.port:
                    new_ports.append(port_config)
        config.ports = {"host": config.ports_host, "container": new_ports}

    config.save()


def _parse_port_spec_simple(port_spec) -> tuple:
    """Simple port spec parser returning (host_port, container_port)."""
    try:
        if isinstance(port_spec, int):
            return (port_spec, port_spec)
        parts = str(port_spec).split(":")
        if len(parts) == 1:
            port = int(parts[0])
            return (port, port)
        elif len(parts) == 2:
            return (int(parts[0]), int(parts[1]))
        elif len(parts) == 3:
            return (int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        pass
    return (None, None)


def _ensure_container_running(manager: ContainerManager, container_name: str) -> None:
    """Ensure the container exists and is running, auto-starting if needed.

    When creating a new container, this function:
    1. Checks for port conflicts and handles them interactively
    2. Syncs MCP servers from library
    3. Creates the container
    4. Applies config (packages) after container starts

    Raises:
        ContainerError: If container creation or startup fails.
        SystemExit: If user aborts due to port conflicts.
    """
    if manager.is_running(container_name):
        return

    # Check for port conflicts before starting
    project_dir = resolve_project_dir()
    if not _handle_port_conflicts(project_dir, container_name):
        raise SystemExit(1)

    if manager.container_exists(container_name):
        console.print(f"[blue]Container {container_name} is not running. Starting...[/blue]")
        try:
            manager.start_container(container_name)
            return
        except Exception as exc:
            raise ContainerError(
                f"Failed to start container {container_name}",
                hint=f"docker logs {container_name}  # Check container logs",
            ) from exc

    console.print(
        f"[blue]Container {container_name} doesn't exist. Creating and starting...[/blue]"
    )
    project_name = manager.get_project_name(project_dir)
    boxctl_dir = get_boxctl_dir(project_dir)

    try:
        # Sync MCP servers from library before creating container
        if boxctl_dir.exists():
            _sync_library_mcps(boxctl_dir, quiet=True)

        # Create the container
        manager.create_container(
            project_name=project_name,
            project_dir=project_dir,
        )

        # Apply config (packages) after container is created
        from boxctl.config import ProjectConfig

        config = ProjectConfig(project_dir)
        if config.exists():
            config.rebuild(manager, container_name)

        console.print(f"[green]Container {container_name} created and started[/green]")
    except Exception as exc:
        raise ContainerError(
            f"Failed to create container {container_name}\n\nError: {exc}",
            hint="docker ps  # Check if Docker is running",
        ) from exc


def _run_agent_command(
    manager: ContainerManager,
    project: Optional[str],
    args: tuple,
    command: str,
    extra_args: Optional[list[str]] = None,
    label: Optional[str] = None,
    reuse_tmux_session: bool = False,
    session_key: Optional[str] = None,
    persist_session: bool = False,
    extra_env: Optional[dict[str, str]] = None,
    custom_session_name: Optional[str] = None,
    workdir: Optional[str] = None,
) -> None:
    container_name, args = _resolve_container_and_args(manager, project, args)

    # Get project dir for config version check (before starting container)
    project_dir = resolve_project_dir()

    # Block if config needs migration
    if not _require_config_migrated(project_dir):
        raise SystemExit(1)

    # Ensure container is running (raises ContainerError on failure)
    _ensure_container_running(manager, container_name)

    _warn_if_base_outdated(manager, container_name, project_dir)

    if not manager.wait_for_user(container_name, "abox"):
        console.print("[red]Container user 'abox' not found.[/red]")
        console.print("[yellow]Rebuild the base image with: boxctl update[/yellow]")
        raise SystemExit(1)

    from boxctl.cli.helpers.utils import wait_for_container_ready

    if not wait_for_container_ready(manager, container_name, timeout_s=90.0):
        console.print("[red]Container failed to initialize (timeout or health check failed)[/red]")
        console.print("[yellow]Check container logs:[/yellow]")
        console.print(f"  docker logs {container_name}")
        console.print("[yellow]Check health status:[/yellow]")
        console.print(f"  docker inspect {container_name} | jq '.State.Health'")
        raise SystemExit(1)

    agent_cmd, tmux_setup, display, _ = _build_agent_command(
        container_name=container_name,
        command=command,
        args=args,
        extra_args=extra_args,
        label=label,
        reuse_tmux_session=reuse_tmux_session,
        session_key=session_key,
        persist_session=persist_session,
        extra_env=extra_env,
        custom_session_name=custom_session_name,
        workdir=workdir,
    )
    banner_title = f"BOXCTL CONTAINER: {container_name}"
    banner_action = f"RUNNING: {display}"
    width = max(len(banner_title), len(banner_action))
    line = "-" * width
    console.print("")
    console.print(f"+{line}+")
    console.print(f"|{banner_title.ljust(width)}|")
    console.print(f"|{banner_action.ljust(width)}|")
    console.print(f"+{line}+")
    try:
        import subprocess

        result = subprocess.run(agent_cmd)
        sys.exit(result.returncode)
    finally:
        # Reset terminal to disable mouse mode and clean state after tmux exits
        # This handles cases where tmux session is killed or container is destroyed
        reset_terminal()
