# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Migration helpers for agentbox → boxctl rename.

This module provides functions to migrate from the old 'agentbox' naming
to the new 'boxctl' naming.
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console

console = Console()


def check_legacy_project_dir(project_dir: Path) -> bool:
    """Check if a project has legacy .agentbox directory.

    Args:
        project_dir: Project directory to check

    Returns:
        True if .agentbox exists but .boxctl does not
    """
    legacy_dir = project_dir / ".agentbox"
    new_dir = project_dir / ".boxctl"
    return legacy_dir.exists() and not new_dir.exists()


def check_legacy_config_file(project_dir: Path) -> bool:
    """Check if a project has legacy .agentbox.yml config file in root.

    Args:
        project_dir: Project directory to check

    Returns:
        True if .agentbox.yml exists in root (should be .boxctl/config.yml)
    """
    legacy_file = project_dir / ".agentbox.yml"
    return legacy_file.exists()


def check_misplaced_config_file(project_dir: Path) -> bool:
    """Check if a project has misplaced .boxctl.yml in root.

    Args:
        project_dir: Project directory to check

    Returns:
        True if .boxctl.yml exists in root (should be .boxctl/config.yml)
    """
    misplaced_file = project_dir / ".boxctl.yml"
    return misplaced_file.exists()


def migrate_config_file(project_dir: Path, quiet: bool = False) -> bool:
    """Migrate .agentbox.yml or .boxctl.yml to .boxctl/config.yml.

    The config file should be inside .boxctl/ directory, not in project root.

    Args:
        project_dir: Project directory to migrate
        quiet: If True, don't print messages

    Returns:
        True if migration was performed
    """
    legacy_file = project_dir / ".agentbox.yml"
    misplaced_file = project_dir / ".boxctl.yml"
    boxctl_dir = project_dir / ".boxctl"
    target_file = boxctl_dir / "config.yml"

    # Determine which source file to migrate
    source_file = None
    source_name = None
    if legacy_file.exists():
        source_file = legacy_file
        source_name = ".agentbox.yml"
    elif misplaced_file.exists():
        source_file = misplaced_file
        source_name = ".boxctl.yml"
    else:
        return False

    # Ensure .boxctl directory exists
    if not boxctl_dir.exists():
        boxctl_dir.mkdir(parents=True)

    if target_file.exists():
        if not quiet:
            console.print(f"[yellow]Both {source_name} and .boxctl/config.yml exist[/yellow]")
            console.print(
                f"[yellow]Please resolve manually (delete {source_name} if not needed)[/yellow]"
            )
        return False

    try:
        source_file.rename(target_file)
        if not quiet:
            console.print(f"[green]Migrated {source_name} → .boxctl/config.yml[/green]")
        return True
    except Exception as e:
        if not quiet:
            console.print(f"[red]Failed to migrate config file: {e}[/red]")
        return False


def cleanup_legacy_project_files(project_dir: Path, dry_run: bool = False) -> List[str]:
    """Clean up legacy/misplaced files in project.

    This handles:
    - .claude/ in root → remove (runtime data, belongs in container home)
    - .boxctl/{agent}/ → remove (use library defaults, or create .boxctl/config/{agent}/ if needed)
    - agentbox.config.json → remove (obsolete)
    - .mcp.json in project root → remove (should be in home dir)

    Args:
        project_dir: Project directory to clean up
        dry_run: If True, only report what would be done

    Returns:
        List of actions taken (or would be taken if dry_run)
    """
    import shutil

    actions = []
    boxctl_dir = project_dir / ".boxctl"

    if not boxctl_dir.exists():
        return actions

    # 1. Remove .claude/ from project root entirely
    # Commands are now handled as skills at container startup (copied to ~/.claude/skills/)
    # No need to keep anything in project's .claude/ directory
    legacy_claude = project_dir / ".claude"
    if legacy_claude.exists() and legacy_claude.is_dir():
        if dry_run:
            actions.append(f"Would remove .claude/ (commands now handled as skills)")
        else:
            try:
                shutil.rmtree(legacy_claude)
                actions.append(f"Removed .claude/ (commands now handled as skills)")
            except Exception as e:
                actions.append(f"[red]Failed to remove .claude/: {e}[/red]")

    # 1b. Remove misplaced agent folders directly in .boxctl/
    # These shouldn't exist - agent configs come from library defaults
    # If user needs custom settings, they can create .boxctl/config/{agent}/ manually
    for agent in ["claude", "gemini", "codex", "qwen"]:
        misplaced_agent = boxctl_dir / agent
        if misplaced_agent.exists() and misplaced_agent.is_dir():
            if dry_run:
                actions.append(f"Would remove .boxctl/{agent}/ (use library defaults)")
            else:
                try:
                    shutil.rmtree(misplaced_agent)
                    actions.append(f"Removed .boxctl/{agent}/ (use library defaults instead)")
                except Exception as e:
                    actions.append(f"[red]Failed to remove .boxctl/{agent}/: {e}[/red]")

    # 2. Remove obsolete agentbox.config.json
    obsolete_config = project_dir / "agentbox.config.json"
    if obsolete_config.exists():
        if dry_run:
            actions.append(f"Would remove agentbox.config.json (obsolete)")
        else:
            try:
                obsolete_config.unlink()
                actions.append(f"Removed agentbox.config.json (obsolete)")
            except Exception as e:
                actions.append(f"[red]Failed to remove agentbox.config.json: {e}[/red]")

    # 3. Remove .mcp.json from project root (should be in home dir only)
    workspace_mcp = project_dir / ".mcp.json"
    if workspace_mcp.exists():
        if dry_run:
            actions.append(f"Would remove .mcp.json from project root (belongs in home dir)")
        else:
            try:
                workspace_mcp.unlink()
                actions.append(f"Removed .mcp.json from project root")
            except Exception as e:
                actions.append(f"[red]Failed to remove .mcp.json: {e}[/red]")

    # 4. Remove obsolete files inside .boxctl/
    # These are legacy formats no longer used
    obsolete_boxctl_files = [
        ("config.json", "obsolete - use config.yml"),
        ("volumes.json", "no longer used"),
        ("codex.toml", "legacy codex config"),
        ("claude.mcp.json", "legacy MCP config"),
    ]

    for filename, reason in obsolete_boxctl_files:
        obsolete_file = boxctl_dir / filename
        if obsolete_file.exists():
            if dry_run:
                actions.append(f"Would remove .boxctl/{filename} ({reason})")
            else:
                try:
                    obsolete_file.unlink()
                    actions.append(f"Removed .boxctl/{filename} ({reason})")
                except Exception as e:
                    actions.append(f"[red]Failed to remove .boxctl/{filename}: {e}[/red]")

    # 5. Remove obsolete directories inside .boxctl/
    obsolete_boxctl_dirs = [
        ("state", "no longer used"),
    ]

    for dirname, reason in obsolete_boxctl_dirs:
        obsolete_dir = boxctl_dir / dirname
        if obsolete_dir.exists() and obsolete_dir.is_dir():
            if dry_run:
                actions.append(f"Would remove .boxctl/{dirname}/ ({reason})")
            else:
                try:
                    shutil.rmtree(obsolete_dir)
                    actions.append(f"Removed .boxctl/{dirname}/ ({reason})")
                except Exception as e:
                    actions.append(f"[red]Failed to remove .boxctl/{dirname}/: {e}[/red]")

    return actions


def _migrate_mcp_servers(boxctl_dir: Path) -> List[str]:
    """Migrate MCP server directories and configs from agentbox to boxctl naming.

    Args:
        boxctl_dir: The .boxctl directory path

    Returns:
        List of migrated items
    """
    import json
    import shutil

    migrated = []
    mcp_dir = boxctl_dir / "mcp"

    if not mcp_dir.exists():
        return migrated

    # Rename MCP server directories
    renames = [
        ("agentbox-analyst", "boxctl-analyst"),
        ("agentbox-notify", "boxctl-notify"),
    ]

    for old_name, new_name in renames:
        old_path = mcp_dir / old_name
        new_path = mcp_dir / new_name
        if old_path.exists():
            if new_path.exists():
                # New already exists, remove old
                shutil.rmtree(old_path)
                migrated.append(f"removed {old_name} (duplicate)")
            else:
                old_path.rename(new_path)
                migrated.append(f"{old_name} → {new_name}")

    # Update mcp.json
    mcp_json = boxctl_dir / "mcp.json"
    if mcp_json.exists():
        try:
            content = mcp_json.read_text()
            original = content
            # Replace agentbox-analyst with boxctl-analyst
            content = content.replace("agentbox-analyst", "boxctl-analyst")
            content = content.replace("agentbox-notify", "boxctl-notify")
            # Replace .agentbox/ paths with .boxctl/
            content = content.replace(".agentbox/", ".boxctl/")
            if content != original:
                mcp_json.write_text(content)
                migrated.append("mcp.json")
        except Exception:
            pass

    # Update mcp-meta.json
    mcp_meta = boxctl_dir / "mcp-meta.json"
    if mcp_meta.exists():
        try:
            content = mcp_meta.read_text()
            original = content
            content = content.replace("agentbox-analyst", "boxctl-analyst")
            content = content.replace("agentbox-notify", "boxctl-notify")
            content = content.replace(".agentbox/", ".boxctl/")
            if content != original:
                mcp_meta.write_text(content)
                migrated.append("mcp-meta.json")
        except Exception:
            pass

    # Remove root .mcp.json if it exists (Claude auto-discovers it, causing duplicates)
    # All MCP config should be in ~/.mcp.json only
    project_dir = boxctl_dir.parent
    root_mcp_json = project_dir / ".mcp.json"
    if root_mcp_json.exists():
        try:
            root_mcp_json.unlink()
            migrated.append(".mcp.json (removed - use ~/.mcp.json only)")
        except Exception:
            pass

    # Update peer agent settings files (gemini, qwen, etc.)
    for agent_dir in ["gemini", "qwen", "codex", "claude"]:
        settings_file = boxctl_dir / agent_dir / "settings.json"
        if settings_file.exists():
            try:
                content = settings_file.read_text()
                original = content
                content = content.replace("agentbox-analyst", "boxctl-analyst")
                content = content.replace("agentbox-notify", "boxctl-notify")
                content = content.replace(".agentbox/", ".boxctl/")
                if content != original:
                    settings_file.write_text(content)
                    migrated.append(f"{agent_dir}/settings.json")
            except Exception:
                pass

    return migrated


def _migrate_file_content(file_path: Path) -> bool:
    """Migrate content inside a file from agentbox to boxctl references.

    Args:
        file_path: Path to file to migrate

    Returns:
        True if content was changed
    """
    import re

    try:
        content = file_path.read_text()
        original = content

        # Replacements for file content (more aggressive than shell RC files)
        replacements = [
            # Directory references
            (r"\.agentbox/", ".boxctl/"),
            (r"\.agentbox\b", ".boxctl"),
            # Command references (but keep 'abox' as it's the short alias)
            (r"\bagentbox\b", "boxctl"),
            # Capitalized references
            (r"\bAgentbox\b", "Boxctl"),
            (r"\bAgentBox\b", "BoxCtl"),
            # Environment variables
            (r"\bAGENTBOX_", "BOXCTL_"),
        ]

        for pattern, replacement in replacements:
            content = re.sub(pattern, replacement, content)

        if content != original:
            file_path.write_text(content)
            return True
        return False
    except Exception:
        return False


def migrate_project_dir(project_dir: Path, quiet: bool = False) -> bool:
    """Migrate .agentbox to .boxctl in a project directory.

    Args:
        project_dir: Project directory to migrate
        quiet: If True, don't print messages

    Returns:
        True if migration was performed
    """
    legacy_dir = project_dir / ".agentbox"
    new_dir = project_dir / ".boxctl"

    if not legacy_dir.exists():
        return False

    if new_dir.exists():
        if not quiet:
            console.print(f"[yellow]Both .agentbox and .boxctl exist in {project_dir}[/yellow]")
            console.print("[yellow]Please resolve manually[/yellow]")
        return False

    try:
        legacy_dir.rename(new_dir)
        if not quiet:
            console.print(f"[green]Migrated .agentbox → .boxctl in {project_dir}[/green]")

        # Also migrate content inside key files
        files_to_migrate = [
            new_dir / "agents.md",
            new_dir / "superagents.md",
            new_dir / "config.yml",
        ]
        migrated_files = []
        for file_path in files_to_migrate:
            if file_path.exists() and _migrate_file_content(file_path):
                migrated_files.append(file_path.name)

        if migrated_files and not quiet:
            console.print(f"  [dim]Updated content in: {', '.join(migrated_files)}[/dim]")

        # Migrate MCP servers
        mcp_migrated = _migrate_mcp_servers(new_dir)
        if mcp_migrated and not quiet:
            console.print(f"  [dim]MCP migration: {', '.join(mcp_migrated)}[/dim]")

        return True
    except Exception as e:
        if not quiet:
            console.print(f"[red]Failed to migrate {project_dir}: {e}[/red]")
        return False


def auto_migrate_project_dir(project_dir: Optional[Path] = None) -> bool:
    """Auto-migrate project directory if legacy .agentbox exists.

    This is called automatically when boxctl commands run.

    Args:
        project_dir: Project directory (defaults to BOXCTL_PROJECT_DIR env var or cwd)

    Returns:
        True if migration was performed
    """
    if project_dir is None:
        # Use BOXCTL_PROJECT_DIR if set (wrapper script preserves original cwd there)
        project_dir_str = os.environ.get("BOXCTL_PROJECT_DIR")
        if project_dir_str:
            project_dir = Path(project_dir_str)
        else:
            project_dir = Path.cwd()

    migrated = False

    # Migrate .agentbox directory to .boxctl
    if check_legacy_project_dir(project_dir):
        migrated = migrate_project_dir(project_dir)

    # Migrate .agentbox.yml or misplaced .boxctl.yml to .boxctl/config.yml
    if check_legacy_config_file(project_dir) or check_misplaced_config_file(project_dir):
        if migrate_config_file(project_dir):
            migrated = True

    # Also check if .boxctl exists but MCP content still has old references
    # This catches cases where directory was renamed but content wasn't fully migrated
    boxctl_dir = project_dir / ".boxctl"
    if boxctl_dir.exists():
        mcp_migrated = _migrate_mcp_servers(boxctl_dir)
        if mcp_migrated:
            migrated = True

    return migrated


def check_legacy_global_config() -> Tuple[bool, List[str]]:
    """Check for legacy global config directories.

    Returns:
        Tuple of (has_legacy, list of legacy paths found)
    """
    home = Path.home()
    legacy_paths = []

    # Check ~/.config/agentbox
    legacy_config = home / ".config" / "agentbox"
    if legacy_config.exists():
        new_config = home / ".config" / "boxctl"
        if not new_config.exists():
            legacy_paths.append(str(legacy_config))

    # Check ~/.local/share/agentbox
    legacy_data = home / ".local" / "share" / "agentbox"
    if legacy_data.exists():
        new_data = home / ".local" / "share" / "boxctl"
        if not new_data.exists():
            legacy_paths.append(str(legacy_data))

    return bool(legacy_paths), legacy_paths


def migrate_global_config(dry_run: bool = False) -> List[Tuple[str, str, bool]]:
    """Migrate global config directories.

    Args:
        dry_run: If True, don't actually migrate, just report

    Returns:
        List of (old_path, new_path, success) tuples
    """
    home = Path.home()
    results = []

    migrations = [
        (home / ".config" / "agentbox", home / ".config" / "boxctl"),
        (home / ".local" / "share" / "agentbox", home / ".local" / "share" / "boxctl"),
    ]

    for old_path, new_path in migrations:
        if not old_path.exists():
            continue

        if new_path.exists():
            console.print(f"[yellow]Skipping {old_path} - {new_path} already exists[/yellow]")
            results.append((str(old_path), str(new_path), False))
            continue

        if dry_run:
            console.print(f"[blue]Would migrate:[/blue] {old_path} → {new_path}")
            results.append((str(old_path), str(new_path), True))
        else:
            try:
                old_path.rename(new_path)
                console.print(f"[green]Migrated:[/green] {old_path} → {new_path}")
                results.append((str(old_path), str(new_path), True))
            except Exception as e:
                console.print(f"[red]Failed to migrate {old_path}: {e}[/red]")
                results.append((str(old_path), str(new_path), False))

    return results


def check_legacy_containers() -> List[str]:
    """Check for legacy agentbox-* containers.

    Returns:
        List of legacy container names
    """
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=agentbox-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
            return containers
    except Exception:
        pass
    return []


def warn_legacy_containers() -> None:
    """Print warning about legacy containers if any exist."""
    containers = check_legacy_containers()
    if containers:
        console.print()
        console.print("[yellow]⚠ Found legacy agentbox containers:[/yellow]")
        for c in containers[:5]:  # Show first 5
            console.print(f"  [dim]{c}[/dim]")
        if len(containers) > 5:
            console.print(f"  [dim]... and {len(containers) - 5} more[/dim]")
        console.print()
        console.print("[yellow]Clean up with:[/yellow]")
        console.print('  docker rm $(docker ps -aq -f "name=agentbox-")')
        console.print()


def check_legacy_env_vars() -> List[str]:
    """Check for legacy AGENTBOX_* environment variables.

    Returns:
        List of legacy env var names that are set
    """
    legacy_vars = []
    for key in os.environ:
        if key.startswith("AGENTBOX_"):
            legacy_vars.append(key)
    return legacy_vars


def warn_legacy_env_vars() -> None:
    """Print warning about legacy env vars if any are set."""
    legacy_vars = check_legacy_env_vars()
    if legacy_vars:
        console.print()
        console.print("[yellow]⚠ Found legacy environment variables:[/yellow]")
        for var in legacy_vars:
            new_var = var.replace("AGENTBOX_", "BOXCTL_")
            console.print(f"  [dim]{var}[/dim] → [green]{new_var}[/green]")
        console.print()
        console.print("[yellow]Update your shell config to use BOXCTL_* instead[/yellow]")
        console.print()


def check_shell_rc_files() -> List[Tuple[str, List[int]]]:
    """Check shell RC files for legacy agentbox references.

    Returns:
        List of (file_path, line_numbers) tuples where agentbox was found
    """
    home = Path.home()

    # Common shell RC files to check
    rc_files = [
        home / ".bashrc",
        home / ".bash_profile",
        home / ".bash_aliases",
        home / ".profile",
        home / ".zshrc",
        home / ".zprofile",
    ]

    # Also check common config directories
    zsh_dir = home / ".zsh"
    if zsh_dir.is_dir():
        rc_files.extend(zsh_dir.glob("*.zsh"))

    bashrc_d = home / ".bashrc.d"
    if bashrc_d.is_dir():
        rc_files.extend(bashrc_d.glob("*.conf"))
        rc_files.extend(bashrc_d.glob("*.sh"))

    results = []

    for rc_file in rc_files:
        # Resolve symlinks to check actual file
        try:
            if rc_file.is_symlink():
                rc_file = rc_file.resolve()
            if not rc_file.is_file():
                continue
        except Exception:
            continue

        try:
            import re

            content = rc_file.read_text()
            lines_with_agentbox = []

            # Patterns that indicate migration is needed (not arbitrary paths)
            migration_patterns = [
                r"agentbox-completion\.(zsh|bash)",  # Completion filenames
                r"['\"]agentbox['\"]",  # Command in quotes
                r"\.agentbox\b",  # Config directory
                r"\bAGENTBOX_",  # Env var prefix
                r"#\s*AgentBox\b",  # Comment mentioning AgentBox
                r"\balias\s+\w+\s*=.*agentbox",  # Alias definitions
            ]

            for i, line in enumerate(content.splitlines(), 1):
                for pattern in migration_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        lines_with_agentbox.append(i)
                        break  # Only count line once

            if lines_with_agentbox:
                results.append((str(rc_file), lines_with_agentbox))
        except Exception:
            pass

    return results


def fix_shell_rc_files(dry_run: bool = False) -> List[Tuple[str, bool]]:
    """Fix shell RC files by replacing agentbox references with boxctl.

    Args:
        dry_run: If True, don't actually modify files, just report

    Returns:
        List of (file_path, success) tuples
    """
    import re

    rc_files = check_shell_rc_files()
    results = []

    # Replacement patterns (order matters - more specific first)
    replacements = [
        # Completion file names (not the directory path)
        (r"agentbox-completion\.zsh", "boxctl-completion.zsh"),
        (r"agentbox-completion\.bash", "boxctl-completion.bash"),
        # Command/alias references (in quotes)
        (r"='agentbox'", "='boxctl'"),
        (r'="agentbox"', '="boxctl"'),
        (r"= 'agentbox'", "= 'boxctl'"),
        (r'= "agentbox"', '= "boxctl"'),
        # Config directory references
        (r"\.agentbox/", ".boxctl/"),
        (r"\.agentbox\b", ".boxctl"),
        # Environment variable prefixes
        (r"\bAGENTBOX_", "BOXCTL_"),
        # Comments mentioning AgentBox (at start of comment, not in paths)
        (r"(#\s*)AgentBox(\s)", r"\1BoxCtl\2"),
        # "for agentbox" or "for boxctl" in comments (preserve space after)
        (r"(\bfor\s+)agentbox(\s)", r"\1boxctl\2"),
    ]

    for file_path, line_nums in rc_files:
        try:
            content = Path(file_path).read_text()
            original = content

            for pattern, replacement in replacements:
                content = re.sub(pattern, replacement, content)

            if content != original:
                if dry_run:
                    console.print(f"[blue]Would fix:[/blue] {file_path}")
                    results.append((file_path, True))
                else:
                    # Create backup
                    backup_path = Path(file_path).with_suffix(
                        Path(file_path).suffix + ".agentbox-backup"
                    )
                    if not backup_path.exists():
                        Path(file_path).rename(backup_path)
                        Path(file_path).write_text(content)
                        console.print(f"[green]Fixed:[/green] {file_path}")
                        console.print(f"  [dim]Backup: {backup_path}[/dim]")
                    else:
                        # Backup exists, write directly
                        Path(file_path).write_text(content)
                        console.print(f"[green]Fixed:[/green] {file_path}")
                    results.append((file_path, True))
            else:
                results.append((file_path, False))
        except Exception as e:
            console.print(f"[red]Failed to fix {file_path}: {e}[/red]")
            results.append((file_path, False))

    return results


def warn_shell_rc_files() -> None:
    """Print warning about shell RC files with legacy agentbox references."""
    rc_files = check_shell_rc_files()
    if rc_files:
        console.print()
        console.print("[yellow]⚠ Found agentbox references in shell config files:[/yellow]")
        for file_path, line_nums in rc_files:
            lines_str = ", ".join(str(n) for n in line_nums[:5])
            if len(line_nums) > 5:
                lines_str += f" (+{len(line_nums) - 5} more)"
            console.print(f"  [dim]{file_path}[/dim] (lines: {lines_str})")
        console.print()
        console.print("[dim]Run 'boxctl migrate --fix-shell-rc' to auto-fix[/dim]")
        console.print()


def get_boxctl_bin_dir() -> Optional[Path]:
    """Get the boxctl bin directory path.

    Returns:
        Path to bin directory, or None if not found
    """
    # Try to find via this file's location
    this_file = Path(__file__).resolve()
    # migrations/rename_migration.py -> boxctl/ -> project root -> bin/
    project_root = this_file.parent.parent.parent
    bin_dir = project_root / "bin"
    if bin_dir.exists() and (bin_dir / "boxctl").exists():
        return bin_dir
    return None


def check_path_setup() -> Tuple[bool, Optional[Path]]:
    """Check if boxctl bin directory is in PATH or shell config.

    Returns:
        Tuple of (is_setup, bin_dir_path)
    """
    bin_dir = get_boxctl_bin_dir()
    if bin_dir is None:
        return (False, None)

    # Check if bin_dir is in current PATH (not via poetry venv)
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if str(bin_dir) in path_dirs:
        return (True, bin_dir)

    # Check if it's configured in shell RC files
    home = Path.home()
    rc_files = [home / ".zshrc", home / ".bashrc", home / ".profile"]

    for rc_file in rc_files:
        if rc_file.exists():
            try:
                content = rc_file.read_text()
                # Check for PATH export containing our bin dir
                if str(bin_dir) in content and "PATH" in content:
                    return (True, bin_dir)
            except Exception:
                pass

    return (False, bin_dir)


def fix_path_setup(dry_run: bool = False) -> bool:
    """Add boxctl bin directory to shell PATH if missing.

    Args:
        dry_run: If True, don't actually modify files

    Returns:
        True if PATH was added or already set
    """
    is_setup, bin_dir = check_path_setup()
    if is_setup:
        console.print("[green]boxctl is already in PATH[/green]")
        return True

    if bin_dir is None:
        console.print("[red]Could not find boxctl bin directory[/red]")
        return False

    # Find the appropriate RC file
    home = Path.home()
    shell = os.environ.get("SHELL", "")

    if "zsh" in shell:
        rc_file = home / ".zshrc"
    else:
        rc_file = home / ".bashrc"

    if not rc_file.exists():
        console.print(f"[yellow]Shell config not found: {rc_file}[/yellow]")
        return False

    path_line = f'\n# boxctl PATH\nexport PATH="{bin_dir}:$PATH"\n'

    if dry_run:
        console.print(f"[blue]Would add to {rc_file}:[/blue]")
        console.print(f'  export PATH="{bin_dir}:$PATH"')
        return True

    # Check if already present
    content = rc_file.read_text()
    if str(bin_dir) in content and "PATH" in content:
        console.print(f"[green]PATH setup already in {rc_file}[/green]")
        return True

    # Append PATH setup
    with open(rc_file, "a") as f:
        f.write(path_line)

    console.print(f"[green]Added boxctl to PATH in {rc_file}[/green]")
    console.print("[yellow]Restart your shell or run: source " + str(rc_file) + "[/yellow]")
    return True


def warn_path_setup() -> None:
    """Print warning if boxctl is not in PATH."""
    is_setup, bin_dir = check_path_setup()
    if not is_setup and bin_dir:
        console.print()
        console.print("[yellow]⚠ boxctl bin directory not in PATH[/yellow]")
        console.print(f"  [dim]{bin_dir}[/dim]")
        console.print()
        console.print("[dim]Run 'boxctl migrate --fix-path' to auto-fix[/dim]")
        console.print()


def remove_legacy_containers(dry_run: bool = False, force: bool = False) -> Tuple[int, int]:
    """Stop and remove legacy agentbox-* containers.

    Args:
        dry_run: If True, don't actually remove, just report
        force: If True, force remove running containers

    Returns:
        Tuple of (stopped_count, removed_count)
    """
    import subprocess

    containers = check_legacy_containers()
    if not containers:
        return (0, 0)

    stopped = 0
    removed = 0

    for container in containers:
        if dry_run:
            console.print(f"[blue]Would remove:[/blue] {container}")
            removed += 1
            continue

        # Check if running
        try:
            result = subprocess.run(
                ["docker", "inspect", container, "--format", "{{.State.Running}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            is_running = result.stdout.strip() == "true"
        except Exception:
            is_running = False

        # Stop if running
        if is_running:
            console.print(f"[yellow]Stopping:[/yellow] {container}")
            try:
                subprocess.run(["docker", "stop", container], capture_output=True, timeout=30)
                stopped += 1
            except Exception as e:
                console.print(f"[red]Failed to stop {container}: {e}[/red]")
                if not force:
                    continue

        # Remove container
        console.print(f"[red]Removing:[/red] {container}")
        try:
            rm_args = ["docker", "rm", container]
            if force:
                rm_args.insert(2, "-f")
            subprocess.run(rm_args, capture_output=True, timeout=10)
            removed += 1
        except Exception as e:
            console.print(f"[red]Failed to remove {container}: {e}[/red]")

    return (stopped, removed)


def check_legacy_systemd_service() -> bool:
    """Check if legacy agentboxd.service exists.

    Returns:
        True if agentboxd.service exists
    """
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    legacy_service = systemd_dir / "agentboxd.service"
    return legacy_service.exists()


def get_legacy_systemd_service_path() -> Path:
    """Get path to legacy systemd service file."""
    return Path.home() / ".config" / "systemd" / "user" / "agentboxd.service"


def get_new_systemd_service_path() -> Path:
    """Get path to new systemd service file."""
    return Path.home() / ".config" / "systemd" / "user" / "boxctld.service"


def migrate_systemd_service(dry_run: bool = False, reinstall: bool = True) -> Tuple[bool, str]:
    """Migrate from agentboxd.service to boxctld.service.

    Args:
        dry_run: If True, don't actually migrate, just report
        reinstall: If True, install boxctld.service after removing old one

    Returns:
        Tuple of (success, message)
    """
    import subprocess

    legacy_path = get_legacy_systemd_service_path()
    new_path = get_new_systemd_service_path()

    if not legacy_path.exists():
        return (True, "No legacy agentboxd.service found")

    if dry_run:
        msg = f"Would migrate: {legacy_path} → {new_path}"
        if reinstall:
            msg += " (and reinstall service)"
        console.print(f"[blue]{msg}[/blue]")
        return (True, msg)

    # Stop the old service
    console.print("[yellow]Stopping agentboxd.service...[/yellow]")
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", "agentboxd"], capture_output=True, timeout=30
        )
    except Exception:
        pass  # Service might not be running

    # Disable the old service
    console.print("[yellow]Disabling agentboxd.service...[/yellow]")
    try:
        subprocess.run(
            ["systemctl", "--user", "disable", "agentboxd"], capture_output=True, timeout=10
        )
    except Exception:
        pass  # Service might not be enabled

    # Remove the old service file
    try:
        legacy_path.unlink()
        console.print(f"[green]Removed:[/green] {legacy_path}")
    except Exception as e:
        console.print(f"[red]Failed to remove {legacy_path}: {e}[/red]")
        return (False, f"Failed to remove legacy service: {e}")

    # Reload systemd
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=10)
    except Exception:
        pass

    if reinstall and not new_path.exists():
        # Actually install the new service
        console.print("[blue]Installing boxctld.service...[/blue]")
        try:
            from boxctl.cli.commands.service import (
                _get_service_unit_path,
                _get_config_path,
                _create_service_file,
                _create_default_config,
            )

            config_path = _get_config_path()
            unit_path = _get_service_unit_path()

            # Create config directory and default config if needed
            config_path.parent.mkdir(parents=True, exist_ok=True)
            if not config_path.exists():
                config_path.write_text(_create_default_config())
                console.print(f"[green]Created config at {config_path}[/green]")

            # Create systemd service
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            service_content = _create_service_file()
            unit_path.write_text(service_content)
            console.print(f"[green]Installed service at {unit_path}[/green]")

            # Reload, enable, and start
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, timeout=30)
            subprocess.run(["systemctl", "--user", "enable", "boxctld"], check=False, timeout=30)
            subprocess.run(["systemctl", "--user", "start", "boxctld"], check=False, timeout=30)
            console.print("[green]Service enabled and started[/green]")

            return (True, "Legacy agentboxd.service migrated to boxctld.service")
        except Exception as e:
            console.print(f"[yellow]Could not auto-install service: {e}[/yellow]")
            console.print("[blue]To install manually, run:[/blue]")
            console.print("  boxctl service install")
            return (True, f"Legacy service removed. Manual install needed: {e}")

    return (True, "Legacy agentboxd.service migrated successfully")


def warn_legacy_systemd_service() -> None:
    """Print warning about legacy systemd service if it exists."""
    if check_legacy_systemd_service():
        console.print()
        console.print("[yellow]⚠ Found legacy agentboxd.service[/yellow]")
        console.print(f"  [dim]{get_legacy_systemd_service_path()}[/dim]")
        console.print()
        console.print("[dim]Run 'boxctl migrate --fix-systemd' to migrate to boxctld.service[/dim]")
        console.print()
