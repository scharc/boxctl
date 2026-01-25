# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Project lifecycle commands."""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.table import Table

from agentbox import __version__ as AGENTBOX_VERSION
from agentbox.cli import cli
from agentbox.config import ProjectConfig
from agentbox.container import ContainerManager
from agentbox.utils.terminal import reset_terminal
from agentbox.cli.helpers import (
    BANNER,
    LOG_DOC_NAME,
    _complete_project_name,
    _complete_connect_session,
    _attach_tmux_session,
    _copy_commands,
    _ensure_container_running,
    _get_project_context,
    _get_tmux_sessions,
    _rebuild_container,
    _require_container_running,
    _sync_library_mcps,
    _warn_if_agents_running,
    _warn_if_base_outdated,
    console,
    handle_errors,
    safe_rmtree,
    wait_for_container_ready,
)
from agentbox.utils.project import resolve_project_dir, get_agentbox_dir


@cli.group()
def project():
    """Manage project containers and lifecycle."""
    pass


def _check_worktree_uncommitted_changes(manager, container_name: str) -> list[dict]:
    """Check if any worktrees have uncommitted changes.

    Returns list of worktrees with uncommitted work.

    Performance optimized: Single docker exec call that:
    1. Lists all worktrees
    2. Checks status for each /git-worktrees/ path
    3. Returns combined results

    This replaces the previous 2-call approach (list + batch status).
    """
    from agentbox.container import get_abox_environment

    if not manager.is_running(container_name):
        return []

    # Single combined script that lists worktrees AND checks their status
    # This combines what was previously 2 docker exec calls into 1
    combined_script = '''
# Get worktree paths from /git-worktrees/
git -C /workspace worktree list --porcelain 2>/dev/null | while read line; do
    case "$line" in
        "worktree /git-worktrees/"*)
            path="${line#worktree }"
            if [ -d "$path" ]; then
                echo "PATH:$path"
                branch=$(git -C "$path" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
                echo "BRANCH:$branch"
                count=$(git -C "$path" status --porcelain 2>/dev/null | wc -l)
                echo "COUNT:$count"
            fi
            ;;
    esac
done
'''

    exit_code, output = manager.exec_command(
        container_name,
        ["bash", "-c", combined_script],
        environment=get_abox_environment(include_tmux=False, container_name=container_name),
        user="abox",
    )

    if exit_code != 0 or not output.strip():
        return []

    # Parse results using markers (handles edge cases reliably)
    results = []
    current = {}
    for line in output.strip().split("\n"):
        if line.startswith("PATH:"):
            if current.get("path") and current.get("changes", 0) > 0:
                results.append(current)
            current = {"path": line[5:]}
        elif line.startswith("BRANCH:"):
            current["branch"] = line[7:]
        elif line.startswith("COUNT:"):
            try:
                current["changes"] = int(line[6:].strip())
            except ValueError:
                current["changes"] = 0
    # Don't forget last entry
    if current.get("path") and current.get("changes", 0) > 0:
        results.append(current)

    return results


def _require_config_migrated(project_dir: Path) -> bool:
    """Check if config needs migration and block if so.

    Args:
        project_dir: Project directory path

    Returns:
        True if config is up to date, False if migrations needed (blocks start)
    """
    from agentbox.migrations import MigrationRunner

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
    console.print("[yellow]Your .agentbox/config.yml uses deprecated settings:[/yellow]\n")

    from agentbox.migrations import get_migration
    for result in applicable:
        migration = get_migration(result.migration_id)
        console.print(f"  • {migration.description}")

    console.print("\n[blue]Run this command to update your config:[/blue]")
    console.print("  abox config migrate\n")

    return False


@project.command(options_metavar="")
@handle_errors
def init():
    """Initialize .agentbox/ directory structure (non-interactive).

    Creates the .agentbox/ directory with default configuration files.
    Use 'agentbox setup' for an interactive setup wizard that helps
    configure common options.
    """
    console.print(BANNER, highlight=False, markup=False)
    project_dir = resolve_project_dir()
    agentbox_dir = get_agentbox_dir(project_dir)

    if agentbox_dir.exists():
        console.print(f"[yellow].agentbox/ already initialized in {project_dir}[/yellow]")

    console.print(f"[green]Initializing .agentbox/ in {project_dir}...[/green]")

    # Create directory structure
    # Agent configs are created in home dirs at container startup
    # Only project-level files go in .agentbox/
    for subdir in ["skills", "mcp"]:
        (agentbox_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Copy/update MCP servers and skills from library
    from agentbox.library import LibraryManager
    import shutil

    lib_manager = LibraryManager()

    # Copy/update MCPs
    _sync_library_mcps(agentbox_dir)

    # Copy/update default skills to root skills/ directory
    # Agent subdirs symlink to this at runtime
    if lib_manager.skills_dir.exists():
        for skill_path in lib_manager.skills_dir.iterdir():
            if skill_path.is_dir():
                target_path = agentbox_dir / "skills" / skill_path.name
                # safe_rmtree handles symlinks securely
                if safe_rmtree(target_path):
                    console.print(f"  [yellow]Updated skill: {skill_path.name}[/yellow]")
                else:
                    console.print(f"  [green]Copied skill: {skill_path.name}[/green]")
                shutil.copytree(skill_path, target_path)

    # Copy config templates from library
    package_root = Path(__file__).resolve().parents[3]
    templates_dir = package_root / "library" / "config" / "default"

    # Templates to copy: (source_relative_path, dest_relative_path)
    # Note: Agent configs (claude/config.json etc) are created in home dirs at container startup
    template_copies = [
        ("agents.md", "agents.md"),
        ("superagents.md", "superagents.md"),
    ]

    for src_rel, dest_rel in template_copies:
        src = templates_dir / src_rel
        dest = agentbox_dir / dest_rel
        if src.exists() and not dest.exists():
            dest.write_text(src.read_text())

    # Workspaces config
    workspaces_path = agentbox_dir / "workspaces.json"
    if not workspaces_path.exists():
        workspaces_path.write_text(json.dumps({"workspaces": []}, indent=2))

    # Gitignore
    gitignore_path = agentbox_dir / ".gitignore"
    gitignore_content = """# Runtime files (auto-generated)
mcp.json
install-manifest.json

# Environment secrets (if used)
.env
.env.local

# Logs
logs/
"""
    gitignore_path.write_text(gitignore_content)

    # Log file
    log_path = agentbox_dir / LOG_DOC_NAME
    if not log_path.exists():
        log_path.write_text("# Agentbox Log\n\n- ")

    # Add default MCPs (agentctl, agentbox-analyst)
    from agentbox.cli.commands.mcp import _add_mcp

    class _InitPctx:
        """Minimal context for _add_mcp during init."""
        def __init__(self, agentbox_dir: Path, project_dir: Path):
            self.agentbox_dir = agentbox_dir
            self.project_dir = project_dir

    init_pctx = _InitPctx(agentbox_dir, project_dir)
    default_mcps = ["agentctl", "agentbox-analyst"]
    for mcp_name in default_mcps:
        success, _ = _add_mcp(mcp_name, lib_manager, init_pctx)
        if success:
            console.print(f"  [green]Added default MCP: {mcp_name}[/green]")

    # Copy slash commands for all installed skills
    skills_dir = agentbox_dir / "skills"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                # Find source in library
                skill_source = lib_manager.skills_dir / skill_dir.name
                if not skill_source.exists():
                    skill_source = lib_manager.user_skills_dir / skill_dir.name
                if skill_source.exists():
                    copied = _copy_commands(skill_source, project_dir, "skill", skill_dir.name)
                    if copied:
                        console.print(f"  [green]Added commands for skill: {skill_dir.name}[/green]")

    # Create .agentbox/config.yml template if it doesn't exist
    project_config = ProjectConfig(project_dir)
    if not project_config.exists():
        project_config.create_template()

    console.print("\n[green]✓ Initialized .agentbox/[/green]")
    console.print("\n[blue]Created:[/blue]")
    console.print("  .agentbox/config.yml (project config)")
    console.print("  .agentbox/agents.md (agent instructions)")
    console.print("  .agentbox/superagents.md (super agent instructions)")
    console.print("  .agentbox/mcp/ (MCP server code)")
    console.print("  .agentbox/mcp-meta.json (MCP tracking)")
    console.print("  .agentbox/skills/ (installed skills)")
    console.print("  .agentbox/LOG.md")
    console.print("  .agentbox/.gitignore")
    console.print("\n[dim]Agent configs created at container startup in ~/.claude/, ~/.codex/, etc.[/dim]")
    console.print("\n[yellow]Tip: Edit .agentbox/config.yml to configure ports, volumes, etc.[/yellow]")
    console.print("[yellow]Tip: Create PLAN.md in project root for planning context[/yellow]")
    console.print("\n[blue]Next: agentbox start[/blue]")


def _prompt_choice(prompt: str, choices: list[str], default: str = None) -> str:
    """Prompt user to select from choices using number keys."""
    console.print(f"\n[bold]{prompt}[/bold]")
    for i, choice in enumerate(choices, 1):
        marker = " [dim](current)[/dim]" if choice == default else ""
        console.print(f"  [yellow]{i})[/yellow] {choice}{marker}")
    console.print(f"  [yellow]0)[/yellow] [dim]Keep current[/dim]")
    console.print(f"  [yellow]q)[/yellow] [dim]Quit[/dim]")

    while True:
        try:
            response = input("\nSelect [0-{}, q]: ".format(len(choices))).strip()
            if response.lower() in ("q", "quit", "exit"):
                console.print("\n[yellow]Aborted[/yellow]")
                sys.exit(130)
            if response == "" or response == "0":
                return default
            idx = int(response)
            if 1 <= idx <= len(choices):
                return choices[idx - 1]
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Aborted[/yellow]")
            sys.exit(130)  # Standard exit code for Ctrl+C
        except ValueError:
            pass
        console.print("[red]Invalid selection[/red]")


def _prompt_bool(prompt: str, default: bool) -> bool:
    """Prompt user for yes/no. Empty or '0' keeps current value."""
    default_str = "Y/n/q" if default else "y/N/q"
    try:
        response = input(f"\n{prompt} [{default_str}]: ").strip().lower()
        if response in ("q", "quit", "exit"):
            console.print("\n[yellow]Aborted[/yellow]")
            sys.exit(130)
        if response == "" or response == "0":
            return default
        return response in ("y", "yes", "true", "1")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Aborted[/yellow]")
        sys.exit(130)


def _send_test_notification(project_name: str) -> None:
    """Send a test notification through agentboxd."""
    import json
    import socket
    from agentbox.host_config import get_config

    config = get_config()
    sock_path = config.socket_path

    if not sock_path.exists():
        console.print("[yellow]⚠ agentboxd not running - start with 'agentbox service start'[/yellow]")
        return

    payload = {
        "action": "notify",
        "title": f"{project_name} | Test",
        "message": "This is a test notification from agentbox reconfigure",
        "urgency": "normal",
    }

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5.0)
            sock.connect(str(sock_path))
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            response = sock.recv(4096).decode("utf-8")

        result = json.loads(response.strip().splitlines()[-1])
        if result.get("ok"):
            console.print("[green]✓ Test notification sent successfully![/green]")
        else:
            error = result.get("error", "unknown error")
            console.print(f"[red]✗ Notification failed: {error}[/red]")
    except FileNotFoundError:
        console.print("[yellow]⚠ agentboxd socket not found - start with 'agentbox service start'[/yellow]")
    except ConnectionRefusedError:
        console.print("[yellow]⚠ agentboxd not accepting connections - restart with 'agentbox service restart'[/yellow]")
    except Exception as e:
        console.print(f"[red]✗ Failed to send notification: {e}[/red]")


@project.command(options_metavar="")
def reconfigure():
    """Interactively reconfigure agent and project settings.

    Walks through common configuration options for Claude configs
    and project settings (.agentbox/config.yml).
    """
    project_dir = resolve_project_dir()
    agentbox_dir = get_agentbox_dir(project_dir)

    if not agentbox_dir.exists():
        console.print("[red]Error: .agentbox/ not found. Run 'agentbox init' first.[/red]")
        sys.exit(1)

    console.print(BANNER, highlight=False, markup=False)
    console.print("[bold cyan]Agentbox Configuration[/bold cyan]")
    console.print(f"[dim]Project: {project_dir}[/dim]\n")

    # Load current configs (project-level config templates)
    # These are copied to ~/.claude/ at container startup
    config_dir = agentbox_dir / "config" / "claude"
    config_dir.mkdir(parents=True, exist_ok=True)

    claude_config_path = config_dir / "settings.json"
    claude_super_path = config_dir / "settings-super.json"

    claude_config = {}
    claude_super = {}

    if claude_config_path.exists():
        claude_config = json.loads(claude_config_path.read_text())
    if claude_super_path.exists():
        claude_super = json.loads(claude_super_path.read_text())

    # Load project config
    config = ProjectConfig(project_dir)

    # Track changes
    changes_made = False
    project_config_changed = False

    # === MIGRATIONS ===
    from agentbox.migrations import MigrationRunner

    if config.exists():
        runner = MigrationRunner(
            raw_config=config.config,
            project_dir=project_dir,
            interactive=True,
            auto_migrate=False,
        )
        results = runner.check_all()
        applicable = [r for r in results if r.applicable]

        if applicable:
            console.print("[bold]─── Config Migrations ───[/bold]")
            console.print(f"\n[yellow]Found {len(applicable)} migration(s) to apply:[/yellow]")
            for r in applicable:
                console.print(f"  • {r.description}")

            apply_migrations = _prompt_bool("\nApply these migrations now?", True)
            if apply_migrations:
                new_config = runner.run_migrations()
                config.config = new_config
                applied = [r for r in runner.results if r.applied]
                if applied:
                    console.print(f"[green]Applied {len(applied)} migration(s)[/green]")
                    project_config_changed = True
            console.print("")

    # === CLAUDE SETTINGS ===
    console.print("[bold]─── Claude Settings ───[/bold]")

    # Default model
    current_model = claude_config.get("model", "")
    model_choices = ["sonnet", "opus", "haiku", "(empty - use default)"]
    console.print(f"\n[dim]Current model: {current_model or '(not set)'}[/dim]")
    new_model = _prompt_choice("Default model", model_choices, current_model or "(empty - use default)")

    if new_model == "(empty - use default)":
        new_model = ""

    if new_model != current_model:
        if new_model:
            claude_config["model"] = new_model
            claude_super["model"] = new_model
        else:
            claude_config.pop("model", None)
            claude_super.pop("model", None)
        changes_made = True

    # Show thinking
    current_thinking = claude_config.get("display", {}).get("show_thinking", False)
    new_thinking = _prompt_bool(f"Show thinking? (current: {current_thinking})", current_thinking)
    if new_thinking != current_thinking:
        claude_config.setdefault("display", {})["show_thinking"] = new_thinking
        claude_super.setdefault("display", {})["show_thinking"] = new_thinking
        changes_made = True

    # Show tool results
    current_results = claude_config.get("display", {}).get("show_tool_results", True)
    new_results = _prompt_bool(f"Show tool results? (current: {current_results})", current_results)
    if new_results != current_results:
        claude_config.setdefault("display", {})["show_tool_results"] = new_results
        claude_super.setdefault("display", {})["show_tool_results"] = new_results
        changes_made = True

    # Notifications (super config only)
    has_hooks = "hooks" in claude_super
    new_hooks = _prompt_bool(f"Enable notifications for super agents? (current: {has_hooks})", has_hooks)
    if new_hooks != has_hooks:
        if new_hooks:
            # Add default hooks
            # Note: abox-notify automatically builds title from container/session
            claude_super["hooks"] = {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/usr/local/bin/abox-notify '' 'Task completed' 'normal' \"${AGENTBOX_CONTAINER}\" \"${AGENTBOX_SESSION_NAME}\""
                            }
                        ]
                    }
                ],
                "Notification": [
                    {
                        "matcher": "permission_prompt",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/usr/local/bin/abox-notify '' 'Needs permission' 'critical' \"${AGENTBOX_CONTAINER}\" \"${AGENTBOX_SESSION_NAME}\""
                            }
                        ]
                    }
                ]
            }
        else:
            claude_super.pop("hooks", None)
        changes_made = True

    # === NOTIFICATION SETTINGS ===
    console.print("\n[bold]─── Notification Settings ───[/bold]")

    # AI-enhanced notifications (task agents)
    current_task_agents = config.task_agents
    current_ai_enabled = current_task_agents.get("enabled", False)
    console.print(f"\n[dim]AI-enhanced notifications analyze terminal output to provide[/dim]")
    console.print(f"[dim]context-aware summaries (uses ~0.01$ per notification)[/dim]")
    new_ai_enabled = _prompt_bool(
        f"Enable AI-enhanced notifications? (current: {current_ai_enabled})",
        current_ai_enabled
    )

    ai_changed = False
    if new_ai_enabled != current_ai_enabled:
        ai_changed = True

    # AI model selection (only ask if enabled)
    current_ai_model = current_task_agents.get("model", "haiku")
    new_ai_model = current_ai_model
    if new_ai_enabled:
        model_choices = ["haiku", "sonnet"]
        console.print(f"\n[dim]Current AI model: {current_ai_model}[/dim]")
        new_ai_model = _prompt_choice("AI notification model", model_choices, current_ai_model)
        if new_ai_model != current_ai_model:
            ai_changed = True

    # Stall detection
    current_stall = config.stall_detection
    current_stall_enabled = current_stall.get("enabled", True)  # Default is enabled
    new_stall_enabled = _prompt_bool(
        f"Enable stall detection notifications? (current: {current_stall_enabled})",
        current_stall_enabled
    )

    stall_changed = False
    if new_stall_enabled != current_stall_enabled:
        stall_changed = True

    # Stall threshold (only ask if enabled)
    current_threshold = current_stall.get("threshold_seconds", 30)
    new_threshold = current_threshold
    if new_stall_enabled:
        threshold_choices = ["30", "60", "120", "300"]
        console.print(f"\n[dim]Current stall threshold: {current_threshold}s[/dim]")
        new_threshold_str = _prompt_choice("Stall threshold (seconds)", threshold_choices, str(current_threshold))
        new_threshold = int(new_threshold_str)
        if new_threshold != current_threshold:
            stall_changed = True

    # Test notification (only if service is running)
    from agentbox.host_config import get_config as get_host_config
    host_config = get_host_config()
    if host_config.socket_path.exists():
        test_notif = _prompt_bool("Send a test notification?", False)
        if test_notif:
            _send_test_notification(project_dir.name)
    else:
        console.print(f"\n[dim]Notifications require 'agentbox service start' (optional)[/dim]")

    # === SSH SETTINGS ===
    console.print("\n[bold]─── SSH Settings ───[/bold]")

    current_ssh_mode = config.ssh_mode
    ssh_modes = ["keys", "mount", "config", "none"]
    console.print(f"\n[dim]Current SSH mode: {current_ssh_mode}[/dim]")
    console.print("[dim]  keys: Copy SSH keys into container[/dim]")
    console.print("[dim]  mount: Bind mount ~/.ssh directly[/dim]")
    console.print("[dim]  config: Copy only config (use with forward_agent)[/dim]")
    console.print("[dim]  none: No SSH setup[/dim]")
    new_ssh_mode = _prompt_choice("SSH mode", ssh_modes, current_ssh_mode)

    ssh_changed = False
    if new_ssh_mode != current_ssh_mode:
        ssh_changed = True

    current_forwarding = config.ssh_forward_agent
    new_forwarding = _prompt_bool(f"Forward SSH agent? (current: {current_forwarding})", current_forwarding)
    if new_forwarding != current_forwarding:
        ssh_changed = True

    # === DOCKER SETTINGS ===
    console.print("\n[bold]─── Docker Settings ───[/bold]")

    # Check current docker status
    current_docker_enabled = config.docker_enabled
    console.print(f"\n[dim]Docker socket access allows the container to run Docker commands.[/dim]")
    console.print(f"[dim]Current: {'enabled' if current_docker_enabled else 'disabled'}[/dim]")
    new_docker_enabled = _prompt_bool(
        f"Enable Docker socket access? (current: {current_docker_enabled})",
        current_docker_enabled
    )

    docker_changed = False
    if new_docker_enabled != current_docker_enabled:
        docker_changed = True

    # === CREDENTIALS SETTINGS ===
    console.print("\n[bold]─── CLI Credentials ───[/bold]")

    # GitHub CLI (gh)
    current_gh_enabled = config.gh_enabled
    console.print(f"\n[dim]Mount GitHub CLI (gh) credentials from ~/.config/gh[/dim]")
    console.print(f"[dim]Allows 'gh' commands in container to use your GitHub auth.[/dim]")
    new_gh_enabled = _prompt_bool(
        f"Enable GitHub CLI credentials? (current: {current_gh_enabled})",
        current_gh_enabled
    )

    # GitLab CLI (glab)
    current_glab_enabled = config.glab_enabled
    console.print(f"\n[dim]Mount GitLab CLI (glab) credentials from ~/.config/glab-cli[/dim]")
    console.print(f"[dim]Allows 'glab' commands in container to use your GitLab auth.[/dim]")
    new_glab_enabled = _prompt_bool(
        f"Enable GitLab CLI credentials? (current: {current_glab_enabled})",
        current_glab_enabled
    )

    credentials_changed = False
    if new_gh_enabled != current_gh_enabled or new_glab_enabled != current_glab_enabled:
        credentials_changed = True

    # === SAVE CHANGES ===
    if changes_made:
        console.print("\n[bold]─── Saving Claude configs ───[/bold]")
        claude_config_path.write_text(json.dumps(claude_config, indent=2) + "\n")
        console.print(f"  [green]✓[/green] {claude_config_path.relative_to(project_dir)}")
        claude_super_path.write_text(json.dumps(claude_super, indent=2) + "\n")
        console.print(f"  [green]✓[/green] {claude_super_path.relative_to(project_dir)}")

    if ssh_changed or stall_changed or ai_changed or docker_changed or credentials_changed or project_config_changed:
        console.print("\n[bold]─── Saving project config ───[/bold]")
        if ssh_changed:
            config.ssh_mode = new_ssh_mode
            config.ssh_forward_agent = new_forwarding
        if stall_changed:
            config.stall_detection = {
                "enabled": new_stall_enabled,
                "threshold_seconds": new_threshold,
            }
        if ai_changed:
            config.task_agents = {
                "enabled": new_ai_enabled,
                "agent": "claude",
                "model": new_ai_model,
            }
        if docker_changed:
            config.docker_enabled = new_docker_enabled
        if credentials_changed:
            config.gh_enabled = new_gh_enabled
            config.glab_enabled = new_glab_enabled
        config.save()
        console.print(f"  [green]✓[/green] .agentbox/config.yml")

    if not changes_made and not ssh_changed and not stall_changed and not ai_changed and not docker_changed and not credentials_changed and not project_config_changed:
        console.print("\n[dim]No changes made.[/dim]")
    else:
        console.print("\n[green]✓ Configuration updated[/green]")
        console.print("[yellow]Note: Restart container for changes to take effect[/yellow]")


@project.command(options_metavar="")
def setup():
    """Initialize and configure agentbox for this project.

    Runs 'init' to create .agentbox/ directory, then 'reconfigure'
    to interactively set up common options.
    """
    ctx = click.get_current_context()
    ctx.invoke(init)
    console.print()
    ctx.invoke(reconfigure)


@project.command(options_metavar="")
@handle_errors
def start():
    """Start container for current project."""
    pctx = _get_project_context()

    # Block if config needs migration
    if not _require_config_migrated(pctx.project_dir):
        raise SystemExit(1)

    # Sync MCP servers from library before creating container
    if pctx.agentbox_dir.exists():
        console.print("[blue]Syncing MCP servers from library...[/blue]")
        _sync_library_mcps(pctx.agentbox_dir, quiet=True)

    container = pctx.manager.create_container(
        project_name=pctx.project_name,
        project_dir=pctx.project_dir,
    )

    # Apply config (packages) after container is created
    config = ProjectConfig(pctx.project_dir)
    if config.exists():
        config.rebuild(pctx.manager, container.name)

    # Wait for container initialization to complete
    if not wait_for_container_ready(pctx.manager, container.name, timeout_s=90.0):
        console.print("[yellow]Warning: Container may still be initializing[/yellow]")
        console.print(f"  Check logs: docker logs {container.name}")

    console.print(f"\n[green]Container started: {container.name}[/green]")
    console.print("\n[blue]Next steps:[/blue]")
    console.print("  agentbox shell    - Enter interactive shell")
    console.print("  agentbox claude   - Run Claude Code")
    console.print("  agentbox codex    - Run Codex")
    console.print("  agentbox info     - Get container details")


@project.command(options_metavar="")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
@handle_errors
def stop(project_name: Optional[str]):
    """Stop the project container.

    If no project name is provided, stops the container for the current directory.
    """
    pctx = _get_project_context(project=project_name)
    pctx.manager.stop_container(pctx.container_name)


@project.command(options_metavar="")
@click.argument("show_all", required=False)
@handle_errors
def list(show_all: Optional[str]):
    """List all agentbox containers.

    Pass 'all' as argument to show stopped containers too.

    Examples:
        abox project list      # Running only
        abox project list all  # All containers
    """
    manager = ContainerManager()
    all_containers = show_all == "all"
    manager.print_containers_table(all_containers=all_containers)


@project.command(options_metavar="")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
@handle_errors
def shell(project_name: Optional[str]):
    """Open interactive shell in container.

    If no project name is provided, opens shell in the current project's container.
    """
    from agentbox.cli.helpers import _run_agent_command

    pctx = _get_project_context(project=project_name)
    _require_container_running(pctx.manager, pctx.container_name)
    _warn_if_base_outdated(pctx.manager, pctx.container_name, pctx.project_dir)

    console.print(f"[green]Opening shell in {pctx.container_name}...[/green]")
    _run_agent_command(
        pctx.manager,
        project_name,
        tuple(),
        "/bin/bash",
        label="Shell",
        reuse_tmux_session=True,
        session_key="shell",
    )


@project.command(options_metavar="")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
@click.argument("session", required=False, shell_complete=_complete_connect_session)
@handle_errors
def connect(project_name: Optional[str], session: Optional[str]):
    """Connect to container with interactive shell or session.

    Quick access for SSH workflows - enter a container and optionally attach
    to a specific agent session.

    Examples:
        abox connect                    # Connect to current project
        abox connect my-project         # Connect to specific project
        abox connect my-project claude  # Connect and attach to claude session
    """
    pctx = _get_project_context(project=project_name)
    _require_container_running(pctx.manager, pctx.container_name)
    _warn_if_base_outdated(pctx.manager, pctx.container_name, pctx.project_dir)

    if not pctx.manager.wait_for_user(pctx.container_name, "abox", timeout_s=10.0):
        raise click.ClickException("Container user not ready")

    if not wait_for_container_ready(pctx.manager, pctx.container_name, timeout_s=90.0):
        raise click.ClickException(
            f"Container not ready. Check logs: docker logs {pctx.container_name}"
        )

    if session:
        console.print(f"[green]Attaching to {session} in {pctx.container_name}...[/green]")
        _attach_tmux_session(pctx.manager, pctx.container_name, session)

    # Check for existing sessions and attach to first one, or start shell
    sessions = _get_tmux_sessions(pctx.manager, pctx.container_name)
    if sessions:
        first_session = sessions[0]["name"]
        console.print(f"[green]Attaching to existing session '{first_session}' in {pctx.container_name}...[/green]")
        console.print("[dim]Tip: Use 'agentbox session list' to see all sessions[/dim]")
        _attach_tmux_session(pctx.manager, pctx.container_name, first_session)

    # No sessions found - start interactive shell
    console.print(f"[green]Connecting to {pctx.container_name}...[/green]")
    console.print("[dim]No tmux sessions found. Starting shell.[/dim]")
    os.execvp("docker", [
        "docker", "exec", "-it",
        "-u", "abox",
        "-w", "/workspace",
        pctx.container_name,
        "/bin/bash"
    ])


@project.command(options_metavar="")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
@handle_errors
def info(project_name: Optional[str]):
    """Show container and project configuration.

    Displays container status, network info, active sessions, and the full
    project configuration including SSH, Docker, ports, MCP servers, and more.

    If no project name is provided, shows info for the current project.
    """
    pctx = _get_project_context(project=project_name)

    if not pctx.manager.container_exists(pctx.container_name):
        raise click.ClickException(f"Container {pctx.container_name} not found")

    _warn_if_base_outdated(pctx.manager, pctx.container_name, pctx.project_dir)

    container = pctx.manager.client.containers.get(pctx.container_name)
    networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})

    # Container info
    console.print(f"\n[bold]Container[/bold]")
    console.print(f"  Name:   {pctx.container_name}")
    console.print(f"  Status: {container.status}")

    for network_name, network_info in networks.items():
        ip_address = network_info.get("IPAddress", "")
        if ip_address:
            console.print(f"  IP:     {ip_address}")
            console.print(f"  Network: {network_name}")
            break

    # Show sessions if running
    if pctx.manager.is_running(pctx.container_name):
        sessions = _get_tmux_sessions(pctx.manager, pctx.container_name)
        if sessions:
            console.print(f"\n[bold]Sessions[/bold]")
            for sess in sessions:
                status = "[green]attached[/green]" if sess.get("attached") else "[dim]detached[/dim]"
                console.print(f"  - {sess['name']} ({status})")

    # Load project config
    config = ProjectConfig(pctx.project_dir)
    if not config.exists():
        console.print(f"\n[dim]No config file found at {pctx.project_dir}/.agentbox/config.yml[/dim]")
        return

    # SSH configuration
    console.print(f"\n[bold]SSH[/bold]")
    ssh_mode = config.ssh_mode
    forward_agent = config.ssh_forward_agent
    if ssh_mode == "none":
        console.print("  Mode: [dim]disabled[/dim]")
    else:
        console.print(f"  Mode: {ssh_mode}")
        console.print(f"  Agent forwarding: {'[green]enabled[/green]' if forward_agent else '[dim]disabled[/dim]'}")

    # Docker configuration
    console.print(f"\n[bold]Docker[/bold]")
    docker_enabled = config.docker_enabled
    console.print(f"  Socket: {'[green]enabled[/green]' if docker_enabled else '[dim]disabled[/dim]'}")

    # Port forwarding
    ports_config = config.ports
    forwarded = ports_config.get("forward", [])
    exposed = ports_config.get("expose", [])
    if forwarded or exposed:
        console.print(f"\n[bold]Ports[/bold]")
        if forwarded:
            port_strs = [str(p) if isinstance(p, int) else f"{p.get('host', '?')}:{p.get('container', '?')}" for p in forwarded]
            console.print(f"  Forward: {', '.join(port_strs)}")
        if exposed:
            console.print(f"  Expose: {', '.join(str(p) for p in exposed)}")

    # MCP servers
    mcp_servers = config.mcp_servers
    if mcp_servers:
        console.print(f"\n[bold]MCP Servers[/bold]")
        for mcp in mcp_servers:
            console.print(f"  - {mcp}")

    # Skills
    skills = config.skills
    if skills:
        console.print(f"\n[bold]Skills[/bold]")
        for skill in skills:
            console.print(f"  - {skill}")

    # Workspace mounts
    workspaces = config.workspaces
    if workspaces:
        console.print(f"\n[bold]Workspace Mounts[/bold]")
        for ws in workspaces:
            if isinstance(ws, dict):
                console.print(f"  - {ws.get('host', '?')} → {ws.get('container', '?')}")
            else:
                console.print(f"  - {ws}")

    # System packages
    packages = config.system_packages
    if packages:
        console.print(f"\n[bold]System Packages[/bold]")
        console.print(f"  {', '.join(packages)}")


@project.command(options_metavar="")
@click.argument("project_name", required=False, shell_complete=_complete_project_name)
@click.argument("force_remove", required=False)
@handle_errors
def remove(project_name: Optional[str], force_remove: Optional[str]):
    """Remove the project container.

    Stops the container gracefully if it's running, then removes it.
    Pass 'force' to kill immediately without graceful shutdown.

    Examples:
        abox project remove        # Stop (if running) and remove container
        abox project remove force  # Force kill and remove immediately
    """
    pctx = _get_project_context(project=project_name)
    force = force_remove == "force"
    pctx.manager.remove_container(pctx.container_name, force=force)


@project.command(options_metavar="")
@handle_errors
def cleanup():
    """Remove all stopped agentbox containers."""
    manager = ContainerManager()
    manager.cleanup_stopped()


@project.command(name="rebase", options_metavar="")
@click.argument("scope", required=False)
@handle_errors
def rebase(scope: Optional[str]):
    """Rebase project container to the current base image.

    Recreates the container from scratch using the latest agentbox-base:latest.
    Use this after running 'abox rebuild' to update the base image.

    Pass 'all' as argument to rebase all existing containers at once.

    Examples:
        abox rebase       # Rebase current project
        abox rebase all   # Rebase all containers
    """
    manager = ContainerManager()

    if scope == "all":
        _rebase_all_containers(manager)
        return

    # Single project rebase
    pctx = _get_project_context()

    # Block if config needs migration
    if not _require_config_migrated(pctx.project_dir):
        raise SystemExit(1)

    # Warn if agents are running
    if not _warn_if_agents_running(pctx.manager, pctx.container_name, "rebase"):
        console.print("[yellow]Rebase cancelled[/yellow]")
        return

    # Check for uncommitted work in worktrees
    worktrees_with_changes = _check_worktree_uncommitted_changes(pctx.manager, pctx.container_name)
    if worktrees_with_changes:
        console.print("\n[red bold]Warning: Uncommitted changes in worktrees![/red bold]")
        console.print("[yellow]Rebasing will destroy these changes:[/yellow]\n")
        for wt in worktrees_with_changes:
            console.print(f"  [cyan]{wt['branch']}[/cyan] - {wt['changes']} uncommitted file(s)")
            console.print(f"    [dim]{wt['path']}[/dim]")
        console.print("")
        if not click.confirm("Continue with rebase? (uncommitted changes will be lost)"):
            console.print("[yellow]Rebase cancelled[/yellow]")
            return

    # Reset terminal before removing to disable mouse mode from any attached sessions
    if pctx.manager.container_exists(pctx.container_name):
        reset_terminal()

    # Use unified rebuild path
    _rebuild_container(pctx.manager, pctx.project_name, pctx.project_dir, pctx.container_name)

    console.print(f"\n[green]✓ Container rebased: {pctx.container_name}[/green]")
    console.print("\n[blue]Next steps:[/blue]")
    console.print("  agentbox shell    - Enter interactive shell")
    console.print("  agentbox claude   - Run Claude Code")
    console.print("  agentbox codex    - Run Codex")


def _rebase_all_containers(manager: ContainerManager) -> None:
    """Rebase all existing agentbox containers to the current base image."""
    containers = manager.list_containers(all_containers=True)

    if not containers:
        console.print("[yellow]No agentbox containers found[/yellow]")
        return

    console.print(f"[bold]Found {len(containers)} container(s) to rebase:[/bold]\n")
    for c in containers:
        status_color = "green" if c["status"] == "running" else "dim"
        console.print(f"  [{status_color}]{c['name']}[/{status_color}] ({c['status']})")
        if c.get("project_path"):
            console.print(f"    [dim]{c['project_path']}[/dim]")

    console.print("")
    if not click.confirm(f"Rebase all {len(containers)} container(s)?"):
        console.print("[yellow]Rebase cancelled[/yellow]")
        return

    # Check for running containers with agents
    running_with_agents = []
    for c in containers:
        if c["status"] == "running":
            from agentbox.cli.helpers import _get_tmux_sessions
            sessions = _get_tmux_sessions(manager, c["name"])
            if sessions:
                running_with_agents.append((c, sessions))

    if running_with_agents:
        console.print("\n[red bold]Warning: Running containers with active sessions:[/red bold]")
        for c, sessions in running_with_agents:
            session_names = ", ".join(s["name"] for s in sessions)
            console.print(f"  [cyan]{c['name']}[/cyan]: {session_names}")
        console.print("")
        if not click.confirm("Continue? (all sessions will be terminated)"):
            console.print("[yellow]Rebase cancelled[/yellow]")
            return

    # Check for uncommitted worktree changes in all containers
    containers_with_changes = []
    for c in containers:
        if c["status"] == "running":
            changes = _check_worktree_uncommitted_changes(manager, c["name"])
            if changes:
                containers_with_changes.append((c, changes))

    if containers_with_changes:
        console.print("\n[red bold]Warning: Uncommitted changes in worktrees![/red bold]")
        for c, changes in containers_with_changes:
            console.print(f"\n  [cyan]{c['name']}[/cyan]:")
            for wt in changes:
                console.print(f"    {wt['branch']} - {wt['changes']} uncommitted file(s)")
        console.print("")
        if not click.confirm("Continue? (uncommitted changes will be lost)"):
            console.print("[yellow]Rebase cancelled[/yellow]")
            return

    # Reset terminal before starting
    reset_terminal()

    # Rebase each container
    console.print("\n[bold]Rebasing containers...[/bold]\n")
    success_count = 0
    failed = []

    for c in containers:
        container_name = c["name"]
        project_name = c["project"]
        project_path = c.get("project_path")

        if not project_path or not Path(project_path).exists():
            console.print(f"[yellow]⚠ Skipping {container_name}: project path not found[/yellow]")
            failed.append((container_name, "project path not found"))
            continue

        project_dir = Path(project_path)
        console.print(f"[blue]Rebasing {container_name}...[/blue]")

        try:
            _rebuild_container(manager, project_name, project_dir, container_name, quiet=True)
            console.print(f"  [green]✓ {container_name}[/green]")
            success_count += 1
        except Exception as e:
            console.print(f"  [red]✗ {container_name}: {e}[/red]")
            failed.append((container_name, str(e)))

    # Summary
    console.print(f"\n[bold]Rebase complete:[/bold]")
    console.print(f"  [green]✓ {success_count} succeeded[/green]")
    if failed:
        console.print(f"  [red]✗ {len(failed)} failed[/red]")
        for name, error in failed:
            console.print(f"    - {name}: {error}")


@project.command(name="migrate")
@click.option("--dry-run", is_flag=True, help="Show what would be migrated")
@click.option("--auto", is_flag=True, help="Apply all without prompting")
@handle_errors
def config_migrate(dry_run: bool, auto: bool):
    """Migrate config to latest format.

    Detects legacy configuration patterns and updates them to the
    current format. Run with --dry-run to preview changes.

    Examples:
        abox project migrate           # Interactive migration
        abox project migrate --dry-run # Preview changes
        abox project migrate --auto    # Auto-apply all
    """
    from agentbox.migrations import MigrationRunner

    project_dir = resolve_project_dir()
    config = ProjectConfig(project_dir)

    if not config.exists():
        raise click.ClickException("No .agentbox/config.yml found")

    runner = MigrationRunner(
        raw_config=config.config,
        project_dir=project_dir,
        interactive=not auto,
        auto_migrate=auto,
    )

    results = runner.check_all()

    if not any(r.applicable for r in results):
        console.print("[green]Config is up to date![/green]")
        return

    if dry_run:
        from agentbox.migrations.base import MigrationAction

        console.print("[bold]Pending migrations:[/bold]")
        for r in results:
            if r.applicable:
                if r.action == MigrationAction.AUTO:
                    status = "[green]auto-apply[/green]"
                elif r.action == MigrationAction.PROMPT:
                    status = "[yellow]will prompt[/yellow]" if not auto else "[green]auto-apply[/green]"
                else:  # SUGGEST
                    status = "[dim]suggestion only[/dim]"
                console.print(f"  - {r.description} ({status})")
        return

    new_config = runner.run_migrations()
    config.config = new_config
    config.save(quiet=True)

    applied = [r for r in runner.results if r.applied]
    skipped = [r for r in runner.results if r.skipped]
    errored = [r for r in runner.results if r.error]

    if applied:
        console.print(f"[green]Applied {len(applied)} migration(s):[/green]")
        for r in applied:
            console.print(f"  [green]✓[/green] {r.migration_id}")

    if skipped:
        console.print(f"[yellow]Skipped {len(skipped)} migration(s):[/yellow]")
        for r in skipped:
            reason = r.skip_reason or "unknown"
            console.print(f"  [yellow]○[/yellow] {r.migration_id} ({reason})")

    if errored:
        console.print(f"[red]Failed {len(errored)} migration(s):[/red]")
        for r in errored:
            console.print(f"  [red]✗[/red] {r.migration_id}: {r.error}")
