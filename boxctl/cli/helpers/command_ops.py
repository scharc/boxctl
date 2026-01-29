# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Slash command management for MCPs and skills.

DEPRECATED: Commands are now handled at container startup.
Container-init.sh symlinks MCP commands from library/mcp/*/commands/,
~/.config/boxctl/mcp/*/commands/, and .boxctl/mcp/*/commands/
to ~/.claude/commands/ where Claude finds them.

This module is kept for backwards compatibility but most functions
are now no-ops. Commands no longer clutter the project directory.
"""

import shutil
from pathlib import Path
from typing import List, Tuple


def _get_commands_dir(project_dir: Path) -> Path:
    """DEPRECATED: Commands are now handled at container startup.

    Returns the legacy path for backwards compatibility.
    """
    return project_dir / ".boxctl" / "commands"


def _get_command_prefix(source_type: str, name: str) -> str:
    """Get the prefix for command files from a source.

    Args:
        source_type: Either 'mcp' or 'skill'
        name: Name of the MCP or skill

    Returns:
        Prefix string like 'mcp-agentctl-' or 'skill-westworld-'
    """
    return f"{source_type}-{name}-"


def _copy_commands(
    source_dir: Path,
    project_dir: Path,
    source_type: str,
    name: str,
    override_symlinks: bool = False,
) -> List[str]:
    """DEPRECATED: Commands are now handled at container startup.

    Container-init.sh copies commands from library/mcp/*/commands/ and
    .boxctl/mcp/*/commands/ to ~/.claude/skills/ automatically.

    This function is a no-op kept for backwards compatibility.
    """
    return []


def _remove_commands(
    project_dir: Path,
    source_type: str,
    name: str,
) -> List[str]:
    """Remove command files for a source from .claude/commands/.

    Args:
        project_dir: Project root directory
        source_type: Either 'mcp' or 'skill'
        name: Name of the MCP or skill

    Returns:
        List of command names that were removed
    """
    commands_dir = _get_commands_dir(project_dir)
    if not commands_dir.exists():
        return []

    prefix = _get_command_prefix(source_type, name)
    removed = []

    # Find and remove all files with this prefix
    for cmd_file in commands_dir.glob(f"{prefix}*.md"):
        # Get the original command name (without prefix and extension)
        original_name = cmd_file.name[len(prefix) :]  # e.g., "context.md"
        cmd_name = original_name[:-3] if original_name.endswith(".md") else original_name

        # Check if there's an ab- prefixed symlink pointing to this file
        ab_symlink_path = commands_dir / f"ab-{original_name}"
        if ab_symlink_path.is_symlink():
            # Only remove symlink if it points to our file
            try:
                if ab_symlink_path.resolve().name == cmd_file.name:
                    ab_symlink_path.unlink()
            except (OSError, ValueError):
                pass

        # Remove the prefixed file
        cmd_file.unlink()
        removed.append(cmd_name)

    return removed


def _list_installed_commands(project_dir: Path) -> List[Tuple[str, str, str]]:
    """List all installed commands with their sources.

    Returns:
        List of tuples: (command_name, source_type, source_name)
    """
    commands_dir = _get_commands_dir(project_dir)
    if not commands_dir.exists():
        return []

    commands = []
    for cmd_file in sorted(commands_dir.glob("*.md")):  # Sort for deterministic order
        # Skip symlinks, only process actual files
        if cmd_file.is_symlink():
            continue

        name = cmd_file.stem
        # Parse prefix to get source
        # Use rsplit to handle MCP/skill names with hyphens (e.g., "agentbox-analyst")
        # mcp-agentbox-analyst-consult -> source_name=agentbox-analyst, cmd_name=consult
        if name.startswith("mcp-"):
            rest = name[4:]  # Remove "mcp-"
            if "-" in rest:
                source_name, cmd_name = rest.rsplit("-", 1)
                commands.append((cmd_name, "mcp", source_name))
        elif name.startswith("skill-"):
            rest = name[6:]  # Remove "skill-"
            if "-" in rest:
                source_name, cmd_name = rest.rsplit("-", 1)
                commands.append((cmd_name, "skill", source_name))
        else:
            # Standalone command (not from MCP or skill)
            commands.append((name, "project", ""))

    return commands


def _get_installed_command_names(
    project_dir: Path,
    source_type: str,
    name: str,
) -> set:
    """Get the set of command names currently installed for a source.

    Args:
        project_dir: Project root directory
        source_type: Either 'mcp' or 'skill'
        name: Name of the MCP or skill

    Returns:
        Set of command names (without .md extension)
    """
    commands_dir = _get_commands_dir(project_dir)
    if not commands_dir.exists():
        return set()

    prefix = _get_command_prefix(source_type, name)
    installed = set()

    for cmd_file in commands_dir.glob(f"{prefix}*.md"):
        if cmd_file.is_symlink():
            continue
        # Extract command name: "mcp-agentctl-context.md" -> "context"
        cmd_name = cmd_file.name[len(prefix) : -3]  # Remove prefix and .md
        installed.add(cmd_name)

    return installed


def _remove_stale_commands(
    source_dir: Path,
    project_dir: Path,
    source_type: str,
    name: str,
) -> List[str]:
    """Remove commands that no longer exist in the source directory.

    Args:
        source_dir: Source directory of the MCP/skill (containing commands/ subdir)
        project_dir: Project root directory
        source_type: Either 'mcp' or 'skill'
        name: Name of the MCP or skill

    Returns:
        List of command names that were removed
    """
    commands_src = source_dir / "commands"

    # Get commands from source (what should exist)
    source_commands = set()
    if commands_src.exists() and commands_src.is_dir():
        for cmd_file in commands_src.glob("*.md"):
            source_commands.add(cmd_file.stem)

    # Get currently installed commands
    installed_commands = _get_installed_command_names(project_dir, source_type, name)

    # Find stale commands (installed but not in source)
    stale_commands = installed_commands - source_commands

    if not stale_commands:
        return []

    # Remove stale commands
    commands_dir = _get_commands_dir(project_dir)
    prefix = _get_command_prefix(source_type, name)
    removed = []

    for cmd_name in stale_commands:
        cmd_file = commands_dir / f"{prefix}{cmd_name}.md"
        if cmd_file.exists() and not cmd_file.is_symlink():
            # Remove ab- symlink if it points to this file
            ab_symlink = commands_dir / f"ab-{cmd_name}.md"
            if ab_symlink.is_symlink():
                try:
                    if ab_symlink.resolve().name == cmd_file.name:
                        ab_symlink.unlink()
                except (OSError, ValueError):
                    pass

            # Remove the command file
            cmd_file.unlink()
            removed.append(cmd_name)

    return removed


def _sync_mcp_commands(
    mcp_source_dir: Path,
    project_dir: Path,
    mcp_name: str,
    is_custom: bool = False,
) -> List[str]:
    """DEPRECATED: Commands are now handled at container startup.

    Container-init.sh symlinks commands from library/mcp/*/commands/,
    ~/.config/boxctl/mcp/*/commands/, and .boxctl/mcp/*/commands/
    to ~/.claude/commands/ automatically.

    This function is a no-op kept for backwards compatibility.
    """
    return []


def _sync_skill_commands(
    skill_source_dir: Path,
    project_dir: Path,
    skill_name: str,
    is_custom: bool = False,
) -> List[str]:
    """DEPRECATED: Commands are now handled at container startup.

    Container-init.sh handles skill setup by symlinking skill directories
    from library, user home, and project to ~/.claude/skills/.

    This function is a no-op kept for backwards compatibility.
    """
    return []
