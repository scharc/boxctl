# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Migration runner for config migrations."""

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel

from boxctl.migrations.base import (
    Migration,
    MigrationAction,
    MigrationResult,
    MigrationSeverity,
)

console = Console()


class MigrationRunner:
    """Checks and runs config migrations."""

    def __init__(
        self,
        raw_config: Dict[str, Any],
        project_dir: Path,
        interactive: bool = True,
        auto_migrate: bool = False,
    ):
        """Initialize the migration runner.

        Args:
            raw_config: Raw config dictionary from .boxctl.yml
            project_dir: Project directory path
            interactive: Whether to prompt for user confirmation
            auto_migrate: Whether to auto-apply all applicable migrations
        """
        self.raw_config = copy.deepcopy(raw_config)
        self.project_dir = project_dir
        self.interactive = interactive
        self.auto_migrate = auto_migrate
        self.results: List[MigrationResult] = []

    def check_all(self) -> List[MigrationResult]:
        """Check all registered migrations and return results.

        Returns:
            List of MigrationResult for each applicable migration
        """
        from boxctl.migrations import get_all_migrations

        results = []
        for migration in get_all_migrations():
            result = migration.check(self.raw_config, self.project_dir)
            if result.applicable:
                results.append(result)

        self.results = results
        return results

    def run_migrations(self) -> Dict[str, Any]:
        """Apply migrations based on settings.

        Returns:
            Modified config dictionary
        """
        from boxctl.migrations import get_migration

        if not self.results:
            self.check_all()

        config = copy.deepcopy(self.raw_config)

        for result in self.results:
            if not result.applicable:
                continue

            migration = get_migration(result.migration_id)
            should_apply = False

            # SUGGEST migrations are never auto-applied - they're advisory only
            if result.action == MigrationAction.SUGGEST:
                result.skipped = True
                result.skip_reason = "suggestion only"
                continue

            if self.auto_migrate:
                should_apply = True
            elif result.action == MigrationAction.AUTO:
                should_apply = True
            elif result.action == MigrationAction.PROMPT:
                if self.interactive:
                    should_apply = self._prompt_migration(migration, result)
                    if not should_apply:
                        result.skipped = True
                        result.skip_reason = "user declined"
                        continue
                else:
                    # Non-interactive mode: skip PROMPT migrations with feedback
                    result.skipped = True
                    result.skip_reason = "requires interactive mode (use --auto to force)"
                    continue

            if should_apply:
                try:
                    config = migration.migrate(config, self.project_dir)
                    result.applied = True
                    result.changes_made = [migration.description]
                except Exception as e:
                    result.error = str(e)
                    console.print(f"[red]Migration {result.migration_id} failed: {e}[/red]")

        return config

    def _prompt_migration(self, migration: Migration, result: MigrationResult) -> bool:
        """Prompt user for migration confirmation.

        Args:
            migration: Migration instance
            result: Migration result

        Returns:
            True if user confirms migration
        """
        console.print(f"\n[bold]Migration: {migration.description}[/bold]")
        console.print(f"[dim]{migration.get_suggestion()}[/dim]")

        try:
            response = (
                console.input("\n[yellow]Apply this migration? [y/N]: [/yellow]").strip().lower()
            )
            return response in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            return False

    def show_warnings(self) -> None:
        """Display warnings for pending migrations."""
        if not self.results:
            self.check_all()

        pending = [r for r in self.results if r.applicable and not r.applied]
        if not pending:
            return

        from boxctl.migrations import get_migration

        lines = []
        for result in pending:
            migration = get_migration(result.migration_id)
            # Use first line of suggestion as brief description
            brief = migration.get_suggestion().split("\n")[0]
            if result.skipped and result.skip_reason:
                lines.append(f"• {brief} [skipped: {result.skip_reason}]")
            else:
                lines.append(f"• {brief}")

        lines.append("")
        lines.append("Run 'abox config migrate' to update.")

        message = "\n".join(lines)
        console.print(Panel(message, title="⚠ Config Migration Needed", border_style="yellow"))
