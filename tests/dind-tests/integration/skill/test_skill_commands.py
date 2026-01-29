# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for skill management commands."""

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container


@pytest.mark.integration
class TestSkillList:
    """Test 'boxctl skill list' command."""

    def test_list_shows_available_skills(self, test_project):
        """Test listing available skills from library."""
        result = run_abox("skill", "list", cwd=test_project)

        assert result.returncode == 0, f"skill list failed: {result.stderr}"
        # Should show some output (even if empty, should have headers or message)
        assert len(result.stdout) > 0, "Should have output"


@pytest.mark.integration
class TestSkillShow:
    """Test 'boxctl skill show' command."""

    def test_show_nonexistent_skill(self, test_project):
        """Test showing details of non-existent skill fails gracefully."""
        result = run_abox("skill", "show", "nonexistent-skill-xyz", cwd=test_project)

        # Should fail or indicate skill not found
        assert (
            result.returncode != 0
            or "not found" in result.stdout.lower()
            or "not found" in result.stderr.lower()
        ), f"Should fail for non-existent skill. Got: {result.stdout} {result.stderr}"


@pytest.mark.integration
class TestSkillAdd:
    """Test 'boxctl skill add' command."""

    def test_add_skill_creates_directories(self, running_container, test_project):
        """Test adding skill creates directories in both Claude and Codex."""
        container_name = f"boxctl-{test_project.name}"

        # First, check what skills are available in the library
        result = run_abox("skill", "list", cwd=test_project)
        assert result.returncode == 0

        # For testing, we'll create a test skill in the container's library
        # Note: In real tests, we'd use an actual skill from the library
        # For now, let's test the behavior with a skill that may exist

        # Create a mock skill in the library for testing
        result = exec_in_container(
            container_name,
            "mkdir -p /boxctl/library/skills/test-skill && "
            "echo '# Test Skill' > /boxctl/library/skills/test-skill/SKILL.md",
        )
        assert result.returncode == 0, "Failed to create test skill"

        # Add the skill
        result = run_abox("skill", "add", "test-skill", cwd=test_project)

        assert result.returncode == 0, f"skill add failed: {result.stderr}"
        assert (
            "Added" in result.stdout or "added" in result.stdout.lower()
        ), f"Expected success message: {result.stdout}"

        # Verify skill directory exists (skills are now project-level, shared by all agents)
        result = exec_in_container(container_name, "test -d /workspace/.boxctl/skills/test-skill")
        assert result.returncode == 0, "Skill should exist in skills directory"

        # Verify SKILL.md exists
        result = exec_in_container(
            container_name, "test -f /workspace/.boxctl/skills/test-skill/SKILL.md"
        )
        assert result.returncode == 0, "SKILL.md should exist in skill directory"

        # Cleanup
        run_abox("skill", "remove", "test-skill", cwd=test_project)

    def test_add_nonexistent_skill_fails(self, test_project):
        """Test adding non-existent skill fails."""
        result = run_abox("skill", "add", "definitely-nonexistent-skill-xyz", cwd=test_project)

        assert result.returncode != 0, "Should fail for non-existent skill"
        assert (
            "not found" in result.stdout.lower() or "not found" in result.stderr.lower()
        ), f"Expected 'not found' error"

    def test_add_duplicate_skill_warns(self, running_container, test_project):
        """Test adding already-installed skill shows warning."""
        container_name = f"boxctl-{test_project.name}"

        # Create test skill in library
        exec_in_container(
            container_name,
            "mkdir -p /boxctl/library/skills/dup-test && "
            "echo '# Dup Test' > /boxctl/library/skills/dup-test/SKILL.md",
        )

        # Add skill first time
        result = run_abox("skill", "add", "dup-test", cwd=test_project)
        assert result.returncode == 0, "First add should succeed"

        # Try to add again
        result = run_abox("skill", "add", "dup-test", cwd=test_project)

        # Should succeed but warn (implementation returns 0 and shows warning)
        assert result.returncode == 0, "Should not fail for duplicate"
        assert (
            "already exists" in result.stdout.lower()
        ), f"Expected 'already exists' message: {result.stdout}"

        # Cleanup
        run_abox("skill", "remove", "dup-test", cwd=test_project)


@pytest.mark.integration
class TestSkillRemove:
    """Test 'boxctl skill remove' command."""

    def test_remove_existing_skill(self, running_container, test_project):
        """Test removing an existing skill."""
        container_name = f"boxctl-{test_project.name}"

        # Create and add test skill
        exec_in_container(
            container_name,
            "mkdir -p /boxctl/library/skills/remove-test && "
            "echo '# Remove Test' > /boxctl/library/skills/remove-test/SKILL.md",
        )
        result = run_abox("skill", "add", "remove-test", cwd=test_project)
        assert result.returncode == 0, "Add should succeed"

        # Verify skill exists
        result = exec_in_container(container_name, "test -d /workspace/.boxctl/skills/remove-test")
        assert result.returncode == 0, "Skill should exist before removal"

        # Remove skill
        result = run_abox("skill", "remove", "remove-test", cwd=test_project)

        assert result.returncode == 0, f"skill remove failed: {result.stderr}"
        assert (
            "Removed" in result.stdout or "removed" in result.stdout.lower()
        ), f"Expected success message: {result.stdout}"

        # Verify skill is gone
        result = exec_in_container(container_name, "test -d /workspace/.boxctl/skills/remove-test")
        assert result.returncode != 0, "Skill should be removed from skills directory"

    def test_remove_nonexistent_skill(self, test_project):
        """Test removing non-existent skill shows warning."""
        result = run_abox("skill", "remove", "nonexistent-skill", cwd=test_project)

        # Should succeed but warn (implementation returns 0 and shows warning)
        assert result.returncode == 0, "Should not fail for non-existent skill"
        assert (
            "not found" in result.stdout.lower()
        ), f"Expected 'not found' message: {result.stdout}"


@pytest.mark.integration
class TestSkillIntegration:
    """Integration tests for complete skill workflows."""

    def test_skill_lifecycle(self, running_container, test_project):
        """Test complete skill lifecycle: list, add, verify, remove."""
        container_name = f"boxctl-{test_project.name}"

        skill_name = "lifecycle-skill"

        # Create test skill in library
        result = exec_in_container(
            container_name,
            f"mkdir -p /boxctl/library/skills/{skill_name} && "
            f"echo '# Lifecycle Skill' > /boxctl/library/skills/{skill_name}/SKILL.md && "
            f"echo 'Test content' > /boxctl/library/skills/{skill_name}/config.json",
        )
        assert result.returncode == 0

        # 1. List skills (should show our test skill)
        result = run_abox("skill", "list", cwd=test_project)
        assert result.returncode == 0

        # 2. Add skill
        result = run_abox("skill", "add", skill_name, cwd=test_project)
        assert result.returncode == 0
        assert "Added" in result.stdout or "added" in result.stdout.lower()

        # 3. Verify skill files exist
        result = exec_in_container(
            container_name, f"cat /workspace/.boxctl/skills/{skill_name}/SKILL.md"
        )
        assert result.returncode == 0
        assert "Lifecycle Skill" in result.stdout

        result = exec_in_container(
            container_name, f"cat /workspace/.boxctl/skills/{skill_name}/config.json"
        )
        assert result.returncode == 0
        assert "Test content" in result.stdout

        # 4. Remove skill
        result = run_abox("skill", "remove", skill_name, cwd=test_project)
        assert result.returncode == 0
        assert "Removed" in result.stdout or "removed" in result.stdout.lower()

        # 5. Verify removal
        result = exec_in_container(
            container_name, f"test -d /workspace/.boxctl/skills/{skill_name}"
        )
        assert result.returncode != 0, "Skill should be removed"

    def test_multiple_skills(self, running_container, test_project):
        """Test managing multiple skills simultaneously."""
        container_name = f"boxctl-{test_project.name}"

        skills = ["skill-a", "skill-b", "skill-c"]

        # Create test skills in library
        for skill in skills:
            exec_in_container(
                container_name,
                f"mkdir -p /boxctl/library/skills/{skill} && "
                f"echo '# {skill}' > /boxctl/library/skills/{skill}/SKILL.md",
            )

        # Add all skills
        for skill in skills:
            result = run_abox("skill", "add", skill, cwd=test_project)
            assert result.returncode == 0, f"Add {skill} should succeed"

        # Verify all exist
        for skill in skills:
            result = exec_in_container(
                container_name, f"test -f /workspace/.boxctl/skills/{skill}/SKILL.md"
            )
            assert result.returncode == 0, f"{skill} should exist in Claude skills"

        # Remove all skills
        for skill in skills:
            result = run_abox("skill", "remove", skill, cwd=test_project)
            assert result.returncode == 0, f"Remove {skill} should succeed"

        # Verify all removed
        for skill in skills:
            result = exec_in_container(container_name, f"test -d /workspace/.boxctl/skills/{skill}")
            assert result.returncode != 0, f"{skill} should be removed"

    def test_skill_persists_across_rebuild(self, running_container, test_project):
        """Test that added skills persist after container rebuild."""
        container_name = f"boxctl-{test_project.name}"

        skill_name = "persist-test"

        # Create and add test skill
        exec_in_container(
            container_name,
            f"mkdir -p /boxctl/library/skills/{skill_name} && "
            f"echo '# Persist Test' > /boxctl/library/skills/{skill_name}/SKILL.md",
        )
        result = run_abox("skill", "add", skill_name, cwd=test_project)
        assert result.returncode == 0

        # Verify skill exists
        result = exec_in_container(
            container_name, f"test -f /workspace/.boxctl/skills/{skill_name}/SKILL.md"
        )
        assert result.returncode == 0

        # Rebuild container
        result = run_abox("rebuild", cwd=test_project, timeout=180)
        assert result.returncode == 0, f"Rebuild failed: {result.stderr}"

        from helpers.docker import wait_for_container_ready

        wait_for_container_ready(container_name, timeout=120)

        # Verify skill still exists after rebuild
        result = exec_in_container(
            container_name, f"test -f /workspace/.boxctl/skills/{skill_name}/SKILL.md"
        )
        assert result.returncode == 0, "Skill should persist after rebuild"

        result = exec_in_container(
            container_name, f"cat /workspace/.boxctl/skills/{skill_name}/SKILL.md"
        )
        assert result.returncode == 0
        assert "Persist Test" in result.stdout, "Skill content should be preserved"

        # Cleanup
        run_abox("skill", "remove", skill_name, cwd=test_project)
