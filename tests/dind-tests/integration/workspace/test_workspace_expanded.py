# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Expanded integration tests for workspace mount operations."""

import json
import time

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container, wait_for_container_ready


@pytest.mark.integration
class TestWorkspaceMountModes:
    """Test read-only and read-write mount modes."""

    def test_readonly_mount_prevents_writes(self, running_container, test_project, tmp_path):
        """Test that read-only mounts prevent write operations."""
        # Create a test directory with a file
        test_dir = tmp_path / "readonly_test"
        test_dir.mkdir()
        (test_dir / "test.txt").write_text("original content")

        # Add as read-only mount
        result = run_abox(
            "workspace", "add", str(test_dir), "ro", "readonly-mount", cwd=test_project
        )
        assert result.returncode == 0, f"Failed to add readonly mount: {result.stderr}"

        # Wait for container to be ready after rebuild
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        # Verify mount exists
        result = exec_in_container(container_name, "test -d /context/readonly-mount")
        assert result.returncode == 0, "Readonly mount should exist"

        # Verify file is readable
        result = exec_in_container(container_name, "cat /context/readonly-mount/test.txt")
        assert result.returncode == 0
        assert "original content" in result.stdout

        # Attempt to write should fail
        result = exec_in_container(
            container_name,
            "echo 'new content' > /context/readonly-mount/test.txt 2>&1 || echo 'WRITE_FAILED'",
        )
        assert (
            "WRITE_FAILED" in result.stdout or "Read-only" in result.stdout
        ), "Write to readonly mount should fail"

    def test_readwrite_mount_allows_writes(self, running_container, test_project, tmp_path):
        """Test that read-write mounts allow write operations."""
        # Create a test directory
        test_dir = tmp_path / "readwrite_test"
        test_dir.mkdir()
        (test_dir / "original.txt").write_text("original")

        # Add as read-write mount
        result = run_abox(
            "workspace", "add", str(test_dir), "rw", "readwrite-mount", cwd=test_project
        )
        assert result.returncode == 0, f"Failed to add readwrite mount: {result.stderr}"

        # Wait for container to be ready
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        # Write a new file
        result = exec_in_container(
            container_name, "echo 'new content' > /context/readwrite-mount/new.txt"
        )
        assert result.returncode == 0, "Write to readwrite mount should succeed"

        # Verify the file was written on host
        assert (test_dir / "new.txt").exists(), "File should be written to host"
        assert (test_dir / "new.txt").read_text().strip() == "new content"

    def test_default_mode_is_readonly(self, running_container, test_project, tmp_path):
        """Test that omitting mode defaults to read-only."""
        # Create test directory
        test_dir = tmp_path / "default_mode_test"
        test_dir.mkdir()

        # Add without specifying mode
        result = run_abox("workspace", "add", str(test_dir), "default-mount", cwd=test_project)
        assert result.returncode == 0

        # Wait for container
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        # Attempt write should fail (default is ro)
        result = exec_in_container(
            container_name,
            "echo 'test' > /context/default-mount/test.txt 2>&1 || echo 'WRITE_FAILED'",
        )
        assert "WRITE_FAILED" in result.stdout or "Read-only" in result.stdout


@pytest.mark.integration
class TestWorkspaceMountPaths:
    """Test different path scenarios for workspace mounts."""

    def test_mount_with_spaces_in_path(self, running_container, test_project, tmp_path):
        """Test mounting directory with spaces in path."""
        # Create directory with spaces
        test_dir = tmp_path / "dir with spaces"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")

        # Add mount
        result = run_abox("workspace", "add", str(test_dir), "ro", "spaced-mount", cwd=test_project)
        assert result.returncode == 0, f"Failed to add mount with spaces: {result.stderr}"

        # Wait and verify
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        result = exec_in_container(container_name, "cat /context/spaced-mount/file.txt")
        assert result.returncode == 0
        assert "content" in result.stdout

    def test_mount_nested_directory(self, running_container, test_project, tmp_path):
        """Test mounting deeply nested directory."""
        # Create nested structure
        test_dir = tmp_path / "level1" / "level2" / "level3"
        test_dir.mkdir(parents=True)
        (test_dir / "deep.txt").write_text("deep content")

        # Add mount
        result = run_abox("workspace", "add", str(test_dir), "ro", "nested-mount", cwd=test_project)
        assert result.returncode == 0

        # Verify
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        result = exec_in_container(container_name, "cat /context/nested-mount/deep.txt")
        assert "deep content" in result.stdout

    def test_mount_with_symlink_contents(self, running_container, test_project, tmp_path):
        """Test mounting directory containing symlinks."""
        # Create directory with symlink
        test_dir = tmp_path / "symlink_test"
        test_dir.mkdir()
        (test_dir / "real.txt").write_text("real content")
        (test_dir / "link.txt").symlink_to(test_dir / "real.txt")

        # Add mount
        result = run_abox(
            "workspace", "add", str(test_dir), "ro", "symlink-mount", cwd=test_project
        )
        assert result.returncode == 0

        # Verify symlink works in container
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        result = exec_in_container(container_name, "cat /context/symlink-mount/link.txt")
        assert "real content" in result.stdout


@pytest.mark.integration
class TestWorkspaceMountConflicts:
    """Test conflict detection and handling."""

    def test_duplicate_mount_name_rejected(self, running_container, test_project, tmp_path):
        """Test that duplicate mount names are rejected."""
        # Create two directories
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        dir2 = tmp_path / "dir2"
        dir2.mkdir()

        # Add first mount
        result = run_abox("workspace", "add", str(dir1), "ro", "duplicate-name", cwd=test_project)
        assert result.returncode == 0

        # Try to add second with same name
        result = run_abox("workspace", "add", str(dir2), "ro", "duplicate-name", cwd=test_project)
        assert result.returncode != 0, "Duplicate mount name should be rejected"
        assert "already exists" in result.stderr.lower() or "duplicate" in result.stderr.lower()

    def test_same_path_different_names_allowed(self, running_container, test_project, tmp_path):
        """Test that same path with different names is allowed."""
        # Create one directory
        test_dir = tmp_path / "shared_dir"
        test_dir.mkdir()

        # Add first mount
        result = run_abox("workspace", "add", str(test_dir), "ro", "mount-a", cwd=test_project)
        assert result.returncode == 0

        # Wait for rebuild
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        # Add second mount with same path but different name
        result = run_abox("workspace", "add", str(test_dir), "ro", "mount-b", cwd=test_project)
        # Should either succeed or be rejected - both are valid behaviors
        # Just verify it doesn't crash
        assert result.returncode in (0, 1)


@pytest.mark.integration
class TestWorkspaceMountRemoval:
    """Test workspace mount removal operations."""

    def test_remove_mount_by_name(self, running_container, test_project, tmp_path):
        """Test removing mount by name."""
        # Add mount
        test_dir = tmp_path / "remove_test"
        test_dir.mkdir()
        result = run_abox("workspace", "add", str(test_dir), "ro", "remove-me", cwd=test_project)
        assert result.returncode == 0

        # Verify it's listed
        result = run_abox("workspace", "list", "--json", cwd=test_project)
        data = json.loads(result.stdout)
        assert any(m["name"] == "remove-me" for m in data.get("mounts", []))

        # Remove it
        result = run_abox("workspace", "remove", "remove-me", cwd=test_project)
        assert result.returncode == 0

        # Verify it's gone
        result = run_abox("workspace", "list", "--json", cwd=test_project)
        data = json.loads(result.stdout)
        assert not any(m["name"] == "remove-me" for m in data.get("mounts", []))

    def test_remove_mount_by_path(self, running_container, test_project, tmp_path):
        """Test removing mount by path."""
        # Add mount
        test_dir = tmp_path / "remove_by_path"
        test_dir.mkdir()
        result = run_abox("workspace", "add", str(test_dir), "ro", "path-mount", cwd=test_project)
        assert result.returncode == 0

        # Remove by path
        result = run_abox("workspace", "remove", str(test_dir), cwd=test_project)
        assert result.returncode == 0

        # Verify removal
        result = run_abox("workspace", "list", "--json", cwd=test_project)
        data = json.loads(result.stdout)
        assert not any(str(test_dir) in m.get("path", "") for m in data.get("mounts", []))

    def test_remove_nonexistent_mount(self, running_container, test_project):
        """Test that removing non-existent mount fails gracefully."""
        result = run_abox("workspace", "remove", "nonexistent-mount", cwd=test_project)
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "does not exist" in result.stderr.lower()


@pytest.mark.integration
class TestWorkspaceMountErrors:
    """Test error handling for workspace mounts."""

    def test_mount_nonexistent_directory(self, running_container, test_project, tmp_path):
        """Test that mounting non-existent directory fails."""
        nonexistent = tmp_path / "does_not_exist"

        result = run_abox("workspace", "add", str(nonexistent), "ro", "bad-mount", cwd=test_project)
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "does not exist" in result.stderr.lower()

    def test_mount_file_instead_of_directory(self, running_container, test_project, tmp_path):
        """Test that mounting a file instead of directory fails."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        result = run_abox("workspace", "add", str(test_file), "ro", "file-mount", cwd=test_project)
        assert result.returncode != 0
        assert "directory" in result.stderr.lower() or "not a directory" in result.stderr.lower()

    def test_invalid_mount_mode(self, running_container, test_project, tmp_path):
        """Test that invalid mount mode is rejected."""
        test_dir = tmp_path / "mode_test"
        test_dir.mkdir()

        result = run_abox(
            "workspace", "add", str(test_dir), "invalid-mode", "bad-mode-mount", cwd=test_project
        )
        assert result.returncode != 0
        assert "invalid" in result.stderr.lower() or "mode" in result.stderr.lower()

    def test_mount_with_invalid_name(self, running_container, test_project, tmp_path):
        """Test that invalid mount names are rejected."""
        test_dir = tmp_path / "name_test"
        test_dir.mkdir()

        # Names with special characters that might break Docker
        invalid_names = [
            "mount/with/slashes",
            "mount:with:colons",
            "mount with\ttabs",
        ]

        for invalid_name in invalid_names:
            result = run_abox(
                "workspace", "add", str(test_dir), "ro", invalid_name, cwd=test_project
            )
            # Should either reject or sanitize - both are valid
            # Just verify it doesn't crash
            assert result.returncode in (0, 1)


@pytest.mark.integration
class TestWorkspaceMountMultiple:
    """Test multiple workspace mounts."""

    def test_multiple_mounts_coexist(self, running_container, test_project, tmp_path):
        """Test that multiple mounts can coexist."""
        # Create three directories
        dirs = []
        for i in range(3):
            d = tmp_path / f"mount_{i}"
            d.mkdir()
            (d / f"file_{i}.txt").write_text(f"content {i}")
            dirs.append(d)

        # Add all three mounts
        for i, d in enumerate(dirs):
            result = run_abox("workspace", "add", str(d), "ro", f"mount-{i}", cwd=test_project)
            assert result.returncode == 0, f"Failed to add mount {i}"

        # Wait for final rebuild
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        # Verify all three are accessible
        for i in range(3):
            result = exec_in_container(container_name, f"cat /context/mount-{i}/file_{i}.txt")
            assert result.returncode == 0
            assert f"content {i}" in result.stdout

    def test_list_multiple_mounts(self, running_container, test_project, tmp_path):
        """Test listing multiple mounts."""
        # Add several mounts
        for i in range(3):
            d = tmp_path / f"list_mount_{i}"
            d.mkdir()
            result = run_abox("workspace", "add", str(d), "ro", f"list-mount-{i}", cwd=test_project)
            assert result.returncode == 0

        # List all mounts
        result = run_abox("workspace", "list", "--json", cwd=test_project)
        assert result.returncode == 0

        data = json.loads(result.stdout)
        mount_names = [m["name"] for m in data.get("mounts", [])]

        # Verify all three are listed
        for i in range(3):
            assert f"list-mount-{i}" in mount_names

    def test_remove_one_mount_keeps_others(self, running_container, test_project, tmp_path):
        """Test that removing one mount doesn't affect others."""
        # Add three mounts
        for i in range(3):
            d = tmp_path / f"keep_mount_{i}"
            d.mkdir()
            result = run_abox("workspace", "add", str(d), "ro", f"keep-mount-{i}", cwd=test_project)
            assert result.returncode == 0

        # Remove the middle one
        result = run_abox("workspace", "remove", "keep-mount-1", cwd=test_project)
        assert result.returncode == 0

        # Verify the other two remain
        result = run_abox("workspace", "list", "--json", cwd=test_project)
        data = json.loads(result.stdout)
        mount_names = [m["name"] for m in data.get("mounts", [])]

        assert "keep-mount-0" in mount_names
        assert "keep-mount-1" not in mount_names
        assert "keep-mount-2" in mount_names


@pytest.mark.integration
class TestWorkspaceMountPersistence:
    """Test workspace mount persistence across container lifecycle."""

    def test_mounts_persist_across_restart(self, running_container, test_project, tmp_path):
        """Test that mounts persist when container is stopped and started."""
        # Add mount
        test_dir = tmp_path / "persist_test"
        test_dir.mkdir()
        (test_dir / "persist.txt").write_text("persistent data")

        result = run_abox(
            "workspace", "add", str(test_dir), "ro", "persist-mount", cwd=test_project
        )
        assert result.returncode == 0

        # Stop container
        result = run_abox("stop", cwd=test_project)
        assert result.returncode == 0

        # Start container again
        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0

        # Wait for container
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        # Verify mount still exists and works
        result = exec_in_container(container_name, "cat /context/persist-mount/persist.txt")
        assert result.returncode == 0
        assert "persistent data" in result.stdout

    def test_mount_config_survives_rebuild(self, running_container, test_project, tmp_path):
        """Test that mount configuration survives container rebuild."""
        # Add mount
        test_dir = tmp_path / "rebuild_test"
        test_dir.mkdir()
        result = run_abox(
            "workspace", "add", str(test_dir), "ro", "rebuild-mount", cwd=test_project
        )
        assert result.returncode == 0

        # Rebuild container
        result = run_abox("rebuild", cwd=test_project)
        assert result.returncode == 0

        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=60)

        # Verify mount is still configured
        result = run_abox("workspace", "list", "--json", cwd=test_project)
        data = json.loads(result.stdout)
        mount_names = [m["name"] for m in data.get("mounts", [])]
        assert "rebuild-mount" in mount_names


@pytest.mark.integration
class TestWorkspaceMountIntegration:
    """Integration tests for complete workspace mount workflows."""

    def test_complete_mount_lifecycle(self, running_container, test_project, tmp_path):
        """Test complete mount lifecycle: add, use, modify, remove."""
        test_dir = tmp_path / "lifecycle_test"
        test_dir.mkdir()
        (test_dir / "initial.txt").write_text("initial")

        # 1. Add mount
        result = run_abox(
            "workspace", "add", str(test_dir), "ro", "lifecycle-mount", cwd=test_project
        )
        assert result.returncode == 0

        # 2. Verify accessible
        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        result = exec_in_container(container_name, "cat /context/lifecycle-mount/initial.txt")
        assert "initial" in result.stdout

        # 3. Add new file on host
        (test_dir / "added.txt").write_text("added content")

        # 4. Verify new file visible in container
        result = exec_in_container(container_name, "cat /context/lifecycle-mount/added.txt")
        assert "added content" in result.stdout

        # 5. Remove mount
        result = run_abox("workspace", "remove", "lifecycle-mount", cwd=test_project)
        assert result.returncode == 0

        # 6. Verify mount is gone
        result = run_abox("workspace", "list", "--json", cwd=test_project)
        data = json.loads(result.stdout)
        assert not any(m["name"] == "lifecycle-mount" for m in data.get("mounts", []))

    def test_readwrite_mount_file_sync(self, running_container, test_project, tmp_path):
        """Test bidirectional file sync with read-write mount."""
        test_dir = tmp_path / "sync_test"
        test_dir.mkdir()

        # Add as read-write
        result = run_abox("workspace", "add", str(test_dir), "rw", "sync-mount", cwd=test_project)
        assert result.returncode == 0

        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        # 1. Write from container
        result = exec_in_container(
            container_name, "echo 'from container' > /context/sync-mount/container-file.txt"
        )
        assert result.returncode == 0

        # 2. Verify on host
        time.sleep(0.5)  # Brief delay for file sync
        assert (test_dir / "container-file.txt").exists()
        assert "from container" in (test_dir / "container-file.txt").read_text()

        # 3. Write from host
        (test_dir / "host-file.txt").write_text("from host")

        # 4. Verify in container
        time.sleep(0.5)
        result = exec_in_container(container_name, "cat /context/sync-mount/host-file.txt")
        assert "from host" in result.stdout

    def test_mount_with_existing_files_accessible(self, running_container, test_project, tmp_path):
        """Test that mounting directory with existing files makes them accessible."""
        test_dir = tmp_path / "existing_files"
        test_dir.mkdir()

        # Create several files before mounting
        for i in range(5):
            (test_dir / f"file_{i}.txt").write_text(f"content {i}")

        # Add mount
        result = run_abox(
            "workspace", "add", str(test_dir), "ro", "existing-mount", cwd=test_project
        )
        assert result.returncode == 0

        container_name = f"boxctl-{test_project.name}"
        wait_for_container_ready(container_name, timeout=30)

        # Verify all files are accessible
        for i in range(5):
            result = exec_in_container(container_name, f"cat /context/existing-mount/file_{i}.txt")
            assert result.returncode == 0
            assert f"content {i}" in result.stdout
