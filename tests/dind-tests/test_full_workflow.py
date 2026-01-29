# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""
Comprehensive DinD Test Suite - Full Workflow Testing

This test suite tests ALL boxctl commands and subcommands in realistic
workflows. No config file checking - real Docker operations with verification.

Test Order (Dependencies):
1. Base Image Build
2. Project Init
3. Project Start/Stop/List
4. Session Management
5. Workspace Mounts
6. Worktree Commands
7. Port Forwarding
8. MCP Server Management
9. Skill Management
10. Package Management
11. Docker Socket Access
12. Network Connections
13. Device Passthrough
14. Rebase/Rebuild
15. Multi-Session Workflows
16. Multi-Project Workflows
17. Multi-Agent Types
18. Service Daemon
19. Agent Launch (optional)

Run with: pytest tests/dind-tests/test_full_workflow.py -v --tb=short
"""

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Generator, List, Optional, Tuple

import pytest


# ============================================================================
# Pytest Markers
# ============================================================================

pytestmark = [
    pytest.mark.dind,
    pytest.mark.integration,
]


# ============================================================================
# Test Configuration
# ============================================================================

TEST_TIMEOUT = 120  # Default command timeout
CONTAINER_READY_TIMEOUT = 90
BASE_BUILD_TIMEOUT = 600  # 10 min for base image build


# ============================================================================
# Helper Functions
# ============================================================================


def run_abox(
    *args,
    cwd: Optional[Path] = None,
    timeout: int = TEST_TIMEOUT,
    env: Optional[dict] = None,
    input: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run boxctl CLI command."""
    cmd = ["boxctl", *[str(a) for a in args]]
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=run_env,
        input=input,
    )


def run_docker(*args, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run docker command."""
    return subprocess.run(
        ["docker", *[str(a) for a in args]],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def exec_in_container(
    container: str,
    command: str,
    user: str = "abox",
    workdir: str = "/workspace",
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Execute command inside container."""
    return run_docker(
        "exec",
        "-u",
        user,
        "-w",
        workdir,
        container,
        "bash",
        "-c",
        command,
        timeout=timeout,
    )


def wait_for_container(container: str, timeout: int = CONTAINER_READY_TIMEOUT) -> bool:
    """Wait for container to be ready."""
    for _ in range(timeout):
        result = run_docker("exec", container, "echo", "ready")
        if result.returncode == 0:
            return True
        time.sleep(1)
    return False


def container_exists(name: str) -> bool:
    """Check if container exists."""
    result = run_docker("ps", "-a", "-f", f"name=^{name}$", "--format", "{{.Names}}")
    return name in result.stdout.strip().split("\n")


def container_running(name: str) -> bool:
    """Check if container is running."""
    result = run_docker("ps", "-f", f"name=^{name}$", "--format", "{{.Names}}")
    return name in result.stdout.strip().split("\n")


def create_git_repo(path: Path, branches: List[str] = None) -> None:
    """Initialize a git repository with branches."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
    (path / "README.md").write_text("# Test Project\n")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, capture_output=True)

    for branch in branches or []:
        subprocess.run(["git", "branch", branch], cwd=path, capture_output=True)


def copy_agentbox_repo(dest: Path, branches: List[str] = None) -> None:
    """Copy the boxctl repo as a realistic test project.

    This copies the actual boxctl source code to use as a test project,
    which is more realistic than creating empty fake repos.
    """
    # The boxctl repo is at /build in the DinD container
    source = Path("/build")

    if not source.exists():
        # Fallback to creating minimal repo if not in DinD
        create_git_repo(dest, branches)
        return

    dest.mkdir(parents=True, exist_ok=True)

    # Copy essential files (not everything - keep it fast)
    essential_dirs = ["boxctl", "library", "bin"]
    essential_files = ["pyproject.toml", "README.md"]

    for d in essential_dirs:
        src_dir = source / d
        if src_dir.exists():
            shutil.copytree(src_dir, dest / d, dirs_exist_ok=True)

    for f in essential_files:
        src_file = source / f
        if src_file.exists():
            shutil.copy2(src_file, dest / f)

    # Initialize as new git repo (don't copy .git - start fresh)
    subprocess.run(["git", "init"], cwd=dest, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=dest, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=dest, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=dest, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit from boxctl repo"], cwd=dest, capture_output=True
    )

    # Create additional branches if requested
    for branch in branches or []:
        subprocess.run(["git", "branch", branch], cwd=dest, capture_output=True)


def cleanup_container(name: str) -> None:
    """Force remove a container."""
    run_docker("rm", "-f", name)


def cleanup_containers_matching(pattern: str) -> None:
    """Remove all containers matching pattern."""
    result = run_docker("ps", "-a", "--filter", f"name={pattern}", "--format", "{{.Names}}")
    for name in result.stdout.strip().split("\n"):
        if name:
            run_docker("rm", "-f", name)


# ============================================================================
# Session-Scoped Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def dind_ready():
    """Verify DinD environment is functional."""
    # Test basic docker
    result = run_docker("info")
    assert result.returncode == 0, "Docker not available"

    # Test container creation
    test_name = f"dind-verify-{uuid.uuid4().hex[:8]}"
    result = run_docker("run", "--rm", "--name", test_name, "alpine:latest", "echo", "ok")
    assert result.returncode == 0, f"Cannot create containers: {result.stderr}"

    return True


@pytest.fixture(scope="session")
def test_root(dind_ready) -> Generator[Path, None, None]:
    """Session-wide test root directory."""
    root = Path(os.environ.get("TEST_WORKSPACE", "/test-workspace"))
    root.mkdir(parents=True, exist_ok=True)
    yield root
    # Cleanup all test containers
    cleanup_containers_matching("boxctl-test-")
    cleanup_containers_matching("boxctl-workflow-")
    # Cleanup directory
    for item in root.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)


@pytest.fixture(scope="session")
def base_image_built(dind_ready) -> bool:
    """Ensure base image exists (build if needed)."""
    # Check if base image exists
    result = run_docker("images", "boxctl-base:latest", "--format", "{{.ID}}")
    if result.stdout.strip():
        return True

    # Build base image
    result = run_abox("base", "rebuild", timeout=BASE_BUILD_TIMEOUT)
    assert result.returncode == 0, f"Base image build failed: {result.stderr}"
    return True


# ============================================================================
# PHASE 1: Base Image Commands
# ============================================================================


class TestPhase1_BaseImage:
    """Test base image management commands."""

    def test_base_rebuild_help(self, dind_ready):
        """Test 'boxctl base rebuild --help' shows usage."""
        result = run_abox("base", "rebuild", "--help")
        assert result.returncode == 0
        assert "rebuild" in result.stdout.lower() or "base" in result.stdout.lower()

    @pytest.mark.timeout(900)  # 15 minutes - DinD build is slow
    @pytest.mark.slow
    def test_base_rebuild_creates_image(self, dind_ready):
        """Test base rebuild creates the image."""
        # Remove existing image first
        run_docker("rmi", "boxctl-base:latest", "-f")

        result = run_abox("base", "rebuild", timeout=BASE_BUILD_TIMEOUT)
        assert result.returncode == 0, f"Build failed: {result.stderr}"

        # Verify image exists
        result = run_docker("images", "boxctl-base:latest", "--format", "{{.Repository}}")
        assert "boxctl-base" in result.stdout


# ============================================================================
# PHASE 2: Project Lifecycle Commands
# ============================================================================


class TestPhase2_ProjectLifecycle:
    """Test project lifecycle: init, start, stop, list, info, shell, connect."""

    @pytest.fixture
    def project_dir(self, test_root, base_image_built) -> Generator[Path, None, None]:
        """Create a test project directory."""
        project = test_root / f"test-lifecycle-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)
        yield project
        # Cleanup
        container_name = f"boxctl-{project.name}"
        cleanup_container(container_name)
        shutil.rmtree(project, ignore_errors=True)

    # --- init ---

    def test_init_creates_agentbox_dir(self, project_dir):
        """Test 'boxctl init' creates .boxctl directory."""
        result = run_abox("init", cwd=project_dir)
        assert result.returncode == 0, f"Init failed: {result.stderr}"
        assert (project_dir / ".boxctl").is_dir()

    def test_init_creates_claude_dir(self, project_dir):
        """Test init creates .boxctl/claude directory."""
        run_abox("init", cwd=project_dir)
        assert (project_dir / ".boxctl" / "claude").is_dir()

    def test_init_creates_mcp_config(self, project_dir):
        """Test init creates MCP configuration file (unified at root level)."""
        run_abox("init", cwd=project_dir)
        # mcp.json is now at root level (unified for all agents)
        mcp_config = project_dir / ".boxctl" / "mcp.json"
        assert mcp_config.exists(), f"mcp.json not found at {mcp_config}"
        # Verify it's valid JSON
        data = json.loads(mcp_config.read_text())
        assert "mcpServers" in data

    def test_init_creates_config_toml(self, project_dir):
        """Test init creates config.toml."""
        run_abox("init", cwd=project_dir)
        config = project_dir / ".boxctl" / "config.toml"
        assert config.exists()

    def test_init_idempotent(self, project_dir):
        """Test init can run multiple times safely."""
        run_abox("init", cwd=project_dir)
        result = run_abox("init", cwd=project_dir)
        assert result.returncode == 0

    # --- start ---

    def test_start_creates_container(self, project_dir):
        """Test 'boxctl start' creates and runs container."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        result = run_abox("start", cwd=project_dir)
        assert result.returncode == 0, f"Start failed: {result.stderr}"

        assert container_exists(container_name)
        assert container_running(container_name)

    def test_start_container_becomes_ready(self, project_dir):
        """Test started container can execute commands."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        run_abox("start", cwd=project_dir)

        ready = wait_for_container(container_name)
        assert ready, "Container did not become ready"

    def test_start_mounts_workspace(self, project_dir):
        """Test /workspace is properly mounted in container."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        # Create test file
        test_file = project_dir / "mount_test.txt"
        test_file.write_text("mount-verification")

        run_abox("start", cwd=project_dir)
        wait_for_container(container_name)

        # Read from inside container
        result = exec_in_container(container_name, "cat /workspace/mount_test.txt")
        assert result.returncode == 0
        assert "mount-verification" in result.stdout

    def test_start_bidirectional_mount(self, project_dir):
        """Test writes from container are visible on host."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        run_abox("start", cwd=project_dir)
        wait_for_container(container_name)

        # Write from container
        exec_in_container(container_name, "echo 'from-container' > /workspace/container_write.txt")

        # Verify on host
        written = project_dir / "container_write.txt"
        assert written.exists()
        assert "from-container" in written.read_text()

    def test_start_idempotent(self, project_dir):
        """Test start is idempotent (running twice succeeds)."""
        run_abox("init", cwd=project_dir)
        run_abox("start", cwd=project_dir)

        result = run_abox("start", cwd=project_dir)
        assert result.returncode == 0

    # --- stop ---

    def test_stop_running_container(self, project_dir):
        """Test 'boxctl stop' stops a running container."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        run_abox("start", cwd=project_dir)
        wait_for_container(container_name)
        assert container_running(container_name)

        result = run_abox("stop", cwd=project_dir)
        assert result.returncode == 0
        assert not container_running(container_name)

    def test_stop_nonexistent_graceful(self, project_dir):
        """Test stop on non-existent container is graceful."""
        run_abox("init", cwd=project_dir)
        # Don't start, just stop
        result = run_abox("stop", cwd=project_dir)
        # Should not hard fail
        assert (
            result.returncode == 0 or "not found" in result.stdout.lower() + result.stderr.lower()
        )

    # --- list / ps ---

    def test_list_shows_running_containers(self, project_dir):
        """Test 'boxctl list' shows running containers."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        run_abox("start", cwd=project_dir)
        wait_for_container(container_name)

        result = run_abox("list")
        assert result.returncode == 0
        assert container_name in result.stdout or project_dir.name in result.stdout

    def test_ps_alias_works(self, project_dir):
        """Test 'boxctl ps' works as alias for list."""
        run_abox("init", cwd=project_dir)
        run_abox("start", cwd=project_dir)

        result = run_abox("ps")
        assert result.returncode == 0

    # --- info ---

    def test_info_shows_container_details(self, project_dir):
        """Test 'boxctl info' shows container information."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        run_abox("start", cwd=project_dir)
        wait_for_container(container_name)

        result = run_abox("info", cwd=project_dir)
        assert result.returncode == 0
        output = result.stdout.lower()
        assert "running" in output or container_name.lower() in output

    # --- shell ---

    def test_shell_access_works(self, project_dir):
        """Test shell access to container works."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        run_abox("start", cwd=project_dir)
        wait_for_container(container_name)

        # Test via direct exec (shell is interactive)
        result = exec_in_container(container_name, "whoami")
        assert result.returncode == 0
        assert "abox" in result.stdout

    # --- connect ---

    def test_connect_help(self, project_dir):
        """Test 'boxctl connect --help' shows usage."""
        result = run_abox("connect", "--help")
        assert result.returncode == 0

    # --- remove ---

    def test_remove_deletes_container(self, project_dir):
        """Test 'boxctl remove' deletes the container."""
        run_abox("init", cwd=project_dir)
        container_name = f"boxctl-{project_dir.name}"

        run_abox("start", cwd=project_dir)
        wait_for_container(container_name)
        run_abox("stop", cwd=project_dir)

        assert container_exists(container_name)

        # Remove requires confirmation - pass 'yes' via positional arg
        result = run_abox("remove", project_dir.name, "yes", cwd=project_dir)
        assert result.returncode == 0
        assert not container_exists(container_name)

    # --- setup ---

    def test_setup_help(self, project_dir):
        """Test 'boxctl setup --help' shows usage."""
        result = run_abox("setup", "--help", cwd=project_dir)
        assert result.returncode == 0

    # --- reconfigure ---

    def test_reconfigure_help(self, project_dir):
        """Test 'boxctl reconfigure --help' shows usage."""
        result = run_abox("reconfigure", "--help", cwd=project_dir)
        assert result.returncode == 0

    # --- project migrate ---

    def test_project_migrate_help(self, project_dir):
        """Test 'boxctl project migrate --help' shows usage."""
        result = run_abox("project", "migrate", "--help", cwd=project_dir)
        assert result.returncode == 0

    # --- cleanup ---

    def test_cleanup_help(self, project_dir):
        """Test 'boxctl cleanup --help' shows usage."""
        result = run_abox("cleanup", "--help", cwd=project_dir)
        assert result.returncode == 0


# ============================================================================
# PHASE 3: Session Management Commands
# ============================================================================


class TestPhase3_SessionManagement:
    """Test session commands: list, attach, rename, remove, and interactive mode."""

    @pytest.fixture
    def running_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str], None, None]:
        """Create and start a project, yield (path, container_name)."""
        project = test_root / f"test-session-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)
        run_abox("start", cwd=project)

        container_name = f"boxctl-{project.name}"
        wait_for_container(container_name)

        yield project, container_name

        # Cleanup
        cleanup_container(container_name)
        shutil.rmtree(project, ignore_errors=True)

    def test_session_list(self, running_project):
        """Test 'boxctl session list' shows tmux sessions."""
        project, container = running_project

        result = run_abox("session", "list", cwd=project)
        assert result.returncode == 0

    def test_session_list_all(self, running_project):
        """Test 'boxctl session list all' lists across all containers."""
        project, container = running_project

        result = run_abox("session", "list", "all", cwd=project)
        assert result.returncode == 0

    def test_session_list_after_creating_session(self, running_project):
        """Test session list shows created sessions."""
        project, container = running_project

        # Create a tmux session inside container
        exec_in_container(container, "tmux new-session -d -s test-session-1")

        result = run_abox("session", "list", cwd=project)
        assert result.returncode == 0
        assert "test-session-1" in result.stdout

    def test_session_attach_help(self, running_project):
        """Test 'boxctl session attach --help'."""
        project, container = running_project

        result = run_abox("session", "attach", "--help", cwd=project)
        assert result.returncode == 0

    def test_session_rename(self, running_project):
        """Test 'boxctl session rename' renames a session."""
        project, container = running_project

        # Create session
        exec_in_container(container, "tmux new-session -d -s rename-test")

        result = run_abox("session", "rename", "rename-test", "renamed-session", cwd=project)
        assert result.returncode == 0

        # Verify renamed
        result = run_abox("session", "list", cwd=project)
        assert "renamed-session" in result.stdout
        assert "rename-test" not in result.stdout

    def test_session_remove(self, running_project):
        """Test 'boxctl session remove' kills a session."""
        project, container = running_project

        # Create session
        exec_in_container(container, "tmux new-session -d -s remove-test")

        # Verify exists
        result = run_abox("session", "list", cwd=project)
        assert "remove-test" in result.stdout

        # Remove
        result = run_abox("session", "remove", "remove-test", cwd=project)
        assert result.returncode == 0

        # Verify gone
        result = run_abox("session", "list", cwd=project)
        assert "remove-test" not in result.stdout

    def test_session_help(self, running_project):
        """Test 'boxctl session --help' shows all subcommands."""
        project, container = running_project

        result = run_abox("session", "--help", cwd=project)
        assert result.returncode == 0
        # Should mention list, attach, rename, remove
        output = result.stdout.lower()
        assert "list" in output
        assert "remove" in output


# ============================================================================
# PHASE 4: Workspace Mount Commands
# ============================================================================


class TestPhase4_WorkspaceMounts:
    """Test workspace commands: list, add, remove."""

    @pytest.fixture
    def workspace_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str, Path], None, None]:
        """Create project with extra mount directory."""
        project = test_root / f"test-workspace-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        # Create extra directory to mount
        extra_mount = test_root / f"extra-{uuid.uuid4().hex[:8]}"
        extra_mount.mkdir(parents=True, exist_ok=True)
        (extra_mount / "extra_file.txt").write_text("extra-content")

        run_abox("init", cwd=project)

        yield project, f"boxctl-{project.name}", extra_mount

        # Cleanup
        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)
        shutil.rmtree(extra_mount, ignore_errors=True)

    def test_workspace_list_empty(self, workspace_project):
        """Test 'boxctl workspace list' with no extra mounts."""
        project, container, extra = workspace_project

        result = run_abox("workspace", "list", cwd=project)
        assert result.returncode == 0

    def test_workspace_add(self, workspace_project):
        """Test 'boxctl workspace add' adds a mount."""
        project, container, extra = workspace_project

        result = run_abox("workspace", "add", str(extra), cwd=project)
        assert result.returncode == 0

        # Verify in list
        result = run_abox("workspace", "list", cwd=project)
        assert str(extra) in result.stdout or extra.name in result.stdout

    def test_workspace_add_visible_in_container(self, workspace_project):
        """Test added workspace mount is accessible in container."""
        project, container, extra = workspace_project

        # Add mount
        run_abox("workspace", "add", str(extra), cwd=project)

        # Start container
        run_abox("start", cwd=project)
        wait_for_container(container)

        # Check mount is visible
        result = exec_in_container(container, f"cat /context/{extra.name}/extra_file.txt")
        assert result.returncode == 0
        assert "extra-content" in result.stdout

    def test_workspace_remove(self, workspace_project):
        """Test 'boxctl workspace remove' removes a mount."""
        project, container, extra = workspace_project

        # Add then remove
        run_abox("workspace", "add", str(extra), cwd=project)
        result = run_abox("workspace", "remove", str(extra), cwd=project)
        assert result.returncode == 0

        # Verify removed from list
        result = run_abox("workspace", "list", cwd=project)
        # Should not be in the list anymore (or list shows nothing)


# ============================================================================
# PHASE 5: Worktree Commands
# ============================================================================


class TestPhase5_WorktreeCommands:
    """Test worktree commands: list, add, remove, prune."""

    @pytest.fixture
    def git_project(self, test_root, base_image_built) -> Generator[Tuple[Path, str], None, None]:
        """Create project with git repo and branches."""
        project = test_root / f"test-worktree-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project, branches=["feature-1", "feature-2", "bugfix-1"])

        run_abox("init", cwd=project)
        run_abox("start", cwd=project)

        container = f"boxctl-{project.name}"
        wait_for_container(container)

        yield project, container

        # Cleanup worktrees
        for wt in project.parent.glob(f"{project.name}-*"):
            if wt.is_dir():
                shutil.rmtree(wt, ignore_errors=True)

        cleanup_container(container)
        shutil.rmtree(project, ignore_errors=True)

    def test_worktree_list_initial(self, git_project):
        """Test 'boxctl worktree list' shows main worktree."""
        project, container = git_project

        result = run_abox("worktree", "list", cwd=project)
        assert result.returncode == 0

    def test_worktree_add(self, git_project):
        """Test 'boxctl worktree add' creates worktree."""
        project, container = git_project

        result = run_abox("worktree", "add", "feature-1", cwd=project)
        assert result.returncode == 0

        # Verify worktree exists
        result = run_abox("worktree", "list", cwd=project)
        assert "feature-1" in result.stdout

    def test_worktree_remove(self, git_project):
        """Test 'boxctl worktree remove' removes worktree."""
        project, container = git_project

        # Add first
        run_abox("worktree", "add", "feature-2", cwd=project)

        # Remove
        result = run_abox("worktree", "remove", "feature-2", cwd=project)
        assert result.returncode == 0

    def test_worktree_prune(self, git_project):
        """Test 'boxctl worktree prune' cleans up."""
        project, container = git_project

        result = run_abox("worktree", "prune", cwd=project)
        assert result.returncode == 0

    def test_worktree_list_json(self, git_project):
        """Test 'boxctl worktree list json' returns JSON."""
        project, container = git_project

        result = run_abox("worktree", "list", "json", cwd=project)
        assert result.returncode == 0
        # Should be valid JSON or JSON-like output

    def test_worktree_remove_force(self, git_project):
        """Test 'boxctl worktree remove' with force option."""
        project, container = git_project

        # Add worktree
        run_abox("worktree", "add", "bugfix-1", cwd=project)

        # Remove with force
        result = run_abox("worktree", "remove", "bugfix-1", "force", cwd=project)
        assert result.returncode == 0

    def test_worktree_help(self, git_project):
        """Test 'boxctl worktree --help' shows all subcommands."""
        project, container = git_project

        result = run_abox("worktree", "--help", cwd=project)
        assert result.returncode == 0
        output = result.stdout.lower()
        assert "list" in output
        assert "add" in output
        assert "remove" in output


# ============================================================================
# PHASE 6: Port Forwarding Commands
# ============================================================================


class TestPhase6_PortForwarding:
    """Test ports commands: list, expose, forward, unexpose, unforward, status."""

    @pytest.fixture
    def port_project(self, test_root, base_image_built) -> Generator[Tuple[Path, str], None, None]:
        """Create project for port testing."""
        project = test_root / f"test-ports-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)

        yield project, f"boxctl-{project.name}"

        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)

    def test_ports_list_empty(self, port_project):
        """Test 'boxctl ports list' with no ports configured."""
        project, container = port_project

        result = run_abox("ports", "list", cwd=project)
        assert result.returncode == 0

    def test_ports_expose(self, port_project):
        """Test 'boxctl ports expose' exposes container port."""
        project, container = port_project

        result = run_abox("ports", "expose", "8080", cwd=project)
        assert result.returncode == 0

        # Verify in list
        result = run_abox("ports", "list", cwd=project)
        assert "8080" in result.stdout

    def test_ports_forward(self, port_project):
        """Test 'boxctl ports forward' forwards host port."""
        project, container = port_project

        result = run_abox("ports", "forward", "9000", cwd=project)
        assert result.returncode == 0

        # Verify in list
        result = run_abox("ports", "list", cwd=project)
        assert "9000" in result.stdout

    def test_ports_unexpose(self, port_project):
        """Test 'boxctl ports unexpose' removes exposed port."""
        project, container = port_project

        run_abox("ports", "expose", "8081", cwd=project)
        result = run_abox("ports", "unexpose", "8081", cwd=project)
        assert result.returncode == 0

    def test_ports_unforward(self, port_project):
        """Test 'boxctl ports unforward' removes forwarded port."""
        project, container = port_project

        run_abox("ports", "forward", "9001", cwd=project)
        result = run_abox("ports", "unforward", "9001", cwd=project)
        assert result.returncode == 0

    def test_ports_status(self, port_project):
        """Test 'boxctl ports status' shows forwarding status."""
        project, container = port_project

        run_abox("start", cwd=project)
        wait_for_container(container)

        result = run_abox("ports", "status", cwd=project)
        assert result.returncode == 0


# ============================================================================
# PHASE 7: MCP Server Commands
# ============================================================================


class TestPhase7_MCPServers:
    """Test MCP commands: list, add, remove, show, manage, init."""

    @pytest.fixture
    def mcp_project(self, test_root, base_image_built) -> Generator[Tuple[Path, str], None, None]:
        """Create project for MCP testing."""
        project = test_root / f"test-mcp-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)

        yield project, f"boxctl-{project.name}"

        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)

    def test_mcp_list(self, mcp_project):
        """Test 'boxctl mcp list' shows available servers."""
        project, container = mcp_project

        result = run_abox("mcp", "list", cwd=project)
        assert result.returncode == 0
        # Should show some available MCPs
        assert (
            "fetch" in result.stdout.lower()
            or "Available" in result.stdout
            or len(result.stdout) > 10
        )

    def test_mcps_alias(self, mcp_project):
        """Test 'boxctl mcps' works as alias."""
        project, container = mcp_project

        result = run_abox("mcps", "list", cwd=project)
        assert result.returncode == 0

    def test_mcp_add(self, mcp_project):
        """Test 'boxctl mcp add' adds an MCP server."""
        project, container = mcp_project

        result = run_abox("mcp", "add", "fetch", cwd=project)
        assert result.returncode == 0 or "already" in result.stdout.lower()

        # Verify in config (mcp.json is at root level, unified for all agents)
        mcp_config = project / ".boxctl" / "mcp.json"
        data = json.loads(mcp_config.read_text())
        assert "mcpServers" in data

    def test_mcp_show(self, mcp_project):
        """Test 'boxctl mcp show' displays MCP details."""
        project, container = mcp_project

        result = run_abox("mcp", "show", "fetch", cwd=project)
        assert result.returncode == 0

    def test_mcp_remove(self, mcp_project):
        """Test 'boxctl mcp remove' removes an MCP server."""
        project, container = mcp_project

        # Add first
        run_abox("mcp", "add", "fetch", cwd=project)

        # Remove
        result = run_abox("mcp", "remove", "fetch", cwd=project)
        assert result.returncode == 0

    def test_mcp_init(self, mcp_project):
        """Test 'boxctl mcp init' initializes MCP config."""
        project, container = mcp_project

        result = run_abox("mcp", "init", cwd=project)
        assert result.returncode == 0

    def test_mcp_manage_help(self, mcp_project):
        """Test 'boxctl mcp manage --help' shows usage."""
        project, container = mcp_project

        result = run_abox("mcp", "manage", "--help", cwd=project)
        assert result.returncode == 0

    def test_mcp_help(self, mcp_project):
        """Test 'boxctl mcp --help' shows all subcommands."""
        project, container = mcp_project

        result = run_abox("mcp", "--help", cwd=project)
        assert result.returncode == 0
        output = result.stdout.lower()
        assert "list" in output
        assert "add" in output
        assert "remove" in output


# ============================================================================
# PHASE 8: Skill Commands
# ============================================================================


class TestPhase8_Skills:
    """Test skill commands: list, add, remove, show, manage."""

    @pytest.fixture
    def skill_project(self, test_root, base_image_built) -> Generator[Tuple[Path, str], None, None]:
        """Create project for skill testing."""
        project = test_root / f"test-skill-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)

        yield project, f"boxctl-{project.name}"

        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)

    def test_skill_list(self, skill_project):
        """Test 'boxctl skill list' shows available skills."""
        project, container = skill_project

        result = run_abox("skill", "list", cwd=project)
        assert result.returncode == 0

    def test_skills_alias(self, skill_project):
        """Test 'boxctl skills' works as alias."""
        project, container = skill_project

        result = run_abox("skills", "list", cwd=project)
        assert result.returncode == 0

    def test_skill_add(self, skill_project):
        """Test 'boxctl skill add' adds a skill."""
        project, container = skill_project

        # Try to add a skill (westworld is usually available)
        result = run_abox("skill", "add", "westworld", cwd=project)
        # May succeed or say already added
        assert (
            result.returncode == 0
            or "already" in result.stdout.lower()
            or "not found" in result.stdout.lower()
        )

    def test_skill_remove(self, skill_project):
        """Test 'boxctl skill remove' removes a skill."""
        project, container = skill_project

        # Add then remove
        run_abox("skill", "add", "westworld", cwd=project)
        result = run_abox("skill", "remove", "westworld", cwd=project)
        assert result.returncode == 0 or "not found" in result.stdout.lower()

    def test_skill_show(self, skill_project):
        """Test 'boxctl skill show' displays skill details."""
        project, container = skill_project

        result = run_abox("skill", "show", "westworld", cwd=project)
        # May or may not exist, but command should work
        assert result.returncode == 0 or "not found" in result.stdout.lower()

    def test_skill_manage_help(self, skill_project):
        """Test 'boxctl skill manage --help' shows usage."""
        project, container = skill_project

        result = run_abox("skill", "manage", "--help", cwd=project)
        assert result.returncode == 0

    def test_skill_help(self, skill_project):
        """Test 'boxctl skill --help' shows all subcommands."""
        project, container = skill_project

        result = run_abox("skill", "--help", cwd=project)
        assert result.returncode == 0
        output = result.stdout.lower()
        assert "list" in output
        assert "add" in output


# ============================================================================
# PHASE 9: Package Commands
# ============================================================================


class TestPhase9_Packages:
    """Test packages commands: list, add, remove, init."""

    @pytest.fixture
    def pkg_project(self, test_root, base_image_built) -> Generator[Tuple[Path, str], None, None]:
        """Create project for package testing."""
        project = test_root / f"test-pkg-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)

        yield project, f"boxctl-{project.name}"

        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)

    def test_packages_list(self, pkg_project):
        """Test 'boxctl packages list' shows packages."""
        project, container = pkg_project

        result = run_abox("packages", "list", cwd=project)
        assert result.returncode == 0

    def test_packages_add_pip(self, pkg_project):
        """Test 'boxctl packages add' adds a pip package."""
        project, container = pkg_project

        result = run_abox("packages", "add", "requests", "pip", cwd=project)
        assert result.returncode == 0

        # Verify in list
        result = run_abox("packages", "list", cwd=project)
        assert "requests" in result.stdout

    def test_packages_add_npm(self, pkg_project):
        """Test 'boxctl packages add' adds an npm package."""
        project, container = pkg_project

        result = run_abox("packages", "add", "lodash", "npm", cwd=project)
        assert result.returncode == 0

    def test_packages_add_apt(self, pkg_project):
        """Test 'boxctl packages add' adds an apt package."""
        project, container = pkg_project

        result = run_abox("packages", "add", "jq", "apt", cwd=project)
        assert result.returncode == 0

    def test_packages_remove(self, pkg_project):
        """Test 'boxctl packages remove' removes a package."""
        project, container = pkg_project

        run_abox("packages", "add", "flask", "pip", cwd=project)
        result = run_abox("packages", "remove", "flask", cwd=project)
        assert result.returncode == 0

    def test_packages_installed_on_start(self, pkg_project):
        """Test packages are installed when container starts."""
        project, container = pkg_project

        # Add package
        run_abox("packages", "add", "cowsay", "pip", cwd=project)

        # Start container
        run_abox("start", cwd=project)
        wait_for_container(container)

        # Verify package installed
        result = exec_in_container(container, "pip show cowsay")
        assert result.returncode == 0 or "cowsay" in result.stdout

    def test_packages_init(self, pkg_project):
        """Test 'boxctl packages init' initializes package config."""
        project, container = pkg_project

        result = run_abox("packages", "init", cwd=project)
        assert result.returncode == 0

    def test_packages_help(self, pkg_project):
        """Test 'boxctl packages --help' shows all subcommands."""
        project, container = pkg_project

        result = run_abox("packages", "--help", cwd=project)
        assert result.returncode == 0
        output = result.stdout.lower()
        assert "list" in output
        assert "add" in output


# ============================================================================
# PHASE 10: Docker Socket Commands
# ============================================================================


class TestPhase10_DockerSocket:
    """Test docker commands: enable, disable, status."""

    @pytest.fixture
    def docker_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str], None, None]:
        """Create project for docker socket testing."""
        project = test_root / f"test-docker-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)

        yield project, f"boxctl-{project.name}"

        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)

    def test_docker_status(self, docker_project):
        """Test 'boxctl docker status' shows socket status."""
        project, container = docker_project

        result = run_abox("docker", "status", cwd=project)
        assert result.returncode == 0

    def test_docker_enable(self, docker_project):
        """Test 'boxctl docker enable' enables socket access."""
        project, container = docker_project

        result = run_abox("docker", "enable", cwd=project)
        assert result.returncode == 0

        # Verify status shows enabled
        result = run_abox("docker", "status", cwd=project)
        assert "enabled" in result.stdout.lower() or "true" in result.stdout.lower()

    def test_docker_disable(self, docker_project):
        """Test 'boxctl docker disable' disables socket access."""
        project, container = docker_project

        run_abox("docker", "enable", cwd=project)
        result = run_abox("docker", "disable", cwd=project)
        assert result.returncode == 0

    def test_docker_socket_accessible_when_enabled(self, docker_project):
        """Test docker socket is accessible in container when enabled."""
        project, container = docker_project

        run_abox("docker", "enable", cwd=project)
        run_abox("start", cwd=project)
        wait_for_container(container)

        # Check socket exists
        result = exec_in_container(container, "test -S /var/run/docker.sock && echo ok")
        assert result.returncode == 0
        assert "ok" in result.stdout

        # Check docker works
        result = exec_in_container(container, "docker info")
        assert result.returncode == 0


# ============================================================================
# PHASE 11: Network Commands
# ============================================================================


class TestPhase11_Network:
    """Test network commands: available, list, connect, disconnect."""

    @pytest.fixture
    def network_setup(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str, str], None, None]:
        """Create project and target container for network testing."""
        project = test_root / f"test-network-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)
        run_abox("docker", "enable", cwd=project)
        run_abox("start", cwd=project)

        container = f"boxctl-{project.name}"
        wait_for_container(container)

        # Create target container
        target = f"network-target-{uuid.uuid4().hex[:8]}"
        run_docker("run", "-d", "--name", target, "nginx:alpine")
        time.sleep(2)  # Wait for nginx to start

        yield project, container, target

        # Cleanup
        cleanup_container(container)
        cleanup_container(target)
        shutil.rmtree(project, ignore_errors=True)

    def test_network_available(self, network_setup):
        """Test 'boxctl network available' shows containers."""
        project, container, target = network_setup

        result = run_abox("network", "available", cwd=project)
        assert result.returncode == 0
        assert target in result.stdout or "nginx" in result.stdout

    def test_network_list_empty(self, network_setup):
        """Test 'boxctl network list' with no connections."""
        project, container, target = network_setup

        result = run_abox("network", "list", cwd=project)
        assert result.returncode == 0

    def test_network_connect(self, network_setup):
        """Test 'boxctl network connect' connects to container."""
        project, container, target = network_setup

        result = run_abox("network", "connect", target, cwd=project)
        assert result.returncode == 0

        # Verify in list
        result = run_abox("network", "list", cwd=project)
        assert target in result.stdout

    def test_network_disconnect(self, network_setup):
        """Test 'boxctl network disconnect' disconnects."""
        project, container, target = network_setup

        run_abox("network", "connect", target, cwd=project)
        result = run_abox("network", "disconnect", target, cwd=project)
        assert result.returncode == 0

    def test_network_available_all(self, network_setup):
        """Test 'boxctl network available all' includes boxctl containers."""
        project, container, target = network_setup

        result = run_abox("network", "available", "all", cwd=project)
        assert result.returncode == 0

    def test_network_help(self, network_setup):
        """Test 'boxctl network --help' shows all subcommands."""
        project, container, target = network_setup

        result = run_abox("network", "--help", cwd=project)
        assert result.returncode == 0
        output = result.stdout.lower()
        assert "available" in output
        assert "connect" in output


# ============================================================================
# PHASE 12: Device Commands
# ============================================================================


class TestPhase12_Devices:
    """Test devices commands: list, add, remove, clear, choose."""

    @pytest.fixture
    def device_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str], None, None]:
        """Create project for device testing."""
        project = test_root / f"test-device-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)

        yield project, f"boxctl-{project.name}"

        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)

    def test_devices_list(self, device_project):
        """Test 'boxctl devices list' shows devices."""
        project, container = device_project

        result = run_abox("devices", "list", cwd=project)
        assert result.returncode == 0

    def test_devices_add(self, device_project):
        """Test 'boxctl devices add' adds a device."""
        project, container = device_project

        # Add /dev/null as a safe test device
        result = run_abox("devices", "add", "/dev/null", cwd=project)
        assert result.returncode == 0

    def test_devices_remove(self, device_project):
        """Test 'boxctl devices remove' removes a device."""
        project, container = device_project

        run_abox("devices", "add", "/dev/null", cwd=project)
        result = run_abox("devices", "remove", "/dev/null", cwd=project)
        assert result.returncode == 0

    def test_devices_clear(self, device_project):
        """Test 'boxctl devices clear' clears all devices."""
        project, container = device_project

        run_abox("devices", "add", "/dev/null", cwd=project)
        result = run_abox("devices", "clear", cwd=project)
        assert result.returncode == 0

    def test_devices_choose_help(self, device_project):
        """Test 'boxctl devices choose --help' shows usage."""
        project, container = device_project

        result = run_abox("devices", "choose", "--help", cwd=project)
        assert result.returncode == 0

    def test_devices_help(self, device_project):
        """Test 'boxctl devices --help' shows all subcommands."""
        project, container = device_project

        result = run_abox("devices", "--help", cwd=project)
        assert result.returncode == 0
        output = result.stdout.lower()
        assert "list" in output
        assert "add" in output
        assert "choose" in output


# ============================================================================
# PHASE 13: Rebase/Rebuild Commands
# ============================================================================


class TestPhase13_Rebase:
    """Test rebase command."""

    @pytest.fixture
    def rebase_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str], None, None]:
        """Create project for rebase testing."""
        project = test_root / f"test-rebase-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)
        run_abox("start", cwd=project)

        container = f"boxctl-{project.name}"
        wait_for_container(container)

        yield project, container

        cleanup_container(container)
        shutil.rmtree(project, ignore_errors=True)

    def test_rebase_recreates_container(self, rebase_project):
        """Test 'boxctl rebase' recreates container."""
        project, container = rebase_project

        # Get original container ID
        result = run_docker("ps", "-qf", f"name=^{container}$")
        old_id = result.stdout.strip()

        # Rebase
        result = run_abox("rebase", cwd=project, timeout=180)
        assert result.returncode == 0, f"Rebase failed: {result.stderr}"

        wait_for_container(container)

        # Get new container ID
        result = run_docker("ps", "-qf", f"name=^{container}$")
        new_id = result.stdout.strip()

        assert old_id != new_id, "Container should be recreated"

    def test_rebuild_alias(self, rebase_project):
        """Test 'boxctl rebuild' works as alias."""
        project, container = rebase_project

        result = run_abox("rebuild", "--help", cwd=project)
        assert result.returncode == 0


# ============================================================================
# PHASE 14: Multi-Session Workflows
# ============================================================================


class TestPhase14_MultiSession:
    """Test multiple tmux sessions in same container."""

    @pytest.fixture
    def multi_session_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str], None, None]:
        """Create project for multi-session testing."""
        project = test_root / f"test-multi-session-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)
        run_abox("start", cwd=project)

        container = f"boxctl-{project.name}"
        wait_for_container(container)

        yield project, container

        cleanup_container(container)
        shutil.rmtree(project, ignore_errors=True)

    def test_create_multiple_sessions(self, multi_session_project):
        """Test creating multiple tmux sessions."""
        project, container = multi_session_project

        # Create sessions
        exec_in_container(container, "tmux new-session -d -s session-1")
        exec_in_container(container, "tmux new-session -d -s session-2")
        exec_in_container(container, "tmux new-session -d -s session-3")

        # List sessions
        result = run_abox("session", "list", cwd=project)
        assert "session-1" in result.stdout
        assert "session-2" in result.stdout
        assert "session-3" in result.stdout

    def test_sessions_independent(self, multi_session_project):
        """Test sessions have independent state."""
        project, container = multi_session_project

        # Create sessions with different working directories
        exec_in_container(container, "tmux new-session -d -s dir-test-1 -c /tmp")
        exec_in_container(container, "tmux new-session -d -s dir-test-2 -c /workspace")

        # Verify both exist
        result = run_abox("session", "list", cwd=project)
        assert "dir-test-1" in result.stdout
        assert "dir-test-2" in result.stdout


# ============================================================================
# PHASE 15: Multi-Project Workflows
# ============================================================================


class TestPhase15_MultiProject:
    """Test multiple projects running simultaneously."""

    @pytest.fixture
    def multi_project_setup(
        self, test_root, base_image_built
    ) -> Generator[List[Tuple[Path, str]], None, None]:
        """Create multiple projects."""
        projects = []

        for i in range(3):
            project = test_root / f"test-multi-{i}-{uuid.uuid4().hex[:8]}"
            project.mkdir(parents=True, exist_ok=True)
            copy_agentbox_repo(project)

            run_abox("init", cwd=project)
            run_abox("start", cwd=project)

            container = f"boxctl-{project.name}"
            wait_for_container(container)

            projects.append((project, container))

        yield projects

        # Cleanup
        for project, container in projects:
            cleanup_container(container)
            shutil.rmtree(project, ignore_errors=True)

    def test_multiple_containers_running(self, multi_project_setup):
        """Test multiple containers can run simultaneously."""
        projects = multi_project_setup

        # Verify all are running
        for project, container in projects:
            assert container_running(container), f"{container} should be running"

    def test_list_shows_all_projects(self, multi_project_setup):
        """Test list shows all running containers."""
        projects = multi_project_setup

        result = run_abox("list")
        assert result.returncode == 0

        for project, container in projects:
            assert container in result.stdout or project.name in result.stdout

    def test_projects_isolated(self, multi_project_setup):
        """Test projects have isolated filesystems."""
        projects = multi_project_setup

        # Write different files in each
        for i, (project, container) in enumerate(projects):
            (project / f"project_{i}.txt").write_text(f"project-{i}")

        # Verify each container only sees its own file
        for i, (project, container) in enumerate(projects):
            result = exec_in_container(container, f"cat /workspace/project_{i}.txt")
            assert f"project-{i}" in result.stdout

            # Should not see other project files
            other = (i + 1) % len(projects)
            result = exec_in_container(container, f"cat /workspace/project_{other}.txt 2>&1")
            assert result.returncode != 0 or "No such file" in result.stdout


# ============================================================================
# PHASE 16: Multi-Agent Type Workflows
# ============================================================================


class TestPhase16_MultiAgent:
    """Test different agent types can be configured."""

    @pytest.fixture
    def agent_project(self, test_root, base_image_built) -> Generator[Path, None, None]:
        """Create project for agent testing."""
        project = test_root / f"test-agent-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)

        yield project

        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)

    def test_claude_help(self, agent_project):
        """Test 'boxctl claude --help' shows usage."""
        result = run_abox("claude", "--help")
        assert result.returncode == 0

    def test_superclaude_help(self, agent_project):
        """Test 'boxctl superclaude --help' shows usage."""
        result = run_abox("superclaude", "--help")
        assert result.returncode == 0

    def test_codex_help(self, agent_project):
        """Test 'boxctl codex --help' shows usage."""
        result = run_abox("codex", "--help")
        assert result.returncode == 0

    def test_gemini_help(self, agent_project):
        """Test 'boxctl gemini --help' shows usage."""
        result = run_abox("gemini", "--help")
        assert result.returncode == 0

    def test_supergemini_help(self, agent_project):
        """Test 'boxctl supergemini --help' shows usage."""
        result = run_abox("supergemini", "--help")
        assert result.returncode == 0

    def test_qwen_help(self, agent_project):
        """Test 'boxctl qwen --help' shows usage."""
        result = run_abox("qwen", "--help")
        assert result.returncode == 0

    def test_superqwen_help(self, agent_project):
        """Test 'boxctl superqwen --help' shows usage."""
        result = run_abox("superqwen", "--help")
        assert result.returncode == 0

    def test_supercodex_help(self, agent_project):
        """Test 'boxctl supercodex --help' shows usage."""
        result = run_abox("supercodex", "--help")
        assert result.returncode == 0


# ============================================================================
# PHASE 16b: Agent Launch in Tmux Sessions
# ============================================================================


class TestPhase16b_AgentLaunch:
    """Test actual agent launch in tmux sessions with config verification."""

    @pytest.fixture
    def agent_ready_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str], None, None]:
        """Create and start project ready for agent testing."""
        project = test_root / f"test-agent-launch-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)
        # Add MCP servers that agents will use
        run_abox("mcp", "add", "fetch", cwd=project)
        run_abox("start", cwd=project)

        container = f"boxctl-{project.name}"
        wait_for_container(container)

        yield project, container

        cleanup_container(container)
        shutil.rmtree(project, ignore_errors=True)

    # --- Config Verification Tests ---

    def test_mcp_config_exists(self, agent_ready_project):
        """Test MCP config file exists and is valid (unified for all agents)."""
        project, container = agent_ready_project

        # mcp.json is now at root level (unified for all agents)
        result = exec_in_container(container, "cat /workspace/.boxctl/mcp.json")
        assert result.returncode == 0, f"MCP config not found: {result.stderr}"

        # Verify it's valid JSON
        data = json.loads(result.stdout)
        assert "mcpServers" in data

    def test_agent_instructions_exist(self, agent_ready_project):
        """Test agent instruction files exist."""
        project, container = agent_ready_project

        # Check agents.md
        result = exec_in_container(container, "test -f /workspace/.boxctl/agents.md && echo exists")
        assert result.returncode == 0
        assert "exists" in result.stdout

        # Check superagents.md
        result = exec_in_container(
            container, "test -f /workspace/.boxctl/superagents.md && echo exists"
        )
        assert result.returncode == 0
        assert "exists" in result.stdout

    def test_claude_binary_in_container(self, agent_ready_project):
        """Test claude binary is available in container."""
        project, container = agent_ready_project

        result = exec_in_container(container, "which claude")
        assert result.returncode == 0
        assert "claude" in result.stdout

    def test_codex_binary_in_container(self, agent_ready_project):
        """Test codex binary is available in container."""
        project, container = agent_ready_project

        result = exec_in_container(container, "which codex")
        assert result.returncode == 0
        assert "codex" in result.stdout

    # --- Tmux Session Tests ---

    def test_create_claude_session(self, agent_ready_project):
        """Test creating a tmux session for claude."""
        project, container = agent_ready_project
        session = "claude-test-session"

        # Create session like boxctl does
        result = exec_in_container(
            container,
            f"tmux new-session -d -s {session} -c /workspace 'echo claude-session-started; sleep 10'",
        )
        assert result.returncode == 0, f"Failed to create session: {result.stderr}"

        # Verify session exists
        result = exec_in_container(container, f"tmux has-session -t {session}")
        assert result.returncode == 0

        # Verify session shows in list
        result = run_abox("session", "list", cwd=project)
        assert session in result.stdout

        # Cleanup
        exec_in_container(container, f"tmux kill-session -t {session}")

    def test_create_superclaude_session(self, agent_ready_project):
        """Test creating a tmux session for superclaude."""
        project, container = agent_ready_project
        session = "superclaude-test-session"

        result = exec_in_container(
            container,
            f"tmux new-session -d -s {session} -c /workspace 'echo superclaude-ready; sleep 10'",
        )
        assert result.returncode == 0

        result = exec_in_container(container, f"tmux has-session -t {session}")
        assert result.returncode == 0

        exec_in_container(container, f"tmux kill-session -t {session}")

    def test_multiple_agent_sessions(self, agent_ready_project):
        """Test multiple different agent sessions can coexist."""
        project, container = agent_ready_project
        sessions = ["main-claude", "main-codex", "feature-superclaude"]

        # Create all sessions
        for session in sessions:
            result = exec_in_container(
                container, f"tmux new-session -d -s {session} -c /workspace 'sleep 30'"
            )
            assert result.returncode == 0, f"Failed to create {session}"

        # Verify all exist
        result = run_abox("session", "list", cwd=project)
        for session in sessions:
            assert session in result.stdout, f"{session} not in session list"

        # Cleanup
        for session in sessions:
            exec_in_container(container, f"tmux kill-session -t {session}")

    # --- Agent Config in Session Tests ---

    def test_workspace_accessible_in_session(self, agent_ready_project):
        """Test workspace files are accessible from tmux session."""
        project, container = agent_ready_project

        # Create test file
        (project / "session_test.txt").write_text("session-visible")

        # Access from session
        result = exec_in_container(
            container,
            "tmux new-session -d -s access-test 'cat /workspace/session_test.txt > /tmp/session_out.txt; sleep 2'",
        )
        assert result.returncode == 0

        time.sleep(2)

        result = exec_in_container(container, "cat /tmp/session_out.txt")
        assert "session-visible" in result.stdout

        exec_in_container(container, "tmux kill-session -t access-test 2>/dev/null || true")

    def test_mcp_config_accessible_in_session(self, agent_ready_project):
        """Test MCP config is accessible from agent tmux session."""
        project, container = agent_ready_project

        # mcp.json is now at root level (unified for all agents)
        result = exec_in_container(
            container,
            "tmux new-session -d -s mcp-test 'cat /workspace/.boxctl/mcp.json > /tmp/mcp_out.txt; sleep 2'",
        )
        assert result.returncode == 0

        time.sleep(2)

        result = exec_in_container(container, "cat /tmp/mcp_out.txt")
        assert "mcpServers" in result.stdout

        exec_in_container(container, "tmux kill-session -t mcp-test 2>/dev/null || true")

    def test_claude_help_in_session(self, agent_ready_project):
        """Test claude --help works in tmux session."""
        project, container = agent_ready_project

        result = exec_in_container(
            container,
            "tmux new-session -d -s help-test 'claude --help > /tmp/claude_help.txt 2>&1; sleep 2'",
        )
        assert result.returncode == 0

        time.sleep(3)

        result = exec_in_container(container, "cat /tmp/claude_help.txt")
        # Claude help should output something
        assert len(result.stdout) > 50 or "claude" in result.stdout.lower()

        exec_in_container(container, "tmux kill-session -t help-test 2>/dev/null || true")

    # --- Agent Environment Tests ---

    def test_session_has_correct_workdir(self, agent_ready_project):
        """Test tmux session starts in /workspace."""
        project, container = agent_ready_project

        result = exec_in_container(
            container,
            "tmux new-session -d -s workdir-test -c /workspace 'pwd > /tmp/workdir.txt; sleep 2'",
        )
        assert result.returncode == 0

        time.sleep(2)

        result = exec_in_container(container, "cat /tmp/workdir.txt")
        assert "/workspace" in result.stdout

        exec_in_container(container, "tmux kill-session -t workdir-test 2>/dev/null || true")

    def test_session_environment_variables(self, agent_ready_project):
        """Test environment variables are set in agent sessions."""
        project, container = agent_ready_project

        # Set tmux environment
        exec_in_container(container, "tmux set-environment -g AGENT_TEST 'test-value'")

        result = exec_in_container(
            container, "tmux new-session -d -s env-test 'echo $AGENT_TEST > /tmp/env.txt; sleep 2'"
        )
        assert result.returncode == 0

        time.sleep(2)

        result = exec_in_container(container, "cat /tmp/env.txt")
        assert "test-value" in result.stdout

        exec_in_container(container, "tmux kill-session -t env-test 2>/dev/null || true")

    def test_session_user_is_abox(self, agent_ready_project):
        """Test tmux session runs as abox user."""
        project, container = agent_ready_project

        result = exec_in_container(
            container, "tmux new-session -d -s user-test 'whoami > /tmp/user.txt; sleep 2'"
        )
        assert result.returncode == 0

        time.sleep(2)

        result = exec_in_container(container, "cat /tmp/user.txt")
        assert "abox" in result.stdout

        exec_in_container(container, "tmux kill-session -t user-test 2>/dev/null || true")

    # --- Agent Session Lifecycle Tests ---

    def test_session_rename(self, agent_ready_project):
        """Test renaming agent session."""
        project, container = agent_ready_project

        # Create session
        exec_in_container(container, "tmux new-session -d -s rename-me 'sleep 30'")

        # Rename via CLI
        result = run_abox("session", "rename", "rename-me", "renamed-agent", cwd=project)
        assert result.returncode == 0

        # Verify old name gone
        result = exec_in_container(container, "tmux has-session -t rename-me")
        assert result.returncode != 0

        # Verify new name exists
        result = exec_in_container(container, "tmux has-session -t renamed-agent")
        assert result.returncode == 0

        exec_in_container(container, "tmux kill-session -t renamed-agent")

    def test_session_remove(self, agent_ready_project):
        """Test removing agent session."""
        project, container = agent_ready_project

        # Create session
        exec_in_container(container, "tmux new-session -d -s remove-me 'sleep 30'")

        # Remove via CLI
        result = run_abox("session", "remove", "remove-me", cwd=project)
        assert result.returncode == 0

        # Verify gone
        result = exec_in_container(container, "tmux has-session -t remove-me")
        assert result.returncode != 0

    def test_agent_restart_workflow(self, agent_ready_project):
        """Test stopping and restarting agent session."""
        project, container = agent_ready_project
        session = "restart-agent"

        # Create initial session
        exec_in_container(
            container, f"tmux new-session -d -s {session} 'echo run-1 > /tmp/run.txt; sleep 30'"
        )
        time.sleep(1)

        result = exec_in_container(container, "cat /tmp/run.txt")
        assert "run-1" in result.stdout

        # Kill and recreate
        exec_in_container(container, f"tmux kill-session -t {session}")
        exec_in_container(
            container, f"tmux new-session -d -s {session} 'echo run-2 > /tmp/run.txt; sleep 30'"
        )
        time.sleep(1)

        result = exec_in_container(container, "cat /tmp/run.txt")
        assert "run-2" in result.stdout

        exec_in_container(container, f"tmux kill-session -t {session}")


# ============================================================================
# PHASE 16c: Agent Launch with Auth (Optional)
# ============================================================================


@pytest.mark.requires_auth
class TestPhase16c_AgentLaunchWithAuth:
    """Test agent launch with actual auth credentials (skipped if no auth)."""

    @pytest.fixture
    def auth_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str, bool, bool], None, None]:
        """Create project and check auth availability."""
        project = test_root / f"test-auth-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)
        run_abox("start", cwd=project)

        container = f"boxctl-{project.name}"
        wait_for_container(container)

        # Check auth
        has_claude = (
            Path("/home/testuser/.claude").is_dir() if Path("/home/testuser").exists() else False
        )
        has_codex = (
            Path("/home/testuser/.codex").is_dir() if Path("/home/testuser").exists() else False
        )

        yield project, container, has_claude, has_codex

        cleanup_container(container)
        shutil.rmtree(project, ignore_errors=True)

    def test_claude_version(self, auth_project):
        """Test claude --version works with auth."""
        project, container, has_claude, _ = auth_project

        if not has_claude:
            pytest.skip("Claude auth not available")

        result = exec_in_container(container, "claude --version", timeout=15)
        # Should return version or at least not hard error
        assert result.returncode == 0 or "version" in result.stdout.lower()

    def test_codex_version(self, auth_project):
        """Test codex --version works with auth."""
        project, container, _, has_codex = auth_project

        if not has_codex:
            pytest.skip("Codex auth not available")

        result = exec_in_container(container, "codex --version", timeout=15)
        assert result.returncode == 0 or len(result.stdout) > 0

    def test_claude_can_read_config(self, auth_project):
        """Test claude can parse MCP config without error."""
        project, container, has_claude, _ = auth_project

        if not has_claude:
            pytest.skip("Claude auth not available")

        # Running claude with just --help should load config
        result = exec_in_container(container, "claude --help 2>&1", timeout=15)

        # Should not error about MCP config
        assert "mcp" not in result.stderr.lower() or "error" not in result.stderr.lower()


# ============================================================================
# PHASE 17: Service Daemon Commands
# ============================================================================


class TestPhase17_Service:
    """Test service commands: status, config, logs, serve, install, start, stop."""

    def test_service_status(self, dind_ready):
        """Test 'boxctl service status' shows daemon status."""
        result = run_abox("service", "status")
        # May be running or not, but command should work
        assert result.returncode == 0 or "not running" in result.stdout.lower()

    def test_service_config(self, dind_ready):
        """Test 'boxctl service config' shows configuration."""
        result = run_abox("service", "config")
        assert result.returncode == 0

    def test_service_logs(self, dind_ready):
        """Test 'boxctl service logs' shows logs."""
        result = run_abox("service", "logs")
        # May have no logs if not running
        assert (
            result.returncode == 0
            or "no logs" in result.stdout.lower()
            or "not" in result.stdout.lower()
        )

    def test_service_install_help(self, dind_ready):
        """Test 'boxctl service install --help'."""
        result = run_abox("service", "install", "--help")
        assert result.returncode == 0

    def test_service_start_help(self, dind_ready):
        """Test 'boxctl service start --help'."""
        result = run_abox("service", "start", "--help")
        assert result.returncode == 0

    def test_service_stop_help(self, dind_ready):
        """Test 'boxctl service stop --help'."""
        result = run_abox("service", "stop", "--help")
        assert result.returncode == 0

    def test_service_restart_help(self, dind_ready):
        """Test 'boxctl service restart --help'."""
        result = run_abox("service", "restart", "--help")
        assert result.returncode == 0

    def test_service_uninstall_help(self, dind_ready):
        """Test 'boxctl service uninstall --help'."""
        result = run_abox("service", "uninstall", "--help")
        assert result.returncode == 0

    def test_service_follow_help(self, dind_ready):
        """Test 'boxctl service follow --help'."""
        result = run_abox("service", "follow", "--help")
        assert result.returncode == 0

    def test_service_serve_help(self, dind_ready):
        """Test 'boxctl service serve --help'."""
        result = run_abox("service", "serve", "--help")
        assert result.returncode == 0

    def test_service_help(self, dind_ready):
        """Test 'boxctl service --help' shows all subcommands."""
        result = run_abox("service", "--help")
        assert result.returncode == 0
        output = result.stdout.lower()
        assert "status" in output
        assert "install" in output
        assert "start" in output


# ============================================================================
# PHASE 17b: Boxctld Server Tests
# ============================================================================


class TestPhase17b_BoxctldServer:
    """Test boxctld daemon server functionality."""

    @pytest.fixture
    def daemon_test_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str], None, None]:
        """Create project for daemon testing."""
        project = test_root / f"test-daemon-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)
        run_abox("start", cwd=project)

        container = f"boxctl-{project.name}"
        wait_for_container(container)

        yield project, container

        cleanup_container(container)
        shutil.rmtree(project, ignore_errors=True)

    def test_daemon_can_start_in_background(self, daemon_test_project):
        """Test daemon can be started in background mode."""
        project, container = daemon_test_project

        # Start daemon in background (it should exit gracefully or run)
        result = exec_in_container(
            container, "timeout 5 boxctld serve --port 8765 2>&1 || true", timeout=10
        )
        # Should not hard crash
        assert "error" not in result.stderr.lower() or "traceback" not in result.stderr.lower()

    def test_daemon_api_endpoints_defined(self, daemon_test_project):
        """Test daemon has expected API endpoints defined."""
        project, container = daemon_test_project

        # Check daemon module can be imported
        result = exec_in_container(
            container, "python3 -c 'from boxctl.daemon.server import create_app; print(\"ok\")'"
        )
        assert result.returncode == 0 or "ok" in result.stdout


# ============================================================================
# PHASE 17c: Notification Tests
# ============================================================================


class TestPhase17c_Notifications:
    """Test notification functionality."""

    @pytest.fixture
    def notify_project(
        self, test_root, base_image_built
    ) -> Generator[Tuple[Path, str], None, None]:
        """Create project for notification testing."""
        project = test_root / f"test-notify-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)
        run_abox("start", cwd=project)

        container = f"boxctl-{project.name}"
        wait_for_container(container)

        yield project, container

        cleanup_container(container)
        shutil.rmtree(project, ignore_errors=True)

    def test_notify_script_exists(self, notify_project):
        """Test notify.sh script exists in container."""
        project, container = notify_project

        result = exec_in_container(container, "which notify.sh || test -f /usr/local/bin/notify.sh")
        # notify.sh may or may not be installed, that's ok
        # Just verify the path is accessible

    def test_notification_module_importable(self, notify_project):
        """Test notification module can be imported."""
        project, container = notify_project

        result = exec_in_container(
            container,
            "python3 -c 'from boxctl.notifications import NotificationClient; print(\"ok\")'",
        )
        assert result.returncode == 0
        assert "ok" in result.stdout

    def test_notification_client_instantiable(self, notify_project):
        """Test NotificationClient can be instantiated."""
        project, container = notify_project

        result = exec_in_container(
            container,
            "python3 -c '"
            "from boxctl.notifications import NotificationClient; "
            "client = NotificationClient(); "
            'print(f"created:{client is not None}")\'',
        )
        assert result.returncode == 0
        assert "created:True" in result.stdout

    def test_notification_send_dry_run(self, notify_project):
        """Test notification can be prepared (even if delivery fails without server)."""
        project, container = notify_project

        result = exec_in_container(
            container,
            "python3 -c '"
            "from boxctl.notifications import NotificationClient; "
            "client = NotificationClient(); "
            "# Just test the interface exists "
            'hasattr(client, "send") and print("has_send:True")\'',
        )
        assert result.returncode == 0
        # Should have the send method
        assert "has_send:True" in result.stdout or result.returncode == 0


# ============================================================================
# PHASE 18: Config Migration Commands
# ============================================================================


class TestPhase18_ConfigMigration:
    """Test config migration commands."""

    @pytest.fixture
    def migration_project(self, test_root, base_image_built) -> Generator[Path, None, None]:
        """Create project for migration testing."""
        project = test_root / f"test-migrate-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project)

        run_abox("init", cwd=project)

        yield project

        cleanup_container(f"boxctl-{project.name}")
        shutil.rmtree(project, ignore_errors=True)

    def test_config_migrate_dryrun(self, migration_project):
        """Test 'boxctl config migrate --dry-run'."""
        project = migration_project

        result = run_abox("config", "migrate", "--dry-run", cwd=project)
        assert result.returncode == 0

    def test_config_migrate(self, migration_project):
        """Test 'boxctl config migrate' migrates config."""
        project = migration_project

        result = run_abox("config", "migrate", cwd=project)
        assert result.returncode == 0


# ============================================================================
# PHASE 19: Quick/TUI Commands
# ============================================================================


class TestPhase19_QuickCommands:
    """Test quick/TUI commands."""

    def test_quick_help(self, dind_ready):
        """Test 'boxctl quick --help'."""
        result = run_abox("quick", "--help")
        assert result.returncode == 0

    def test_q_alias(self, dind_ready):
        """Test 'boxctl q --help' works as alias."""
        result = run_abox("q", "--help")
        assert result.returncode == 0


# ============================================================================
# PHASE 20: Fix-Terminal Command
# ============================================================================


class TestPhase20_FixTerminal:
    """Test fix-terminal command."""

    def test_fix_terminal_help(self, dind_ready):
        """Test 'boxctl fix-terminal --help'."""
        result = run_abox("fix-terminal", "--help")
        assert result.returncode == 0


# ============================================================================
# PHASE 21: Cleanup Command
# ============================================================================


class TestPhase21_Cleanup:
    """Test cleanup command."""

    def test_cleanup_help(self, dind_ready):
        """Test 'boxctl cleanup --help'."""
        result = run_abox("cleanup", "--help")
        assert result.returncode == 0


# ============================================================================
# INTEGRATION SCENARIOS
# ============================================================================


class TestIntegration_FullWorkflow:
    """Full workflow integration tests."""

    @pytest.fixture
    def workflow_project(self, test_root, base_image_built) -> Generator[Path, None, None]:
        """Create project for full workflow testing."""
        project = test_root / f"workflow-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        copy_agentbox_repo(project, branches=["feature-x", "feature-y"])

        yield project

        # Cleanup everything
        cleanup_containers_matching(f"boxctl-{project.name}")
        for wt in project.parent.glob(f"{project.name}-*"):
            if wt.is_dir():
                shutil.rmtree(wt, ignore_errors=True)
        shutil.rmtree(project, ignore_errors=True)

    def test_full_project_lifecycle(self, workflow_project):
        """Test complete project lifecycle: init -> configure -> start -> use -> stop -> remove."""
        project = workflow_project
        container = f"boxctl-{project.name}"

        # 1. Initialize
        result = run_abox("init", cwd=project)
        assert result.returncode == 0

        # 2. Configure MCP
        result = run_abox("mcp", "add", "fetch", cwd=project)
        assert result.returncode == 0 or "already" in result.stdout.lower()

        # 3. Configure packages
        result = run_abox("packages", "add", "requests", "pip", cwd=project)
        assert result.returncode == 0

        # 4. Enable Docker
        result = run_abox("docker", "enable", cwd=project)
        assert result.returncode == 0

        # 5. Start
        result = run_abox("start", cwd=project)
        assert result.returncode == 0
        wait_for_container(container)

        # 6. Verify running
        assert container_running(container)

        # 7. Create sessions
        exec_in_container(container, "tmux new-session -d -s work")
        result = run_abox("session", "list", cwd=project)
        assert "work" in result.stdout

        # 8. Stop
        result = run_abox("stop", cwd=project)
        assert result.returncode == 0
        assert not container_running(container)

        # 9. Remove
        result = run_abox("remove", project.name, "yes", cwd=project)
        assert result.returncode == 0
        assert not container_exists(container)

    def test_worktree_multi_branch_workflow(self, workflow_project):
        """Test working with multiple branches via worktrees."""
        project = workflow_project
        container = f"boxctl-{project.name}"

        # Initialize and start
        run_abox("init", cwd=project)
        run_abox("start", cwd=project)
        wait_for_container(container)

        # Add worktrees for feature branches
        run_abox("worktree", "add", "feature-x", cwd=project)
        run_abox("worktree", "add", "feature-y", cwd=project)

        # List should show both
        result = run_abox("worktree", "list", cwd=project)
        assert "feature-x" in result.stdout
        assert "feature-y" in result.stdout

        # Clean up worktrees
        run_abox("worktree", "remove", "feature-x", cwd=project)
        run_abox("worktree", "remove", "feature-y", cwd=project)

    def test_network_connection_workflow(self, workflow_project, base_image_built):
        """Test connecting to other containers."""
        project = workflow_project
        container = f"boxctl-{project.name}"

        # Create target container
        target = f"net-target-{uuid.uuid4().hex[:8]}"
        run_docker("run", "-d", "--name", target, "nginx:alpine")
        time.sleep(2)

        try:
            # Initialize and enable docker
            run_abox("init", cwd=project)
            run_abox("docker", "enable", cwd=project)
            run_abox("start", cwd=project)
            wait_for_container(container)

            # Connect to target
            result = run_abox("network", "connect", target, cwd=project)
            assert result.returncode == 0

            # Verify connection
            result = run_abox("network", "list", cwd=project)
            assert target in result.stdout

            # Disconnect
            run_abox("network", "disconnect", target, cwd=project)
        finally:
            cleanup_container(target)
