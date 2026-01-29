"""Tests for worktree metadata management"""

import json
import pytest
import tempfile
import os
from pathlib import Path

from boxctl.agentctl.worktree.metadata import WorktreeMetadata


@pytest.fixture
def temp_agentbox_dir():
    """Create a temporary .boxctl directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestWorktreeMetadata:
    """Test worktree metadata operations"""

    def test_init_creates_dir(self, temp_agentbox_dir):
        """Test that metadata manager creates directory if needed"""
        agentbox_dir = os.path.join(temp_agentbox_dir, "new_dir")
        metadata = WorktreeMetadata(agentbox_dir)

        # Add a worktree to trigger directory creation
        metadata.add("/worktree-test", "test-branch")

        assert os.path.exists(agentbox_dir)
        assert os.path.exists(metadata.metadata_file)

    def test_add_worktree(self, temp_agentbox_dir):
        """Test adding a worktree to metadata"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        metadata.add("/worktree-feature", "feature-branch", "abc123")

        worktrees = metadata.list_all()
        assert len(worktrees) == 1
        assert worktrees[0]["path"] == "/worktree-feature"
        assert worktrees[0]["branch"] == "feature-branch"
        assert worktrees[0]["commit"] == "abc123"
        assert "created" in worktrees[0]
        assert worktrees[0]["sessions"] == []

    def test_add_duplicate_updates(self, temp_agentbox_dir):
        """Test that adding duplicate worktree updates existing entry"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        metadata.add("/worktree-feature", "feature-branch", "abc123")
        metadata.add("/worktree-feature", "feature-branch-updated", "def456")

        worktrees = metadata.list_all()
        assert len(worktrees) == 1
        assert worktrees[0]["branch"] == "feature-branch-updated"
        assert worktrees[0]["commit"] == "def456"
        assert "updated" in worktrees[0]

    def test_remove_worktree(self, temp_agentbox_dir):
        """Test removing a worktree from metadata"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        metadata.add("/worktree-feature", "feature-branch")
        metadata.add("/worktree-bugfix", "bugfix-branch")

        assert len(metadata.list_all()) == 2

        metadata.remove("/worktree-feature")

        worktrees = metadata.list_all()
        assert len(worktrees) == 1
        assert worktrees[0]["path"] == "/worktree-bugfix"

    def test_get_worktree(self, temp_agentbox_dir):
        """Test getting specific worktree metadata"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        metadata.add("/worktree-feature", "feature-branch", "abc123")
        metadata.add("/worktree-bugfix", "bugfix-branch", "def456")

        wt = metadata.get("/worktree-feature")
        assert wt is not None
        assert wt["branch"] == "feature-branch"
        assert wt["commit"] == "abc123"

        # Non-existent worktree
        wt = metadata.get("/worktree-nonexistent")
        assert wt is None

    def test_add_session(self, temp_agentbox_dir):
        """Test adding session to worktree"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        metadata.add("/worktree-feature", "feature-branch")
        metadata.add_session("/worktree-feature", "claude-session")

        wt = metadata.get("/worktree-feature")
        assert "claude-session" in wt["sessions"]

        # Add another session
        metadata.add_session("/worktree-feature", "codex-session")
        wt = metadata.get("/worktree-feature")
        assert len(wt["sessions"]) == 2
        assert "claude-session" in wt["sessions"]
        assert "codex-session" in wt["sessions"]

    def test_remove_session(self, temp_agentbox_dir):
        """Test removing session from worktree"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        metadata.add("/worktree-feature", "feature-branch")
        metadata.add_session("/worktree-feature", "claude-session")
        metadata.add_session("/worktree-feature", "codex-session")

        metadata.remove_session("/worktree-feature", "claude-session")

        wt = metadata.get("/worktree-feature")
        assert len(wt["sessions"]) == 1
        assert "codex-session" in wt["sessions"]
        assert "claude-session" not in wt["sessions"]

    def test_clear_all_sessions(self, temp_agentbox_dir):
        """Test clearing all session associations"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        metadata.add("/worktree-feature", "feature-branch")
        metadata.add("/worktree-bugfix", "bugfix-branch")
        metadata.add_session("/worktree-feature", "claude-session")
        metadata.add_session("/worktree-bugfix", "codex-session")

        metadata.clear_all_sessions()

        wt1 = metadata.get("/worktree-feature")
        wt2 = metadata.get("/worktree-bugfix")
        assert wt1["sessions"] == []
        assert wt2["sessions"] == []

    def test_persistence(self, temp_agentbox_dir):
        """Test that metadata persists across instances"""
        metadata1 = WorktreeMetadata(temp_agentbox_dir)
        metadata1.add("/worktree-feature", "feature-branch", "abc123")

        # Create new instance with same directory
        metadata2 = WorktreeMetadata(temp_agentbox_dir)
        worktrees = metadata2.list_all()

        assert len(worktrees) == 1
        assert worktrees[0]["path"] == "/worktree-feature"
        assert worktrees[0]["branch"] == "feature-branch"

    def test_empty_metadata(self, temp_agentbox_dir):
        """Test operations on empty metadata"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        assert metadata.list_all() == []
        assert metadata.get("/nonexistent") is None

    def test_corrupted_metadata(self, temp_agentbox_dir):
        """Test handling of corrupted metadata file"""
        metadata = WorktreeMetadata(temp_agentbox_dir)

        # Create corrupted metadata file
        Path(temp_agentbox_dir).mkdir(parents=True, exist_ok=True)
        with open(metadata.metadata_file, "w") as f:
            f.write("invalid json {{{")

        # Should return empty list instead of crashing
        assert metadata.list_all() == []

        # Should be able to add new data
        metadata.add("/worktree-test", "test-branch")
        assert len(metadata.list_all()) == 1
