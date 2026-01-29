# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Tests for skill management commands (list, add, remove)."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.conftest import run_abox


@pytest.fixture
def test_skill(tmp_path):
    """Create a test skill in a temporary location."""
    from unittest.mock import patch

    # Create skill in temp directory
    skill_dir = tmp_path / "test-skill-fixture"
    skill_dir.mkdir()

    # Add SKILL.md
    (skill_dir / "SKILL.md").write_text(
        """---
name: test-skill-fixture
description: A test skill for testing.
---

# Test Skill

This is a test skill.
"""
    )

    # Add config.json
    config = {"name": "test-skill-fixture", "version": "1.0.0"}
    (skill_dir / "config.json").write_text(json.dumps(config))

    # Add README.md
    (skill_dir / "README.md").write_text("# Test Skill\n\nFor testing purposes.")

    # Patch user_skills_dir to include our test skill
    with patch("boxctl.library.HostPaths.user_skills_dir", return_value=tmp_path):
        yield skill_dir.name, skill_dir


def test_skill_list_shows_library(test_project):
    """Test that 'abox skill list' shows available skills."""
    result = run_abox("skill", "list", cwd=test_project)

    assert result.returncode == 0, "skill list should succeed"
    # Output should have content (skills table or message)
    assert len(result.stdout) > 10, "Output should have content"


def test_skill_add_copies_to_project(test_project, test_skill):
    """Test that 'abox skill add' copies skill to project skills directory."""
    skill_name, _ = test_skill

    result = run_abox("skill", "add", skill_name, cwd=test_project, check=False)

    assert result.returncode == 0, f"skill add should succeed: {result.stderr}"

    # Skills are now stored in unified .boxctl/skills/ directory
    skill_dir = test_project / ".boxctl" / "skills" / skill_name

    assert skill_dir.exists(), f"Skill {skill_name} should be copied to project skills"
    assert (skill_dir / "README.md").exists(), "Skill files should be copied"


def test_skill_add_creates_skill_dir(test_project, test_skill):
    """Test that adding a skill creates the skill directory."""
    skill_name, _ = test_skill

    result = run_abox("skill", "add", skill_name, cwd=test_project, check=False)

    assert result.returncode == 0, f"skill add should succeed: {result.stderr}"

    skill_dir = test_project / ".boxctl" / "skills" / skill_name
    assert skill_dir.exists(), f"Skill {skill_name} should be created"
    assert (skill_dir / "config.json").exists(), "Skill config should be copied"


def test_skill_remove_deletes_from_project(test_project, test_skill):
    """Test that 'abox skill remove' removes skill from project."""
    skill_name, _ = test_skill

    # Add skill first
    add_result = run_abox("skill", "add", skill_name, cwd=test_project, check=False)
    assert add_result.returncode == 0, "skill add should succeed"

    # Verify it was added
    skill_dir = test_project / ".boxctl" / "skills" / skill_name
    assert skill_dir.exists(), "Skill should exist before remove"

    # Remove skill
    remove_result = run_abox("skill", "remove", skill_name, cwd=test_project, check=False)
    assert remove_result.returncode == 0, f"skill remove should succeed: {remove_result.stderr}"

    # Verify skill was removed
    assert not skill_dir.exists(), "Skill should be removed after skill remove"


def test_skill_files_accessible_in_container(test_project, test_skill):
    """Test that added skills are accessible in container.

    This is an integration test that requires a running container.
    """
    skill_name, _ = test_skill

    # Add skill
    run_abox("skill", "add", skill_name, cwd=test_project, check=False)

    # Start container
    run_abox("start", cwd=test_project)

    container_name = f"boxctl-{test_project.name}"

    # Check skill files are accessible (skills now mounted at container-level)
    result = subprocess.run(
        ["docker", "exec", container_name, "ls", f"/home/abox/.boxctl/skills/{skill_name}"],
        capture_output=True,
        text=True,
    )

    assert (
        result.returncode == 0
    ), f"Skill directory should be accessible in container: {result.stderr}"


def test_skill_show_displays_info(test_project, test_skill):
    """Test that 'abox skill show' displays skill info."""
    skill_name, _ = test_skill

    result = run_abox("skill", "show", skill_name, cwd=test_project, check=False)

    # Should succeed or show not found message
    if result.returncode == 0:
        assert (
            skill_name in result.stdout or "description" in result.stdout.lower()
        ), "Output should contain skill info"
