# Agentbox DinD Test Suite

Comprehensive Docker-in-Docker integration tests for all boxctl commands.

## Overview

This test suite provides **real flow testing** of all boxctl CLI commands using Docker-in-Docker (DinD). Unlike unit tests that mock Docker, these tests:

- Run in a real Docker environment inside Docker
- Execute actual `agentbox` commands
- Create real containers and verify real effects
- Test multi-project, multi-session, and multi-agent scenarios
- Verify configurations actually work in tmux sessions

## Test Coverage

### Statistics
- **149 test functions**
- **26 test classes**
- **21+ test phases**

### Test Phases

| Phase | Name | Commands Tested |
|-------|------|-----------------|
| 1 | Base Image | `base rebuild` |
| 2 | Project Lifecycle | `init`, `start`, `stop`, `list`, `ps`, `info`, `shell`, `connect`, `remove` |
| 3 | Session Management | `session list`, `session rename`, `session remove` |
| 4 | Workspace Mounts | `workspace list`, `workspace add`, `workspace remove` |
| 5 | Worktree Commands | `worktree list`, `worktree add`, `worktree remove`, `worktree prune` |
| 6 | Port Forwarding | `ports list`, `ports expose`, `ports forward`, `ports unexpose`, `ports unforward`, `ports status` |
| 7 | MCP Servers | `mcp list`, `mcp add`, `mcp remove`, `mcp show`, `mcp init`, `mcps` |
| 8 | Skills | `skill list`, `skill add`, `skill remove`, `skills` |
| 9 | Packages | `packages list`, `packages add`, `packages remove` (pip, npm, apt) |
| 10 | Docker Socket | `docker enable`, `docker disable`, `docker status` |
| 11 | Network | `network available`, `network list`, `network connect`, `network disconnect` |
| 12 | Devices | `devices list`, `devices add`, `devices remove`, `devices clear` |
| 13 | Rebase | `rebase`, `rebuild` |
| 14 | Multi-Session | Multiple tmux sessions in same container |
| 15 | Multi-Project | Multiple projects running simultaneously |
| 16 | Multi-Agent | `claude`, `superclaude`, `codex`, `gemini` help |
| 16b | Agent Launch | Real tmux session creation, config verification |
| 16c | Agent with Auth | Auth-dependent tests (optional) |
| 17 | Service Daemon | `service status`, `service config`, `service logs` |
| 17b | Agentboxd | Daemon server functionality |
| 17c | Notifications | `abox-notify`, NotificationClient |
| 18 | Config Migration | `config migrate` |
| 19 | Quick Commands | `quick`, `q` |
| 20 | Fix-Terminal | `fix-terminal` |
| 21 | Cleanup | `cleanup` |
| Integration | Full Workflows | End-to-end scenarios |

## Running Tests

### Quick Start

```bash
# Run all tests
./scripts/run-dind-tests.sh

# Run just the full workflow tests
./scripts/run-dind-tests.sh --workflow

# Run a specific phase
./scripts/run-dind-tests.sh --phase 2  # Project Lifecycle tests
```

### With Auth (for agent tests)

```bash
# Mount Claude/Codex credentials
./scripts/run-dind-tests.sh --with-auth
```

### Filtering Tests

```bash
# Run tests matching a pattern
./scripts/run-dind-tests.sh -k "test_start"

# Run tests in a specific class
./scripts/run-dind-tests.sh -k "TestPhase3"

# Stop on first failure
./scripts/run-dind-tests.sh -x
```

### Generate HTML Report

```bash
./scripts/run-dind-tests.sh --html
# Report at: results/report.html
```

### Interactive Debugging

```bash
# Shell into the DinD container
./scripts/run-dind-tests.sh --interactive

# Inside container:
pytest dind-tests/test_full_workflow.py -v -k "test_init"
```

## Manual Docker Commands

```bash
# Build the DinD test image
docker build -f tests/dind-tests/Dockerfile.dind -t boxctl-dind-test:latest tests/

# Run tests directly
docker run --privileged --rm boxctl-dind-test:latest \
    pytest dind-tests/test_full_workflow.py -v

# Run with auth mounted
docker run --privileged --rm \
    -v ~/.claude:/home/testuser/.claude:ro \
    -v ~/.codex:/home/testuser/.codex:ro \
    boxctl-dind-test:latest pytest dind-tests/ -v
```

## Test Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Host System                              │
├─────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────┐│
│  │              DinD Test Container                       ││
│  │  - Ubuntu 24.04                                        ││
│  │  - Docker daemon (dockerd)                             ││
│  │  - boxctl CLI                                        ││
│  │  - pytest                                              ││
│  │                                                        ││
│  │  ┌──────────────────────────────────────────────────┐ ││
│  │  │         Agentbox Container                       │ ││
│  │  │  - Built from boxctl-base:latest               │ ││
│  │  │  - Real tmux sessions                            │ ││
│  │  │  - Real MCP configs                              │ ││
│  │  │  - Real workspace mounts                         │ ││
│  │  └──────────────────────────────────────────────────┘ ││
│  │                                                        ││
│  │  ┌──────────────────┐  ┌──────────────────────────┐  ││
│  │  │  nginx:alpine    │  │  postgres:16-alpine      │  ││
│  │  │  (network tests) │  │  (network tests)         │  ││
│  │  └──────────────────┘  └──────────────────────────┘  ││
│  └────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

## Key Testing Principles

### 1. Real Flow Testing
Every test executes actual commands and verifies real effects:
```python
def test_start_creates_container(self, project_dir):
    """Test 'agentbox start' creates and runs container."""
    run_abox("init", cwd=project_dir)
    container_name = f"agentbox-{project_dir.name}"

    result = run_abox("start", cwd=project_dir)
    assert result.returncode == 0

    # Verify REAL container exists
    assert container_exists(container_name)
    assert container_running(container_name)
```

### 2. Proper Ordering
Tests follow realistic usage order:
1. Build base image
2. Initialize project
3. Configure (MCP, packages, ports)
4. Start container
5. Manage sessions
6. Use advanced features
7. Cleanup

### 3. Agent Config Verification
Tests verify configs actually work in tmux sessions:
```python
def test_mcp_config_accessible_in_session(self, agent_ready_project):
    """Test MCP config is accessible from agent tmux session."""
    project, container = agent_ready_project

    exec_in_container(
        container,
        "tmux new-session -d -s mcp-test 'cat /home/abox/.mcp.json'"
    )
    # Verify config is readable
```

### 4. Multi-Scenario Testing
Tests cover realistic multi-project/session scenarios:
- Multiple containers running simultaneously
- Multiple tmux sessions per container
- Isolated filesystems verified
- Network connections between containers

## Adding New Tests

1. Identify the command/feature to test
2. Add to appropriate phase class or create new phase
3. Use fixtures for setup/cleanup
4. Verify real effects, not just config changes

Example:
```python
class TestPhaseN_NewFeature:
    """Test new feature commands."""

    @pytest.fixture
    def feature_project(self, test_root, base_image_built):
        project = test_root / f"test-feature-{uuid.uuid4().hex[:8]}"
        project.mkdir(parents=True, exist_ok=True)
        create_git_repo(project)
        run_abox("init", cwd=project)
        yield project
        cleanup_container(f"agentbox-{project.name}")

    def test_feature_does_something(self, feature_project):
        """Test new feature."""
        result = run_abox("feature", "subcommand", cwd=feature_project)
        assert result.returncode == 0
        # Verify real effect
```

## Troubleshooting

### Tests timeout
- Increase timeout in pytest.ini
- Check if Docker daemon started properly
- Look at /var/log/dockerd.log in container

### Auth tests skipped
- Mount credentials: `--with-auth`
- Ensure ~/.claude and ~/.codex exist

### "Cannot create containers"
- Run with `--privileged` flag
- Check storage driver in daemon.json

### Interactive debugging
```bash
./scripts/run-dind-tests.sh --interactive
# Then run specific tests manually
pytest dind-tests/test_full_workflow.py::TestPhase2_ProjectLifecycle::test_init_creates_agentbox_dir -v
```
