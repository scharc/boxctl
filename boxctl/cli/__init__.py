# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""boxctl CLI package."""

import click

from boxctl.container import ContainerManager

from boxctl.cli.helpers import console
from boxctl.cli.helpers import (
    BANNER,
    LOG_DOC_NAME,
    WORKSPACES_CONFIG_NAME,
    WORKSPACES_MOUNT_ROOT,
    _attach_tmux_session,
    _complete_session_name,
    _ensure_container_running,
    _get_tmux_sessions,
    _get_tmux_socket,
    _load_codex_config,
    _load_workspaces_config,
    _resolve_container_and_args,
    _resolve_tmux_prefix,
    _run_agent_command,
    _sanitize_mount_name,
    _sanitize_tmux_name,
    _save_workspaces_config,
)
from boxctl.cli.helpers.completions import (
    _complete_project_name,
    _complete_connect_session,
)


@click.group(invoke_without_command=True)
@click.version_option(version="0.3.1", prog_name="boxctl")
def cli():
    """boxctl - Secure, isolated Docker environment for Claude Code."""
    ctx = click.get_current_context()
    if ctx.invoked_subcommand is None:
        click.echo("Usage: boxctl [OPTIONS] COMMAND [ARGS]...\n")

        def _print_table(title: str, rows: list[tuple[str, str]], width: int) -> None:
            click.echo(f"{title}:")
            for name, desc in rows:
                click.echo(f"  {name.ljust(width)}  {desc}")
            click.echo("")

        groups = [
            (
                "Agents",
                [
                    ("claude", "Run Claude Code"),
                    ("superclaude", "Run Claude Code (auto-approve)"),
                    ("codex", "Run Codex"),
                    ("supercodex", "Run Codex (auto-approve)"),
                    ("gemini", "Run Gemini"),
                    ("supergemini", "Run Gemini (auto-approve)"),
                    ("run", "Run agent non-interactively (for scripting)"),
                ],
            ),
            (
                "Quick Commands",
                [
                    ("quick/q", "Mobile-friendly TUI menu"),
                    ("start", "Start container for current project"),
                    ("stop", "Stop container"),
                    ("list/ps", "List containers"),
                    ("shell", "Open shell in container"),
                    ("connect", "Connect to container/session"),
                    ("info", "Show container details"),
                    ("rebase", "Rebase project container to current base"),
                    ("remove", "Remove container"),
                    ("cleanup", "Remove stopped containers"),
                    ("setup", "Initialize + configure interactively"),
                    ("init", "Initialize .boxctl/ directory"),
                    ("reconfigure", "Change agent/project settings"),
                    ("rebuild", "Rebuild base Docker image"),
                ],
            ),
            (
                "Command Groups",
                [
                    ("project", "Lifecycle (init/start/stop/rebase/remove/info/list)"),
                    ("session", "Tmux sessions (new/list/attach/remove/rename)"),
                    ("worktree", "Git worktrees (ls/add/remove/prune)"),
                    ("network", "Connect to containers (list/available/connect/disconnect)"),
                    ("base", "Base image (rebuild)"),
                ],
            ),
            (
                "Libraries & Config",
                [
                    ("mcp/mcps", "MCP servers (manage/list/show/add/remove)"),
                    ("skill/skills", "Skills (manage/list/show/add/remove)"),
                    ("workspace", "Workspace mounts (list/add/remove)"),
                    ("packages", "Package management (list/add/remove)"),
                    ("ports", "Port forwarding (list/add/remove/status)"),
                    ("devices", "Device passthrough (list/add/remove/choose)"),
                    ("docker", "Docker socket access (enable/disable/status)"),
                    ("config", "Config utilities (migrate)"),
                    ("usage", "Agent rate limits (status/probe/reset/fallback)"),
                    ("logs", "Conversation logs (list/export/show)"),
                ],
            ),
            (
                "Service",
                [
                    ("service", "Host daemon (install/start/stop/status/logs/serve)"),
                ],
            ),
        ]

        width = max(len(name) for _, rows in groups for name, _ in rows)
        for title, rows in groups:
            _print_table(title, rows, width)
        click.echo("Use --help for full command details.")
        return


def main():
    """Main entry point."""
    # Auto-migrate legacy .agentbox → .boxctl in current project
    from boxctl.migrations.rename_migration import (
        auto_migrate_project_dir,
        warn_legacy_env_vars,
        warn_legacy_systemd_service,
        warn_shell_rc_files,
    )

    auto_migrate_project_dir()
    warn_legacy_env_vars()
    warn_shell_rc_files()
    warn_legacy_systemd_service()

    cli()


from boxctl.cli.commands import agents  # noqa: E402,F401
from boxctl.cli.commands import base  # noqa: E402,F401
from boxctl.cli.commands import devices  # noqa: E402,F401
from boxctl.cli.commands import docker  # noqa: E402,F401
from boxctl.cli.commands import mcp  # noqa: E402,F401
from boxctl.cli.commands import network  # noqa: E402,F401
from boxctl.cli.commands import packages  # noqa: E402,F401
from boxctl.cli.commands import ports  # noqa: E402,F401
from boxctl.cli.commands import project  # noqa: E402,F401
from boxctl.cli.commands import service  # noqa: E402,F401
from boxctl.cli.commands import sessions  # noqa: E402,F401
from boxctl.cli.commands import skill  # noqa: E402,F401
from boxctl.cli.commands import worktree  # noqa: E402,F401
from boxctl.cli.commands import workspace  # noqa: E402,F401
from boxctl.cli.commands import quick  # noqa: E402,F401
from boxctl.cli.commands import usage  # noqa: E402,F401
from boxctl.cli.commands import logs  # noqa: E402,F401
from boxctl.cli.commands import run  # noqa: E402,F401


# Shortcut commands that delegate to command groups
# These provide convenient top-level aliases for common operations


@cli.command("start")
def start_shortcut():
    """Start container for current project (shortcut for: project start)."""
    from boxctl.cli.commands.project import start

    ctx = click.get_current_context()
    ctx.invoke(start)


@cli.command("stop")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
def stop_shortcut(project_name):
    """Stop the project container (shortcut for: project stop)."""
    from boxctl.cli.commands.project import stop

    ctx = click.get_current_context()
    ctx.invoke(stop, project_name=project_name)


@cli.command("list")
@click.argument("show_all", required=False)
def list_shortcut(show_all):
    """List all boxctl containers (shortcut for: project list)."""
    from boxctl.cli.commands.project import list as project_list

    ctx = click.get_current_context()
    ctx.invoke(project_list, show_all=show_all)


@cli.command("ps")
@click.argument("show_all", required=False)
def ps_shortcut(show_all):
    """List all boxctl containers (alias for: list)."""
    from boxctl.cli.commands.project import list as project_list

    ctx = click.get_current_context()
    ctx.invoke(project_list, show_all=show_all)


@cli.command("shell")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
def shell_shortcut(project_name):
    """Open interactive shell in container (shortcut for: project shell)."""
    from boxctl.cli.commands.project import shell

    ctx = click.get_current_context()
    ctx.invoke(shell, project_name=project_name)


@cli.command("connect")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
@click.argument("session", required=False, shell_complete=_complete_connect_session)
def connect_shortcut(project_name, session):
    """Connect to container (shortcut for: project connect)."""
    from boxctl.cli.commands.project import connect

    ctx = click.get_current_context()
    ctx.invoke(connect, project_name=project_name, session=session)


@cli.command("info")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
def info_shortcut(project_name):
    """Show container info (shortcut for: project info)."""
    from boxctl.cli.commands.project import info

    ctx = click.get_current_context()
    ctx.invoke(info, project_name=project_name)


@cli.command("remove")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
@click.argument("force_remove", required=False)
def remove_shortcut(project_name, force_remove):
    """Remove the project container (shortcut for: project remove)."""
    from boxctl.cli.commands.project import remove

    ctx = click.get_current_context()
    ctx.invoke(remove, project_name=project_name, force_remove=force_remove)


@cli.command("cleanup")
def cleanup_shortcut():
    """Remove all stopped containers (shortcut for: project cleanup)."""
    from boxctl.cli.commands.project import cleanup

    ctx = click.get_current_context()
    ctx.invoke(cleanup)


@cli.command("rebase")
@click.argument("scope", required=False)
def rebase_shortcut(scope: str):
    """Rebase project container to current base (shortcut for: project rebase).

    Pass 'all' as argument to rebase all existing containers.
    """
    from boxctl.cli.commands.project import rebase

    ctx = click.get_current_context()
    ctx.invoke(rebase, scope=scope)


@cli.command("init")
def init_shortcut():
    """Initialize .boxctl/ directory (shortcut for: project init)."""
    from boxctl.cli.commands.project import init

    ctx = click.get_current_context()
    ctx.invoke(init)


@cli.command("setup")
def setup_shortcut():
    """Initialize and configure boxctl (shortcut for: project setup)."""
    from boxctl.cli.commands.project import setup

    ctx = click.get_current_context()
    ctx.invoke(setup)


@cli.command("reconfigure")
def reconfigure_shortcut():
    """Reconfigure agent and project settings (shortcut for: project reconfigure)."""
    from boxctl.cli.commands.project import reconfigure

    ctx = click.get_current_context()
    ctx.invoke(reconfigure)


@cli.command("rebuild")
def rebuild_shortcut():
    """Rebuild base Docker image (shortcut for: base rebuild)."""
    from boxctl.cli.commands.base import rebuild

    ctx = click.get_current_context()
    ctx.invoke(rebuild)


@cli.command("fix-terminal")
def fix_terminal():
    """Reset terminal to fix mouse mode and other escape sequence issues.

    Use this command when your terminal is in a broken state after
    a container was destroyed or a tmux session was killed unexpectedly.

    This disables mouse tracking mode and resets terminal settings.
    """
    from boxctl.utils.terminal import reset_terminal

    reset_terminal()
    console.print("[green]Terminal reset complete[/green]")


# Register plural aliases for skill and mcp groups
from boxctl.cli.commands.skill import skill as skill_group
from boxctl.cli.commands.mcp import mcp as mcp_group
from boxctl.cli.commands.logs import logs as logs_group

cli.add_command(skill_group, name="skills")
cli.add_command(mcp_group, name="mcps")
cli.add_command(logs_group)


# Config command group for migration and config utilities
@cli.group()
def config():
    """Configuration utilities (migrate)."""
    pass


@config.command("migrate")
@click.option("--dry-run", is_flag=True, help="Show what would be migrated")
@click.option("--auto", is_flag=True, help="Apply all without prompting")
def config_migrate_shortcut(dry_run: bool, auto: bool):
    """Migrate config to latest format (shortcut for: project migrate)."""
    from boxctl.cli.commands.project import config_migrate

    ctx = click.get_current_context()
    ctx.invoke(config_migrate, dry_run=dry_run, auto=auto)


@cli.command("migrate")
@click.option("--dry-run", is_flag=True, help="Show what would be migrated without applying")
@click.option("--remove-containers", is_flag=True, help="Remove legacy agentbox-* containers")
@click.option("--force", is_flag=True, help="Force remove running containers")
@click.option("--fix-shell-rc", is_flag=True, help="Fix agentbox references in shell RC files")
@click.option("--fix-systemd", is_flag=True, help="Migrate agentboxd.service to boxctld.service")
@click.option("--fix-path", is_flag=True, help="Add boxctl bin directory to PATH")
def migrate_command(
    dry_run: bool,
    remove_containers: bool,
    force: bool,
    fix_shell_rc: bool,
    fix_systemd: bool,
    fix_path: bool,
):
    """Migrate from agentbox to boxctl.

    Migrates global configuration directories from the legacy 'agentbox'
    naming to the new 'boxctl' naming:

    \b
      ~/.config/agentbox  →  ~/.config/boxctl
      ~/.local/share/agentbox  →  ~/.local/share/boxctl

    Also checks for legacy containers, environment variables, shell RC files,
    and systemd service files.

    Use --remove-containers to stop and remove old agentbox-* containers.
    Use --force with --remove-containers to force-remove running containers.
    Use --fix-shell-rc to auto-fix agentbox references in shell config files.
    Use --fix-systemd to migrate agentboxd.service to boxctld.service.
    Use --fix-path to add boxctl bin directory to shell PATH.

    Note: Project-level .agentbox directories are auto-migrated on first use.
    """
    from boxctl.migrations.rename_migration import (
        check_legacy_config_file,
        check_legacy_global_config,
        check_legacy_containers,
        check_legacy_project_dir,
        check_legacy_systemd_service,
        check_misplaced_config_file,
        check_path_setup,
        check_shell_rc_files,
        cleanup_legacy_project_files,
        fix_path_setup,
        fix_shell_rc_files,
        migrate_config_file,
        migrate_global_config,
        migrate_project_dir,
        migrate_systemd_service,
        remove_legacy_containers,
        warn_legacy_containers,
        warn_legacy_env_vars,
        warn_legacy_systemd_service,
        warn_path_setup,
        warn_shell_rc_files,
    )

    has_legacy, legacy_paths = check_legacy_global_config()

    if not has_legacy:
        console.print("[green]No legacy agentbox configuration found.[/green]")
        console.print("[dim]Global config is already using boxctl naming.[/dim]")
    else:
        console.print("[bold]Found legacy agentbox directories:[/bold]")
        for path in legacy_paths:
            console.print(f"  [yellow]{path}[/yellow]")
        console.print()

        if dry_run:
            console.print("[blue]Dry run - no changes made.[/blue]")
            migrate_global_config(dry_run=True)
        else:
            migrate_global_config(dry_run=False)

    # Check for project-level legacy files in current directory
    # Use BOXCTL_PROJECT_DIR (set by wrapper) since we run from boxctl source dir
    import os
    from pathlib import Path

    project_dir_str = os.environ.get("BOXCTL_PROJECT_DIR")
    cwd = Path(project_dir_str) if project_dir_str else Path.cwd()

    # Check for .agentbox directory
    if check_legacy_project_dir(cwd):
        console.print()
        console.print(f"[yellow]Found .agentbox directory in {cwd}[/yellow]")
        if not dry_run:
            migrate_project_dir(cwd)
        else:
            console.print("[blue]Dry run - would migrate .agentbox → .boxctl[/blue]")

    # Check for .agentbox.yml or misplaced .boxctl.yml config file
    if check_legacy_config_file(cwd):
        console.print()
        console.print(f"[yellow]Found .agentbox.yml config file in {cwd}[/yellow]")
        if not dry_run:
            migrate_config_file(cwd)
        else:
            console.print("[blue]Dry run - would migrate .agentbox.yml → .boxctl/config.yml[/blue]")
    elif check_misplaced_config_file(cwd):
        console.print()
        console.print(f"[yellow]Found misplaced .boxctl.yml in project root[/yellow]")
        console.print("[dim]Config should be at .boxctl/config.yml[/dim]")
        if not dry_run:
            migrate_config_file(cwd)
        else:
            console.print("[blue]Dry run - would migrate .boxctl.yml → .boxctl/config.yml[/blue]")

    # Clean up legacy project files (.claude/, agentbox.config.json, .mcp.json)
    console.print()
    console.print(f"[dim]Checking project directory: {cwd}[/dim]")
    cleanup_actions = cleanup_legacy_project_files(cwd, dry_run=dry_run)
    if cleanup_actions:
        console.print("[bold]Project cleanup:[/bold]")
        for action in cleanup_actions:
            console.print(f"  {action}")
    else:
        console.print("[dim]No legacy project files found to clean up.[/dim]")

    # Handle legacy containers
    legacy_containers = check_legacy_containers()
    if legacy_containers:
        if remove_containers:
            console.print()
            console.print(f"[bold]Removing {len(legacy_containers)} legacy containers...[/bold]")
            stopped, removed = remove_legacy_containers(dry_run=dry_run, force=force)
            if not dry_run:
                console.print()
                console.print(
                    f"[green]Stopped {stopped} containers, removed {removed} containers[/green]"
                )
        else:
            warn_legacy_containers()
            console.print("[dim]Use --remove-containers to clean up legacy containers[/dim]")
            console.print(
                "[dim]Use --remove-containers --force to force-remove running containers[/dim]"
            )
            console.print()

    warn_legacy_env_vars()

    # Handle shell RC files
    rc_files = check_shell_rc_files()
    if rc_files:
        if fix_shell_rc:
            console.print()
            console.print(f"[bold]Fixing {len(rc_files)} shell config file(s)...[/bold]")
            fix_shell_rc_files(dry_run=dry_run)
        else:
            warn_shell_rc_files()

    # Handle systemd service
    if check_legacy_systemd_service():
        if fix_systemd:
            console.print()
            console.print("[bold]Migrating systemd service...[/bold]")
            success, message = migrate_systemd_service(dry_run=dry_run)
            if success:
                console.print(f"[green]{message}[/green]")
            else:
                console.print(f"[red]{message}[/red]")
        else:
            warn_legacy_systemd_service()

    # Handle PATH setup
    is_path_setup, _ = check_path_setup()
    if not is_path_setup:
        if fix_path:
            console.print()
            console.print("[bold]Setting up PATH...[/bold]")
            fix_path_setup(dry_run=dry_run)
        else:
            warn_path_setup()
