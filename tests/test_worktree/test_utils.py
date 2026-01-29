"""Tests for worktree utilities"""

import pytest
from boxctl.agentctl.worktree.utils import (
    sanitize_branch_name,
    get_worktree_path,
)


class TestBranchSanitization:
    """Test branch name sanitization for directory names"""

    def test_simple_branch(self):
        assert sanitize_branch_name("main") == "main"
        assert sanitize_branch_name("develop") == "develop"

    def test_branch_with_slash(self):
        assert sanitize_branch_name("feature/auth-fix") == "feature-auth-fix"
        assert sanitize_branch_name("bugfix/issue-123") == "bugfix-issue-123"

    def test_branch_with_dot(self):
        assert sanitize_branch_name("release.1.0") == "release-1-0"
        assert sanitize_branch_name("v2.5.3") == "v2-5-3"

    def test_refs_prefix(self):
        assert sanitize_branch_name("refs/heads/main") == "main"
        assert sanitize_branch_name("refs/heads/feature/auth") == "feature-auth"

    def test_special_characters(self):
        # Should remove special chars
        assert sanitize_branch_name("feat@123") == "feat123"
        assert sanitize_branch_name("fix#456") == "fix456"

    def test_preserve_hyphens_underscores(self):
        assert sanitize_branch_name("feat-auth_v2") == "feat-auth_v2"
        assert sanitize_branch_name("bug_fix-123") == "bug_fix-123"

    def test_complex_branch(self):
        assert (
            sanitize_branch_name("refs/heads/feature/auth-fix.v2@test") == "feature-auth-fix-v2test"
        )


class TestWorktreePath:
    """Test worktree path generation"""

    def test_simple_path(self):
        # Default base_dir is /git-worktrees
        assert get_worktree_path("main") == "/git-worktrees/worktree-main"
        assert get_worktree_path("develop") == "/git-worktrees/worktree-develop"

    def test_custom_base_dir(self):
        assert get_worktree_path("feature", "/tmp") == "/tmp/worktree-feature"
        assert get_worktree_path("fix", "/workspace") == "/workspace/worktree-fix"

    def test_complex_branch(self):
        path = get_worktree_path("feature/auth-fix")
        assert path == "/git-worktrees/worktree-feature-auth-fix"

    def test_sanitization_in_path(self):
        path = get_worktree_path("refs/heads/feature/auth.v2")
        assert path == "/git-worktrees/worktree-feature-auth-v2"
