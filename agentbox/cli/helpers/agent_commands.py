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

from agentbox.container import ContainerManager
from agentbox.cli.helpers.tmux_ops import _sanitize_tmux_name, _resolve_tmux_prefix, _warn_if_base_outdated
from agentbox.cli.helpers.utils import _sync_library_mcps
from agentbox.utils.terminal import reset_terminal
from agentbox.utils.project import resolve_project_dir, get_agentbox_dir

console = Console()


def _resolve_container_and_args(
    manager: ContainerManager,
    project: Optional[str],
    args: tuple,
) -> tuple[str, tuple]:
    if project and not manager.container_exists(
        manager.get_container_name(manager.sanitize_project_name(project))
    ):
        args = (project,) + args
        project = None

    if project is None:
        project_name = manager.get_project_name()
    else:
        project_name = manager.sanitize_project_name(project)

    container_name = manager.get_container_name(project_name)
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
    title = f"AGENTBOX {container_name} | {display}"
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
        f"tmux set-option -t {shlex.quote(session_name)} mouse on; "
        f"tmux set-option -t {shlex.quote(session_name)} set-clipboard on; "
        f"tmux set-option -t {shlex.quote(session_name)} history-limit 50000; "
        # Auto-copy mouse selection to host clipboard via abox-clipboard (uses host's wl-copy/xclip)
        # Use copy-pipe-and-cancel to properly exit selection mode after copying
        f"tmux bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel 'abox-clipboard'; "
        f"tmux bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel 'abox-clipboard'; "
        # Enable mouse wheel scrolling (ensure default bindings work)
        f"tmux bind-key -T root WheelUpPane if-shell -F -t = '{{mouse_any_flag}}' 'send-keys -M' 'if-shell -F -t = \"{{pane_in_mode}}\" \"send-keys -M\" \"copy-mode -e\"'; "
        f"tmux set-option -t {shlex.quote(session_name)} status-left "
        f"{shlex.quote(' AGENTBOX ' + container_name + ' | ' + display + ' ')}; "
        f"tmux set-option -t {shlex.quote(session_name)} status-right ''; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-status top; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-style 'fg=colour226'; "
        f"tmux set-option -t {shlex.quote(session_name)} pane-border-format "
        f"{shlex.quote(' AGENTBOX ' + container_name + ' | ' + display + ' ')}; "
    )

    if reuse_tmux_session:
        tmux_setup = (
            f"if tmux has-session -t {shlex.quote(session_name)} 2>/dev/null; then "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(session_name)}; "
            f"else "
            f"tmux new-session -d -s {shlex.quote(session_name)} "
            f"/bin/bash -lc {shlex.quote(inner_cmd)}; "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(session_name)}; "
            f"fi"
        )
    else:
        tmux_setup = (
            f"tmux new-session -d -s {shlex.quote(session_name)} "
            f"/bin/bash -lc {shlex.quote(inner_cmd)}; "
            f"{tmux_options}"
            f"tmux attach -t {shlex.quote(session_name)}"
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
    agent_cmd.extend([
        "-e",
        f"AGENTBOX_AGENT_LABEL={display}",
        "-e",
        f"AGENTBOX_SESSION_NAME={session_name}",
        "-e",
        f"AGENTBOX_CONTAINER={container_name}",
    ])
    agent_cmd.extend([
        container_name,
        "/bin/bash",
        "-lc",
        tmux_setup,
    ])

    return agent_cmd, tmux_setup, display, session_name


def _require_config_migrated(project_dir: Path) -> bool:
    """Check if config needs migration and block if so.

    Args:
        project_dir: Project directory path

    Returns:
        True if config is up to date, False if migrations needed (blocks start)
    """
    from agentbox.config import ProjectConfig
    from agentbox.migrations import MigrationRunner, get_migration

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
    console.print("[yellow]Your .agentbox.yml uses deprecated settings:[/yellow]\n")

    for result in applicable:
        migration = get_migration(result.migration_id)
        console.print(f"  • {migration.description}")

    console.print("\n[blue]Run this command to update your config:[/blue]")
    console.print("  abox config migrate\n")

    return False


def _ensure_container_running(manager: ContainerManager, container_name: str) -> bool:
    """Ensure the container exists and is running, auto-starting if needed.

    When creating a new container, this function:
    1. Syncs MCP servers from library
    2. Creates the container
    3. Applies config (packages) after container starts
    """
    if manager.is_running(container_name):
        return True

    if manager.container_exists(container_name):
        console.print(f"[blue]Container {container_name} is not running. Starting...[/blue]")
        manager.start_container(container_name)
        return True

    console.print(f"[blue]Container {container_name} doesn't exist. Creating and starting...[/blue]")
    project_dir = resolve_project_dir()
    project_name = manager.get_project_name(project_dir)
    agentbox_dir = get_agentbox_dir(project_dir)

    try:
        # Sync MCP servers from library before creating container
        if agentbox_dir.exists():
            _sync_library_mcps(agentbox_dir, quiet=True)

        # Create the container
        manager.create_container(
            project_name=project_name,
            project_dir=project_dir,
        )

        # Apply config (packages) after container is created
        from agentbox.config import ProjectConfig
        config = ProjectConfig(project_dir)
        if config.exists():
            config.rebuild(manager, container_name)

        console.print(f"[green]Container {container_name} created and started[/green]")
        return True
    except Exception as exc:
        console.print(f"[red]Failed to create container: {exc}[/red]")
        return False


def _run_agent_command_noninteractive(
    manager: ContainerManager,
    project: Optional[str],
    args: tuple,
    command: str,
    extra_args: Optional[list[str]] = None,
    label: Optional[str] = None,
    extra_env: Optional[dict[str, str]] = None,
    workdir: Optional[str] = None,
) -> int:
    """Run an agent command in non-interactive mode (no tmux, no TTY).

    Returns the exit code of the command.
    """
    container_name, args = _resolve_container_and_args(manager, project, args)

    # Get project dir for config version check (before starting container)
    project_dir = resolve_project_dir()

    # Block if config needs migration
    if not _require_config_migrated(project_dir):
        raise SystemExit(1)

    if not _ensure_container_running(manager, container_name):
        console.print(f"[red]Failed to start container {container_name}[/red]")
        raise SystemExit(1)

    _warn_if_base_outdated(manager, container_name, project_dir)

    if not manager.wait_for_user(container_name, "abox"):
        console.print("[red]Container user 'abox' not found.[/red]")
        console.print("[yellow]Rebuild the base image with: agentbox update[/yellow]")
        raise SystemExit(1)

    from agentbox.cli.helpers.utils import wait_for_container_ready

    if not wait_for_container_ready(manager, container_name, timeout_s=90.0):
        console.print("[red]Container failed to initialize (timeout or health check failed)[/red]")
        raise SystemExit(1)

    # Build command for non-interactive execution
    cmd = [command]
    if extra_args:
        cmd.extend(extra_args)
    if args:
        cmd.extend(args)

    display = label or command

    # Build docker exec command without -it (non-interactive)
    docker_cmd = [
        "docker",
        "exec",
        "-u", "abox",
        "-w", workdir or "/workspace",
        "-e", "HOME=/home/abox",
        "-e", "USER=abox",
    ]
    if extra_env:
        for key, value in extra_env.items():
            docker_cmd.extend(["-e", f"{key}={value}"])
    docker_cmd.extend([
        "-e", f"AGENTBOX_AGENT_LABEL={display}",
        "-e", f"AGENTBOX_CONTAINER={container_name}",
        container_name,
    ])
    docker_cmd.extend(cmd)

    import subprocess
    result = subprocess.run(docker_cmd)
    return result.returncode


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

    if not _ensure_container_running(manager, container_name):
        console.print(f"[red]Failed to start container {container_name}[/red]")
        raise SystemExit(1)

    _warn_if_base_outdated(manager, container_name, project_dir)

    if not manager.wait_for_user(container_name, "abox"):
        console.print("[red]Container user 'abox' not found.[/red]")
        console.print("[yellow]Rebuild the base image with: agentbox update[/yellow]")
        raise SystemExit(1)

    from agentbox.cli.helpers.utils import wait_for_container_ready

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
    banner_title = f"AGENTBOX CONTAINER: {container_name}"
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
