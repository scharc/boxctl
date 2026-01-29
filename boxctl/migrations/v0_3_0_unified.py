# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Migrations for v0.3.0 unified agent configuration structure.

This migration consolidates agent configurations into a single .boxctl/ folder:
- Moves .boxctl.yml → .boxctl/config.yml
- Merges agent-specific MCP configs into unified mcp.json
- Creates internal symlinks for shared resources
- Updates .gitignore for state directories
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from boxctl.migrations.base import (
    Migration,
    MigrationAction,
    MigrationSeverity,
)

logger = logging.getLogger(__name__)


class UnifiedConfigStructure(Migration):
    """Migrate to unified .boxctl/ configuration structure.

    This consolidates all agent configurations into a single folder:
    - .boxctl.yml moves to .boxctl/config.yml
    - Agent MCP configs merge into .boxctl/mcp.json
    - Internal symlinks point to shared agents.md, skills/, mcp.json
    - State directories are added to .gitignore
    """

    id = "unified-config-structure"
    description = "Migrate to unified .boxctl/ configuration structure"
    introduced_in = "0.3.0"
    severity = MigrationSeverity.WARNING
    default_action = MigrationAction.PROMPT

    def detect(self, raw_config: Dict[str, Any], project_dir: Path) -> bool:
        """Check if project uses old structure with .boxctl.yml in root."""
        old_config = project_dir / ".boxctl.yml"
        new_config = project_dir / ".boxctl" / "config.yml"

        # Migration needed if old config exists and new doesn't
        if old_config.exists() and not new_config.exists():
            return True

        return False

    def migrate(self, raw_config: Dict[str, Any], project_dir: Path) -> Dict[str, Any]:
        """Apply the unified config migration.

        This performs file operations:
        1. Creates backup of existing state
        2. Moves .boxctl.yml → .boxctl/config.yml
        3. Merges MCP configs into unified mcp.json
        4. Creates internal symlinks
        5. Updates .gitignore

        Args:
            raw_config: Raw config dictionary (unchanged in return)
            project_dir: Project directory path

        Returns:
            The config dictionary (unchanged - file operations done separately)
        """
        boxctl_dir = project_dir / ".boxctl"
        old_config = project_dir / ".boxctl.yml"
        new_config = boxctl_dir / "config.yml"

        # 1. Create backup
        backup_dir = self._create_backup(boxctl_dir)

        try:
            # 2. Move .boxctl.yml → .boxctl/config.yml
            if old_config.exists() and not new_config.exists():
                boxctl_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_config), str(new_config))

            # 3. Merge MCP configs into unified mcp.json
            self._merge_mcp_configs(boxctl_dir)

            # 4. Create internal symlinks
            self._create_internal_symlinks(boxctl_dir)

            # 5. Update .gitignore
            self._update_gitignore(project_dir)

            # 6. Clean up backup on success (keep for now, user can delete)
            # shutil.rmtree(backup_dir)

        except Exception as e:
            # Restore from backup on failure
            raise RuntimeError(f"Migration failed: {e}. Backup at: {backup_dir}")

        return raw_config

    def _create_backup(self, boxctl_dir: Path) -> Path:
        """Create backup of existing state before migration."""
        backup_dir = boxctl_dir / "backup-pre-migration"

        # Remove old backup if exists
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        backup_dir.mkdir(parents=True, exist_ok=True)

        # Backup agent directories
        for agent in ["claude", "codex"]:
            src = boxctl_dir / agent
            if src.exists() or src.is_symlink():
                dst = backup_dir / agent
                # Remove existing destination if present (shouldn't happen, but be safe)
                if dst.exists() or dst.is_symlink():
                    if dst.is_symlink() or dst.is_file():
                        dst.unlink()
                    else:
                        shutil.rmtree(dst)
                if src.is_symlink():
                    # Copy symlink itself (preserving target)
                    dst.symlink_to(src.readlink())
                elif src.is_dir():
                    shutil.copytree(src, dst, symlinks=True)

        # Backup old config if it exists in parent
        old_config = boxctl_dir.parent / ".boxctl.yml"
        if old_config.exists():
            shutil.copy2(old_config, backup_dir / ".boxctl.yml")

        return backup_dir

    def _merge_mcp_configs(self, boxctl_dir: Path) -> None:
        """Merge agent-specific MCP configs into unified mcp.json."""
        unified_mcp: Dict[str, Any] = {"mcpServers": {}}
        unified_mcp_file = boxctl_dir / "mcp.json"

        # Load existing unified config if present
        if unified_mcp_file.exists():
            try:
                unified_mcp = json.loads(unified_mcp_file.read_text())
            except json.JSONDecodeError:
                pass

        # Merge from Claude config
        claude_mcp = boxctl_dir / "claude" / "mcp.json"
        if claude_mcp.exists() and not claude_mcp.is_symlink():
            try:
                claude_config = json.loads(claude_mcp.read_text())
                unified_mcp["mcpServers"].update(claude_config.get("mcpServers", {}))
            except json.JSONDecodeError:
                pass

        # Merge from Codex config (parse TOML for mcp_servers section)
        codex_config = boxctl_dir / "codex" / "config.toml"
        if codex_config.exists():
            try:
                import tomllib

                config = tomllib.loads(codex_config.read_text())
                mcp_servers = config.get("mcp_servers", {})
                for name, server in mcp_servers.items():
                    if name not in unified_mcp["mcpServers"]:
                        unified_mcp["mcpServers"][name] = {
                            "command": server.get("command", ""),
                            "args": server.get("args", []),
                        }
                        if server.get("env"):
                            unified_mcp["mcpServers"][name]["env"] = server["env"]
            except (ImportError, Exception):
                pass  # TOML parsing failed, skip

        # Write unified config
        if unified_mcp["mcpServers"]:
            unified_mcp_file.write_text(json.dumps(unified_mcp, indent=2) + "\n")

    def _create_internal_symlinks(self, boxctl_dir: Path) -> None:
        """Create internal symlinks from agent dirs to unified resources."""
        # Create agent directories
        for agent in ["claude", "codex", "gemini", "qwen"]:
            agent_dir = boxctl_dir / agent
            agent_dir.mkdir(parents=True, exist_ok=True)

        # Symlinks for Claude: mcp.json, skills
        self._safe_symlink(boxctl_dir / "claude" / "mcp.json", "../mcp.json")
        if (boxctl_dir / "skills").exists():
            self._safe_symlink(boxctl_dir / "claude" / "skills", "../skills")

        # Symlinks for other agents: instructions, skills
        for agent, instr_file in [
            ("codex", "AGENTS.md"),
            ("gemini", "GEMINI.md"),
            ("qwen", "QWEN.md"),
        ]:
            if (boxctl_dir / "agents.md").exists():
                self._safe_symlink(boxctl_dir / agent / instr_file, "../agents.md")
            if (boxctl_dir / "skills").exists():
                self._safe_symlink(boxctl_dir / agent / "skills", "../skills")

    def _safe_symlink(self, link_path: Path, target: str) -> None:
        """Create symlink, removing existing file/link if necessary.

        Args:
            link_path: Path where symlink should be created
            target: Relative path the symlink should point to
        """
        # Check if symlink already exists and points to correct target
        if link_path.is_symlink():
            try:
                if str(link_path.readlink()) == target:
                    # Already correct, nothing to do
                    return
            except OSError:
                pass  # Broken symlink, will be recreated
            link_path.unlink()
        elif link_path.exists():
            if link_path.is_file():
                link_path.unlink()
            elif link_path.is_dir():
                # Don't remove directories - they may contain state
                logger.warning(f"Cannot create symlink at {link_path}: directory exists")
                return

        try:
            link_path.symlink_to(target)
        except OSError as e:
            logger.warning(f"Failed to create symlink {link_path} -> {target}: {e}")

    def _update_gitignore(self, project_dir: Path) -> None:
        """Add state directories to .gitignore."""
        gitignore = project_dir / ".gitignore"
        ignore_entries = [
            "",
            "# boxctl state (session data, not for version control)",
            ".boxctl/claude/projects/",
            ".boxctl/claude/file-history/",
            ".boxctl/claude/todos/",
            ".boxctl/claude/debug/",
            ".boxctl/claude/statsig/",
            ".boxctl/codex/sessions/",
            ".boxctl/backup-pre-migration/",
        ]

        marker = "# boxctl state"

        if gitignore.exists():
            content = gitignore.read_text()
            if marker not in content:
                gitignore.write_text(content.rstrip() + "\n" + "\n".join(ignore_entries) + "\n")
        else:
            # Create new .gitignore with these entries
            gitignore.write_text("\n".join(ignore_entries) + "\n")

    def get_suggestion(self) -> str:
        """Get human-readable fix suggestion."""
        return (
            "Migrate to unified .boxctl/ configuration structure\n"
            "This moves .boxctl.yml into .boxctl/config.yml and\n"
            "consolidates agent configurations for easier management.\n"
            "Run: abox config migrate"
        )


class MCPUnification(Migration):
    """Migrate separate agent MCP configs to unified mcp.json.

    This handles projects that already have .boxctl/config.yml but
    still have separate MCP configs in .boxctl/claude/mcp.json.
    """

    id = "mcp-unification"
    description = "Merge agent MCP configs into unified .boxctl/mcp.json"
    introduced_in = "0.3.0"
    severity = MigrationSeverity.INFO
    default_action = MigrationAction.AUTO

    def detect(self, raw_config: Dict[str, Any], project_dir: Path) -> bool:
        """Check if project has separate MCP configs that should be unified."""
        boxctl_dir = project_dir / ".boxctl"
        unified_mcp = boxctl_dir / "mcp.json"
        claude_mcp = boxctl_dir / "claude" / "mcp.json"

        # Migration needed if Claude MCP exists but is not a symlink to unified
        if claude_mcp.exists() and not claude_mcp.is_symlink():
            # And either unified doesn't exist or Claude's is different
            if not unified_mcp.exists():
                return True
            # Could add content comparison here

        return False

    def migrate(self, raw_config: Dict[str, Any], project_dir: Path) -> Dict[str, Any]:
        """Merge MCP configs and create symlink."""
        boxctl_dir = project_dir / ".boxctl"
        unified_mcp = boxctl_dir / "mcp.json"
        claude_mcp = boxctl_dir / "claude" / "mcp.json"

        # Load and merge
        unified: Dict[str, Any] = {"mcpServers": {}}
        if unified_mcp.exists():
            try:
                unified = json.loads(unified_mcp.read_text())
            except json.JSONDecodeError:
                pass

        if claude_mcp.exists() and not claude_mcp.is_symlink():
            try:
                claude = json.loads(claude_mcp.read_text())
                unified["mcpServers"].update(claude.get("mcpServers", {}))
            except json.JSONDecodeError:
                pass

        # Write unified
        unified_mcp.write_text(json.dumps(unified, indent=2) + "\n")

        # Replace Claude's with symlink
        # Check both exists() and is_symlink() to handle broken symlinks
        if claude_mcp.exists() or claude_mcp.is_symlink():
            claude_mcp.unlink()
        claude_mcp.symlink_to("../mcp.json")

        return raw_config

    def get_suggestion(self) -> str:
        """Get human-readable fix suggestion."""
        return (
            "Merge MCP configs into unified .boxctl/mcp.json\n"
            "Agent-specific MCP configs will be replaced with symlinks."
        )
