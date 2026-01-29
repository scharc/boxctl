# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Skill management commands."""

import shutil
from pathlib import Path
from typing import Set

import click
import questionary

from boxctl.cli import cli
from boxctl.cli.helpers import (
    _copy_commands,
    _remove_commands,
    console,
    handle_errors,
    safe_rmtree,
)
from boxctl.cli.helpers.completions import _complete_skill_names
from boxctl.library import LibraryManager
from boxctl.utils.project import resolve_project_dir, get_boxctl_dir


def _get_installed_skills(boxctl_dir: Path) -> Set[str]:
    """Get set of currently installed skill names."""
    installed = set()

    # Skills are now project-level at .boxctl/skills/
    skills_dir = boxctl_dir / "skills"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                installed.add(skill_dir.name)

    return installed


def _add_skill(name: str, lib_manager: LibraryManager, boxctl_dir: Path, project_dir: Path) -> bool:
    """Add a skill to the project. Returns True if added successfully."""
    skill_source_dir = lib_manager.skills_dir / name

    # Check custom skills directory first
    custom_skill_dir = lib_manager.user_skills_dir / name
    if custom_skill_dir.exists() and custom_skill_dir.is_dir():
        skill_source_dir = custom_skill_dir

    if not skill_source_dir.exists() or not skill_source_dir.is_dir():
        return False

    if not (skill_source_dir / "SKILL.md").exists():
        return False

    # Copy to project skills directory (shared by all agents)
    skills_dir = boxctl_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_target = skills_dir / name

    # Copy if not exists
    if not skill_target.exists():
        shutil.copytree(skill_source_dir, skill_target)

    # Copy slash commands if the skill has any
    _copy_commands(skill_source_dir, project_dir, "skill", name)

    return True


def _remove_skill(name: str, boxctl_dir: Path, project_dir: Path) -> bool:
    """Remove a skill from the project. Returns True if removed."""
    # Remove slash commands associated with this skill
    _remove_commands(project_dir, "skill", name)

    # Remove from project skills directory
    skill_dir = boxctl_dir / "skills" / name
    return safe_rmtree(skill_dir)


@cli.group(invoke_without_command=True)
@click.pass_context
@handle_errors
def skill(ctx):
    """Manage skills - select which skills to enable."""
    if ctx.invoked_subcommand is None:
        # Run the manage command by default
        ctx.invoke(skill_manage)


@skill.command(name="manage")
@handle_errors
def skill_manage():
    """Interactive skill selection with checkboxes."""
    project_dir = resolve_project_dir()
    boxctl_dir = get_boxctl_dir(project_dir)

    if not boxctl_dir.exists():
        raise click.ClickException(f".boxctl/ not found in {project_dir}. Run: boxctl init")

    lib_manager = LibraryManager()
    available_skills = lib_manager.list_skills()

    if not available_skills:
        console.print("[yellow]No skills available in library[/yellow]")
        console.print(f"[blue]Add skills to: {lib_manager.skills_dir}[/blue]")
        return

    installed = _get_installed_skills(boxctl_dir)

    # Build choices with pre-selection
    choices = []
    for skill_info in available_skills:
        name = skill_info["name"]
        desc = (
            skill_info["description"][:50] + "..."
            if len(skill_info["description"]) > 50
            else skill_info["description"]
        )
        source = skill_info.get("source", "library")
        label = f"{name} ({source}) - {desc}"
        choices.append(questionary.Choice(title=label, value=name, checked=name in installed))

    console.print("[bold]Select skills to enable:[/bold]")
    console.print("[dim]Space to toggle, Enter to confirm, Ctrl+C to cancel[/dim]\n")

    try:
        selected = questionary.checkbox(
            "Skills:",
            choices=choices,
        ).ask()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
        return

    if selected is None:
        console.print("[yellow]Cancelled[/yellow]")
        return

    selected_set = set(selected)

    # Determine what to add and remove
    to_add = selected_set - installed
    to_remove = installed - selected_set

    if not to_add and not to_remove:
        console.print("[green]No changes needed[/green]")
        return

    # Apply changes
    added = []
    removed = []

    for name in to_add:
        if _add_skill(name, lib_manager, boxctl_dir, project_dir):
            added.append(name)
        else:
            console.print(f"[red]Failed to add skill '{name}'[/red]")

    for name in to_remove:
        if _remove_skill(name, boxctl_dir, project_dir):
            removed.append(name)

    # Print summary
    if added:
        console.print(f"[green]Added skills: {', '.join(sorted(added))}[/green]")
    if removed:
        console.print(f"[yellow]Removed skills: {', '.join(sorted(removed))}[/yellow]")


@skill.command(name="show")
@click.argument("name", shell_complete=_complete_skill_names)
@handle_errors
def skill_show(name: str):
    """Show details of a skill."""
    lib_manager = LibraryManager()
    lib_manager.show_skill(name)


@skill.command(name="list")
@handle_errors
def skill_list():
    """List available skills from library."""
    lib_manager = LibraryManager()
    lib_manager.print_skills_table()


@skill.command(name="add")
@click.argument("name", shell_complete=_complete_skill_names)
@handle_errors
def skill_add(name: str):
    """Add a skill from the library to the project."""
    project_dir = resolve_project_dir()
    boxctl_dir = get_boxctl_dir(project_dir)
    if not boxctl_dir.exists():
        raise click.ClickException(f".boxctl/ not found in {project_dir}. Run: boxctl init")

    lib_manager = LibraryManager()

    if _add_skill(name, lib_manager, boxctl_dir, project_dir):
        console.print(f"[green]✓ Added '{name}' skill[/green]")
    else:
        raise click.ClickException(f"Skill '{name}' not found or missing SKILL.md")


@skill.command(name="remove")
@click.argument("name", shell_complete=_complete_skill_names)
@handle_errors
def skill_remove(name: str):
    """Remove a skill from the project."""
    project_dir = resolve_project_dir()
    boxctl_dir = get_boxctl_dir(project_dir)

    if _remove_skill(name, boxctl_dir, project_dir):
        console.print(f"[green]✓ Removed '{name}' skill[/green]")
    else:
        console.print(f"[yellow]Skill '{name}' not found in project[/yellow]")
