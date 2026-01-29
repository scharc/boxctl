# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for project lifecycle commands."""

import pytest

from helpers.cli import run_abox
from helpers.docker import (
    container_exists,
    container_is_running,
    wait_for_container_ready,
    exec_in_container,
    run_docker,
)


class TestProjectInit:
    """Test 'boxctl init' command."""

    def test_init_creates_agentbox_dir(self, module_workspace):
        """Test init creates .boxctl directory."""
        import uuid

        project_dir = module_workspace / f"init-test-{uuid.uuid4().hex[:8]}"
        project_dir.mkdir(parents=True)

        result = run_abox("init", cwd=project_dir)

        assert result.returncode == 0, f"Init failed: {result.stderr}"
        assert (project_dir / ".boxctl").is_dir()
        assert (project_dir / ".boxctl" / "claude").is_dir()

    def test_init_creates_mcp_config(self, module_workspace):
        """Test init creates MCP configuration."""
        import uuid

        project_dir = module_workspace / f"init-mcp-{uuid.uuid4().hex[:8]}"
        project_dir.mkdir(parents=True)

        run_abox("init", cwd=project_dir)

        mcp_config = project_dir / ".boxctl" / "claude" / "mcp.json"
        assert mcp_config.exists()

    def test_init_idempotent(self, test_project):
        """Test init is idempotent (can run multiple times)."""
        result = run_abox("init", cwd=test_project)

        assert result.returncode == 0


class TestProjectStart:
    """Test 'boxctl start' command."""

    def test_start_creates_container(self, test_project):
        """Test start creates a Docker container."""
        container_name = f"boxctl-{test_project.name}"

        result = run_abox("start", cwd=test_project)

        assert result.returncode == 0, f"Start failed: {result.stderr}"
        assert container_exists(container_name)
        assert container_is_running(container_name)

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_start_container_becomes_healthy(self, test_project):
        """Test started container becomes healthy."""
        container_name = f"boxctl-{test_project.name}"

        run_abox("start", cwd=test_project)

        # Wait for container to be ready
        ready = wait_for_container_ready(container_name, timeout=60)
        assert ready, "Container did not become ready"

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_start_mounts_workspace(self, test_project):
        """Test container has /workspace mounted with actual file visibility.

        This is a critical True DinD test - verifies that bind mounts work
        correctly in the nested Docker environment.
        """
        container_name = f"boxctl-{test_project.name}"

        # Create a test file on the host (test container filesystem)
        test_content = f"True DinD bind mount test - {container_name}"
        test_file = test_project / "dind_bind_test.txt"
        test_file.write_text(test_content)

        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name)

        # Verify directory exists
        result = exec_in_container(container_name, "test -d /workspace")
        assert result.returncode == 0, "/workspace directory not mounted"

        # Verify file created on host is visible in container
        result = exec_in_container(container_name, "cat /workspace/dind_bind_test.txt")
        assert result.returncode == 0, f"Test file not readable in container: {result.stderr}"
        assert test_content in result.stdout, (
            f"File content mismatch - bind mount not working correctly. "
            f"Expected: {test_content!r}, Got: {result.stdout!r}"
        )

        # Verify writes from container are visible on host
        write_content = "Written from inside container"
        result = exec_in_container(
            container_name, f"echo '{write_content}' > /workspace/container_write_test.txt"
        )
        assert result.returncode == 0, f"Failed to write file in container: {result.stderr}"

        write_test_file = test_project / "container_write_test.txt"
        assert (
            write_test_file.exists()
        ), "File written in container not visible on host - bind mount is read-only or broken"
        assert (
            write_content in write_test_file.read_text()
        ), "File content written in container does not match on host"

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_start_idempotent(self, running_container, test_project):
        """Test start is idempotent (running again succeeds)."""
        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0


class TestProjectStop:
    """Test 'boxctl stop' command."""

    def test_stop_running_container(self, test_project):
        """Test stopping a running container."""
        container_name = f"boxctl-{test_project.name}"

        # Start first
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name)

        # Stop
        result = run_abox("stop", cwd=test_project)

        assert result.returncode == 0
        assert not container_is_running(container_name)

    def test_stop_nonexistent_graceful(self, test_project):
        """Test stopping non-existent container succeeds gracefully."""
        # Don't start container, just try to stop
        result = run_abox("stop", cwd=test_project)

        # Should succeed or warn, not fail hard
        assert result.returncode == 0 or "not found" in result.stdout.lower()


class TestProjectRebuild:
    """Test 'boxctl rebuild' command."""

    def test_rebuild_recreates_container(self, test_project):
        """Test rebuild creates a new container."""
        container_name = f"boxctl-{test_project.name}"

        # Start and get original container ID
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name)

        result1 = run_docker("ps", "-qf", f"name=^{container_name}$")
        old_id = result1.stdout.strip()

        # Rebuild
        result = run_abox("rebuild", cwd=test_project, timeout=180)
        assert result.returncode == 0, f"Rebuild failed: {result.stderr}"

        wait_for_container_ready(container_name)

        # Get new container ID
        result2 = run_docker("ps", "-qf", f"name=^{container_name}$")
        new_id = result2.stdout.strip()

        # Should be different container
        assert old_id != new_id, "Container was not recreated"

        # Cleanup
        run_abox("stop", cwd=test_project)


class TestProjectList:
    """Test 'boxctl list' command."""

    def test_list_shows_running_container(self, running_container, test_project):
        """Test list shows running container."""
        result = run_abox("list", cwd=test_project)

        assert result.returncode == 0
        assert running_container in result.stdout or test_project.name in result.stdout


class TestProjectShell:
    """Test 'boxctl shell' command."""

    def test_shell_container_accessible(self, running_container, test_project):
        """Test shell command can access container."""
        # We can't really test interactive shell, but we can test that
        # docker exec works which is what shell uses
        result = exec_in_container(running_container, "whoami")

        assert result.returncode == 0
        assert "abox" in result.stdout


class TestProjectInfo:
    """Test 'boxctl info' command."""

    def test_info_shows_container_details(self, running_container, test_project):
        """Test info shows container details."""
        result = run_abox("info", cwd=test_project)

        assert result.returncode == 0
        # Should show something about the container
        output = result.stdout.lower()
        assert "running" in output or running_container.lower() in output


class TestProjectRemove:
    """Test 'boxctl remove' command."""

    def test_remove_deletes_container(self, test_project):
        """Test remove deletes the container."""
        container_name = f"boxctl-{test_project.name}"

        # Start first
        run_abox("start", cwd=test_project)
        wait_for_container_ready(container_name)

        assert container_exists(container_name)

        # Stop first (required before remove)
        run_abox("stop", cwd=test_project)

        # Remove
        result = run_abox("remove", test_project.name, "yes", cwd=test_project)

        assert result.returncode == 0
        assert not container_exists(container_name)


class TestTrueDinD:
    """True DinD capability tests.

    These tests verify that boxctl containers can perform Docker operations
    themselves - the core value of True DinD architecture.

    Note: Docker socket is only mounted when Docker MCP is enabled.
    These tests enable Docker MCP before starting the container.
    """

    @pytest.fixture
    def docker_enabled_container(self, test_project):
        """Start container with Docker MCP enabled."""
        container_name = f"boxctl-{test_project.name}"

        # Enable Docker MCP to mount the socket
        result = run_abox("mcp", "add", "docker", cwd=test_project)
        assert (
            result.returncode == 0 or "already" in result.stdout.lower()
        ), f"Failed to add Docker MCP: {result.stderr}"

        # Start container
        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"Failed to start container: {result.stderr}"

        ready = wait_for_container_ready(container_name, timeout=60)
        assert ready, "Container failed to become ready"

        yield container_name

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_nested_container_creation(self, docker_enabled_container, test_project):
        """Test that boxctl container can create nested containers.

        This is THE critical True DinD test. It verifies that:
        1. Docker socket is properly mounted in the boxctl container
        2. The container has proper permissions to use Docker
        3. We can actually create and run nested containers

        Without this working, features like 'docker build' inside the
        container would fail.
        """
        # Create a nested container from inside the boxctl container
        nested_container = f"nested-test-{docker_enabled_container}"

        # Run a simple alpine container from inside
        result = exec_in_container(
            docker_enabled_container,
            f"docker run --rm --name {nested_container} alpine:latest echo 'nested-ok'",
        )

        assert result.returncode == 0, (
            f"Failed to create nested container. "
            f"This indicates Docker socket issues in True DinD setup. "
            f"stderr: {result.stderr}"
        )
        assert "nested-ok" in result.stdout, (
            f"Nested container ran but output unexpected. " f"stdout: {result.stdout}"
        )

    def test_nested_docker_build(self, docker_enabled_container, test_project):
        """Test that boxctl container can build Docker images.

        This verifies docker build works inside the boxctl container,
        which is essential for development workflows.
        """
        # Create a simple Dockerfile inside the container
        result = exec_in_container(
            docker_enabled_container,
            "mkdir -p /tmp/build-test && "
            "echo 'FROM alpine:latest' > /tmp/build-test/Dockerfile && "
            "echo 'RUN echo built-ok' >> /tmp/build-test/Dockerfile",
        )
        assert result.returncode == 0, f"Failed to create Dockerfile: {result.stderr}"

        # Build the image
        result = exec_in_container(
            docker_enabled_container, "docker build -t nested-build-test:latest /tmp/build-test"
        )

        assert result.returncode == 0, (
            f"Docker build failed inside container. " f"stderr: {result.stderr}"
        )
        # Docker build output goes to stderr (buildkit progress), not stdout
        build_output = result.stdout + result.stderr
        assert (
            "built-ok" in build_output or "Successfully" in build_output
        ), f"Build output unexpected. stdout: {result.stdout}, stderr: {result.stderr}"

        # Cleanup the built image
        exec_in_container(
            docker_enabled_container, "docker rmi nested-build-test:latest 2>/dev/null || true"
        )

    def test_docker_socket_accessible(self, docker_enabled_container, test_project):
        """Test that Docker socket is accessible in the container."""
        result = exec_in_container(
            docker_enabled_container, "test -S /var/run/docker.sock && echo 'socket-exists'"
        )

        assert result.returncode == 0, (
            f"Docker socket not found at /var/run/docker.sock. " f"stderr: {result.stderr}"
        )
        assert "socket-exists" in result.stdout

        # Verify we can query Docker
        result = exec_in_container(docker_enabled_container, "docker info")
        assert result.returncode == 0, (
            f"Docker info failed - socket may not be usable. " f"stderr: {result.stderr}"
        )


class TestVersionTracking:
    """Test boxctl version tracking in project lifecycle."""

    def test_version_recorded_on_rebuild(self, test_project):
        """Test that agentbox_version is recorded in config after rebuild."""
        container_name = f"boxctl-{test_project.name}"

        # Start the container first
        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"Start failed: {result.stderr}"
        wait_for_container_ready(container_name)

        # Do a rebuild which should update version
        result = run_abox("rebuild", cwd=test_project, timeout=180)
        assert result.returncode == 0, f"Rebuild failed: {result.stderr}"
        wait_for_container_ready(container_name)

        # Check version was recorded in config
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.config import ProjectConfig; "
            "from boxctl import __version__; "
            "config = ProjectConfig(); "
            'print(f"VERSION:{config.boxctl_version}"); '
            'print(f"CURRENT:{__version__}"); '
            'print(f"MATCH:{config.boxctl_version == __version__}")\'',
        )

        assert result.returncode == 0, f"Version check failed: {result.stderr}"
        assert (
            "MATCH:True" in result.stdout
        ), f"Version not updated after rebuild. Output: {result.stdout}"

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_version_outdated_detection(self, running_container, test_project):
        """Test that outdated version is detected correctly."""
        container_name = running_container

        # Manually set an old version in config
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.config import ProjectConfig; "
            "config = ProjectConfig(); "
            'config.boxctl_version = "0.0.1"; '
            "config.save(quiet=True); "
            'print(f"SET:{config.boxctl_version}"); '
            'print(f"OUTDATED:{config.is_version_outdated()}")\'',
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "SET:0.0.1" in result.stdout, f"Failed to set old version. Output: {result.stdout}"
        assert (
            "OUTDATED:True" in result.stdout
        ), f"Expected is_version_outdated to return True. Output: {result.stdout}"

    def test_current_version_not_outdated(self, running_container, test_project):
        """Test that current version is not detected as outdated."""
        container_name = running_container

        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.config import ProjectConfig; "
            "from boxctl import __version__; "
            "config = ProjectConfig(); "
            "config.boxctl_version = __version__; "
            "config.save(quiet=True); "
            'print(f"OUTDATED:{config.is_version_outdated()}")\'',
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OUTDATED:False" in result.stdout
        ), f"Current version should not be outdated. Output: {result.stdout}"


class TestOutdatedEnvironmentWarning:
    """Test outdated environment warning in CLI commands."""

    def test_warn_if_base_outdated_function_exists(self, running_container, test_project):
        """Test that _warn_if_base_outdated function is importable."""
        container_name = running_container

        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.cli.helpers.tmux_ops import _warn_if_base_outdated; "
            'print(f"CALLABLE:{callable(_warn_if_base_outdated)}")\'',
        )

        assert result.returncode == 0, f"Import failed: {result.stderr}"
        assert (
            "CALLABLE:True" in result.stdout
        ), f"_warn_if_base_outdated should be callable. Output: {result.stdout}"

    def test_warning_logic_with_outdated_config(self, running_container, test_project):
        """Test warning is triggered when config version is outdated."""
        container_name = running_container

        # Set old version and verify warning logic would trigger
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.config import ProjectConfig; "
            "from boxctl.container import ContainerManager; "
            "config = ProjectConfig(); "
            'config.boxctl_version = "0.0.1"; '
            "config.save(quiet=True); "
            "manager = ContainerManager(); "
            'base_outdated = manager.is_base_image_outdated("' + container_name + '"); '
            "config_outdated = config.is_version_outdated(); "
            'print(f"CONFIG_OUTDATED:{config_outdated}"); '
            'print(f"WOULD_WARN:{base_outdated or config_outdated}")\'',
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "CONFIG_OUTDATED:True" in result.stdout
        ), f"Config should be outdated. Output: {result.stdout}"
        assert (
            "WOULD_WARN:True" in result.stdout
        ), f"Warning should be triggered. Output: {result.stdout}"

    def test_warning_format_components(self, running_container, test_project):
        """Test warning message format and components."""
        container_name = running_container

        # Verify the warning components exist
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.cli.helpers.tmux_ops import _warn_if_base_outdated; "
            "import inspect; "
            "source = inspect.getsource(_warn_if_base_outdated); "
            "print(f\"HAS_PANEL:{'Panel' in source}\"); "
            "print(f\"HAS_REBASE:{'rebase' in source.lower()}\"); "
            "print(f\"HAS_WARNING:{'warning' in source.lower()}\")'",
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "HAS_PANEL:True" in result.stdout
        ), f"Warning should use Rich Panel. Output: {result.stdout}"
        assert (
            "HAS_REBASE:True" in result.stdout
        ), f"Warning should mention 'rebase' command. Output: {result.stdout}"


class TestRebaseCommand:
    """Test 'abox rebase' command (renamed from rebuild)."""

    def test_rebase_command_exists(self, test_project):
        """Test that rebase command exists and has help."""
        result = run_abox("rebase", "--help", cwd=test_project)

        assert result.returncode == 0, f"rebase --help failed: {result.stderr}"
        # Should have some description
        assert len(result.stdout) > 50, f"Expected help output. Got: {result.stdout}"

    def test_rebase_recreates_container(self, test_project):
        """Test rebase recreates the container with new base image."""
        container_name = f"boxctl-{test_project.name}"

        # Start and get original container ID
        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"Start failed: {result.stderr}"
        wait_for_container_ready(container_name)

        result1 = run_docker("ps", "-qf", f"name=^{container_name}$")
        old_id = result1.stdout.strip()
        assert old_id, "Container should be running"

        # Rebase
        result = run_abox("rebase", cwd=test_project, timeout=180)
        assert result.returncode == 0, f"Rebase failed: {result.stderr}"

        wait_for_container_ready(container_name)

        # Get new container ID
        result2 = run_docker("ps", "-qf", f"name=^{container_name}$")
        new_id = result2.stdout.strip()

        # Should be different container
        assert old_id != new_id, "Container should be recreated after rebase"

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_rebase_updates_version(self, test_project):
        """Test rebase updates the config version."""
        container_name = f"boxctl-{test_project.name}"

        # Start first
        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"Start failed: {result.stderr}"
        wait_for_container_ready(container_name)

        # Set old version
        exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.config import ProjectConfig; "
            "config = ProjectConfig(); "
            'config.boxctl_version = "0.0.1"; '
            "config.save(quiet=True)'",
        )

        # Verify old version set
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.config import ProjectConfig; "
            "print(ProjectConfig().boxctl_version)'",
        )
        assert "0.0.1" in result.stdout, "Old version should be set"

        # Rebase
        result = run_abox("rebase", cwd=test_project, timeout=180)
        assert result.returncode == 0, f"Rebase failed: {result.stderr}"
        wait_for_container_ready(container_name)

        # Check version was updated
        result = exec_in_container(
            container_name,
            "python3 -c '"
            "from boxctl.config import ProjectConfig; "
            "from boxctl import __version__; "
            "config = ProjectConfig(); "
            'print(f"VERSION:{config.boxctl_version}"); '
            'print(f"MATCH:{config.boxctl_version == __version__}")\'',
        )

        assert result.returncode == 0, f"Version check failed: {result.stderr}"
        assert (
            "MATCH:True" in result.stdout
        ), f"Version should match current after rebase. Output: {result.stdout}"

        # Cleanup
        run_abox("stop", cwd=test_project)


class TestOutdatedBaseImageDetectionIntegration:
    """Integration tests for base image outdated detection in real scenarios."""

    def test_fresh_container_not_outdated(self, test_project):
        """Test that a freshly created container is not marked as outdated."""
        container_name = f"boxctl-{test_project.name}"

        # Start fresh container
        result = run_abox("start", cwd=test_project)
        assert result.returncode == 0, f"Start failed: {result.stderr}"
        wait_for_container_ready(container_name)

        # Check if marked as outdated
        result = exec_in_container(
            container_name,
            f"python3 -c '"
            "from boxctl.container import ContainerManager; "
            f"m = ContainerManager(); "
            f'print(f"OUTDATED:{{m.is_base_image_outdated("{container_name}")}}")\'',
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        # A fresh container should NOT be outdated
        assert (
            "OUTDATED:False" in result.stdout
        ), f"Fresh container should not be marked as outdated. Output: {result.stdout}"

        # Cleanup
        run_abox("stop", cwd=test_project)

    def test_container_image_id_accessible(self, running_container, test_project):
        """Test that we can access container's image ID for comparison."""
        container_name = running_container

        result = exec_in_container(
            container_name,
            f"python3 -c '"
            "import docker; "
            "client = docker.from_env(); "
            f'container = client.containers.get("{container_name}"); '
            'image_id = container.attrs.get("Image", ""); '
            'print(f"HAS_IMAGE_ID:{{bool(image_id)}}"); '
            'print(f"ID_PREFIX:{{image_id[:12] if image_id else None}}")\'',
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "HAS_IMAGE_ID:True" in result.stdout
        ), f"Should be able to get container image ID. Output: {result.stdout}"
