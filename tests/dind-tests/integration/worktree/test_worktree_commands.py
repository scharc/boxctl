# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for worktree management commands."""

import json
import shutil
import time

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container, wait_for_container_ready
from helpers.git import init_git_repo


@pytest.mark.integration
class TestWorktreeList:
    """Test 'boxctl worktree list' command."""

    def test_list_in_non_git_repo(self, running_container, test_project):
        """Test listing worktrees in non-git directory fails gracefully."""
        # test_project is not a git repo by default
        result = run_abox("worktree", "list", cwd=test_project)

        # Should fail or indicate not a git repo
        assert (
            result.returncode != 0
            or "not.*git" in result.stdout.lower()
            or "not.*git" in result.stderr.lower()
        ), f"Should fail for non-git repo. stdout: {result.stdout}, stderr: {result.stderr}"

    def test_list_empty_worktrees(self, running_container, test_project, fake_git_repo):
        """Test listing worktrees when only main workspace exists."""
        # Copy git repo to test project
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        result = run_abox("worktree", "list", cwd=test_project)

        assert result.returncode == 0, f"worktree list failed: {result.stderr}"
        # Should show the main workspace at minimum
        assert (
            "/workspace" in result.stdout or "main" in result.stdout.lower()
        ), f"Expected main workspace in output: {result.stdout}"

    def test_list_json_output(self, running_container, test_project, fake_git_repo):
        """Test JSON output format."""
        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        result = run_abox("worktree", "list", "json", cwd=test_project)

        assert result.returncode == 0, f"worktree list json failed: {result.stderr}"

        # Verify valid JSON
        try:
            data = json.loads(result.stdout)
            assert "worktrees" in data, "JSON output missing 'worktrees' key"
            assert isinstance(data["worktrees"], list), "'worktrees' should be a list"
            assert len(data["worktrees"]) > 0, "Should have at least main workspace"
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON output: {e}\nOutput: {result.stdout}")


@pytest.mark.integration
class TestWorktreeAdd:
    """Test 'boxctl worktree add' command."""

    def test_add_worktree_for_existing_branch(self, running_container, test_project, fake_git_repo):
        """Test creating worktree for existing branch."""
        container_name = f"boxctl-{test_project.name}"

        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        # Verify branch exists (created by fake_git_repo fixture)
        result = exec_in_container(container_name, "git branch --list feature-1")
        assert result.returncode == 0, "feature-1 branch should exist"

        # Add worktree
        result = run_abox("worktree", "add", "feature-1", cwd=test_project)

        assert result.returncode == 0, f"worktree add failed: {result.stderr}"
        assert (
            "success" in result.stdout.lower() or "created" in result.stdout.lower()
        ), f"Expected success message: {result.stdout}"

        # Verify worktree directory exists in container
        result = exec_in_container(container_name, "test -d /git-worktrees/worktree-feature-1")
        assert result.returncode == 0, "Worktree directory should exist"

        # Verify worktree is in git worktree list
        result = exec_in_container(container_name, "git worktree list")
        assert result.returncode == 0
        assert "feature-1" in result.stdout, f"Worktree not in git list: {result.stdout}"

        # Cleanup
        run_abox("worktree", "remove", "feature-1", cwd=test_project)

    def test_add_worktree_creates_new_branch(self, running_container, test_project, fake_git_repo):
        """Test creating worktree with new branch using --create flag."""
        container_name = f"boxctl-{test_project.name}"

        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        # Verify branch doesn't exist
        result = exec_in_container(container_name, "git branch --list new-branch")
        assert "new-branch" not in result.stdout, "Branch should not exist yet"

        # Add worktree with --create (via abox worktree, which calls agentctl worktree add --create)
        # Note: The CLI interface may differ, let's test what we can
        result = exec_in_container(container_name, "agentctl worktree add new-branch --create")

        assert result.returncode == 0, f"worktree add with --create failed: {result.stderr}"

        # Verify branch was created
        result = exec_in_container(container_name, "git branch --list new-branch")
        assert "new-branch" in result.stdout, "Branch should be created"

        # Verify worktree exists
        result = exec_in_container(container_name, "test -d /git-worktrees/worktree-new-branch")
        assert result.returncode == 0, "Worktree directory should exist"

        # Cleanup
        exec_in_container(
            container_name, "agentctl worktree remove new-branch --force 2>/dev/null || true"
        )

    def test_add_worktree_fails_for_nonexistent_branch(
        self, running_container, test_project, fake_git_repo
    ):
        """Test adding worktree for non-existent branch fails."""
        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        # Try to add worktree for non-existent branch
        result = run_abox("worktree", "add", "nonexistent-branch", cwd=test_project)

        assert result.returncode != 0, "Should fail for non-existent branch"
        assert (
            "not found" in result.stdout.lower() or "not found" in result.stderr.lower()
        ), f"Expected 'not found' error"

    def test_add_worktree_duplicate_fails(self, running_container, test_project, fake_git_repo):
        """Test adding duplicate worktree fails."""
        container_name = f"boxctl-{test_project.name}"

        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        # Add worktree first time
        result = run_abox("worktree", "add", "feature-1", cwd=test_project)
        assert result.returncode == 0, "First worktree add should succeed"

        # Try to add same worktree again
        result = run_abox("worktree", "add", "feature-1", cwd=test_project)

        assert result.returncode != 0, "Duplicate worktree should fail"
        assert (
            "already exists" in result.stdout.lower() or "already exists" in result.stderr.lower()
        ), f"Expected 'already exists' error"

        # Cleanup
        run_abox("worktree", "remove", "feature-1", cwd=test_project)


@pytest.mark.integration
class TestWorktreeRemove:
    """Test 'boxctl worktree remove' command."""

    def test_remove_existing_worktree(self, running_container, test_project, fake_git_repo):
        """Test removing an existing worktree."""
        container_name = f"boxctl-{test_project.name}"

        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        # Add worktree
        result = run_abox("worktree", "add", "feature-2", cwd=test_project)
        assert result.returncode == 0, "Worktree add should succeed"

        # Verify it exists
        result = exec_in_container(container_name, "test -d /git-worktrees/worktree-feature-2")
        assert result.returncode == 0, "Worktree should exist"

        # Remove worktree
        result = run_abox("worktree", "remove", "feature-2", cwd=test_project)

        assert result.returncode == 0, f"worktree remove failed: {result.stderr}"

        # Verify worktree is gone
        result = exec_in_container(container_name, "test -d /git-worktrees/worktree-feature-2")
        assert result.returncode != 0, "Worktree directory should be removed"

        # Verify not in git worktree list
        result = exec_in_container(container_name, "git worktree list")
        assert "worktree-feature-2" not in result.stdout, "Worktree should not be in git list"

    def test_remove_nonexistent_worktree(self, running_container, test_project, fake_git_repo):
        """Test removing non-existent worktree fails gracefully."""
        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        # Try to remove non-existent worktree
        result = run_abox("worktree", "remove", "nonexistent", cwd=test_project)

        assert result.returncode != 0, "Should fail for non-existent worktree"


@pytest.mark.integration
class TestWorktreeIntegration:
    """Integration tests for complete worktree workflows."""

    def test_worktree_lifecycle(self, running_container, test_project, fake_git_repo):
        """Test complete worktree lifecycle: add, list, use, remove."""
        container_name = f"boxctl-{test_project.name}"

        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        branch = "feature-1"

        # 1. Add worktree
        result = run_abox("worktree", "add", branch, cwd=test_project)
        assert result.returncode == 0, "Add should succeed"

        # 2. List and verify it appears
        result = run_abox("worktree", "list", cwd=test_project)
        assert result.returncode == 0
        assert branch in result.stdout, f"Branch not in list: {result.stdout}"

        # 3. Verify worktree directory structure
        result = exec_in_container(container_name, f"test -d /git-worktrees/worktree-{branch}")
        assert result.returncode == 0, "Worktree directory should exist"

        # 4. Verify .boxctl is accessible (symlinked or copied)
        result = exec_in_container(
            container_name, f"test -d /git-worktrees/worktree-{branch}/.boxctl"
        )
        assert result.returncode == 0, ".boxctl should be accessible in worktree"

        # 5. Create a file in worktree
        result = exec_in_container(
            container_name, f"echo 'test content' > /git-worktrees/worktree-{branch}/test-file.txt"
        )
        assert result.returncode == 0, "Should be able to write in worktree"

        # 6. Verify file exists
        result = exec_in_container(
            container_name, f"cat /git-worktrees/worktree-{branch}/test-file.txt"
        )
        assert result.returncode == 0
        assert "test content" in result.stdout

        # 7. Remove worktree
        result = run_abox("worktree", "remove", branch, cwd=test_project)
        assert result.returncode == 0, "Remove should succeed"

        # 8. Verify it's gone
        result = run_abox("worktree", "list", cwd=test_project)
        assert result.returncode == 0
        # Should not have the worktree anymore (but main workspace still there)
        assert f"worktree-{branch}" not in result.stdout, "Worktree should be removed from list"

    def test_multiple_worktrees(self, running_container, test_project, fake_git_repo):
        """Test managing multiple worktrees simultaneously."""
        container_name = f"boxctl-{test_project.name}"

        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        branches = ["feature-1", "feature-2"]

        # Add multiple worktrees
        for branch in branches:
            result = run_abox("worktree", "add", branch, cwd=test_project)
            assert result.returncode == 0, f"Add {branch} should succeed"

        # List all worktrees
        result = run_abox("worktree", "list", cwd=test_project)
        assert result.returncode == 0

        # Verify all branches are shown
        for branch in branches:
            assert branch in result.stdout, f"Branch {branch} not in list"

        # Remove all worktrees
        for branch in branches:
            result = run_abox("worktree", "remove", branch, cwd=test_project)
            assert result.returncode == 0, f"Remove {branch} should succeed"

    def test_worktree_isolation(self, running_container, test_project, fake_git_repo):
        """Test that worktrees are properly isolated."""
        container_name = f"boxctl-{test_project.name}"

        # Setup git repo
        for item in fake_git_repo.iterdir():
            if item.name == ".git":
                shutil.copytree(item, test_project / ".git")
            else:
                if item.is_dir():
                    shutil.copytree(item, test_project / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, test_project / item.name)

        # Add two worktrees
        run_abox("worktree", "add", "feature-1", cwd=test_project)
        run_abox("worktree", "add", "feature-2", cwd=test_project)

        # Create different files in each worktree
        exec_in_container(
            container_name, "echo 'feature 1' > /git-worktrees/worktree-feature-1/feature1.txt"
        )
        exec_in_container(
            container_name, "echo 'feature 2' > /git-worktrees/worktree-feature-2/feature2.txt"
        )

        # Verify files don't cross-contaminate
        result = exec_in_container(
            container_name, "test -f /git-worktrees/worktree-feature-1/feature2.txt"
        )
        assert result.returncode != 0, "feature2.txt should not be in feature-1 worktree"

        result = exec_in_container(
            container_name, "test -f /git-worktrees/worktree-feature-2/feature1.txt"
        )
        assert result.returncode != 0, "feature1.txt should not be in feature-2 worktree"

        # Cleanup
        run_abox("worktree", "remove", "feature-1", cwd=test_project)
        run_abox("worktree", "remove", "feature-2", cwd=test_project)
