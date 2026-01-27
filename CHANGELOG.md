# Changelog

All notable changes to Boxctl are documented here.

## [0.3.2] - 2026-01-27

### Breaking Changes

- **Renamed project from `agentbox` to `boxctl`**
  - CLI commands now use `boxctl` instead of `agentbox`
  - Config directory changed from `.agentbox/` to `.boxctl/`
  - MCP servers renamed: `agentbox-analyst` → `boxctl-analyst`, `agentbox-notify` → `boxctl-notify`
  - Existing projects need to rename `.agentbox/` to `.boxctl/`

### Added

- **Dev branch workflow** - Cleaner release process with private dev branch
- **Improved test infrastructure** - Better DinD test coverage and reliability
- **Centralized configuration** - Hardcoded values consolidated

### Fixed

- Docker connection error detection improvements
- SSH handler method compatibility in tests
- Various test fixes for renamed codebase

## [0.3.1] - 2026-01-25

### Added

- **Non-interactive mode** - New `abox run` command for automation and scripting
  - Run agents without tmux: `abox run superclaude "implement feature"`
  - Suitable for CI/CD pipelines, automation tools, and scripting
  - Returns exit codes for programmatic handling
  - Thanks to [@stephanj](https://github.com/stephanj) for the concept ([#3](https://github.com/scharc/boxctl/pull/3))
- **GitHub/GitLab CLI credentials** - Opt-in mounting for `gh` and `glab` CLI configs
  - Enable via `abox reconfigure` or set `credentials.gh: true` in config
  - `~/.config/gh/` mounted read-only for GitHub CLI authentication
  - `~/.config/glab-cli/` mounted read-only for GitLab CLI authentication

### Fixed

- **macOS compatibility** - Fixed runtime directory path for macOS
  - Uses `$TMPDIR` on macOS instead of Linux-specific `/run/user/{uid}`
  - Thanks to [@stephanj](https://github.com/stephanj) for the fix ([#2](https://github.com/scharc/boxctl/pull/2))

## [0.3.0] - 2026-01-25

New minor release with Qwen agent support, multi-agent orchestration, unified configuration, and significant reliability improvements.

### Added

- **Qwen Code support** - New agent with `abox qwen` and `abox superqwen` commands
  - Auto-mounts `~/.qwen` for auth/config
  - Superqwen uses `--yolo` flag for auto-approve mode
- **AgentPipe multi-agent orchestration** - Run conversations between AI agents
  - Round-robin, reactive, and free-form conversation modes
  - TUI interface with metrics
  - Supports Claude, Gemini, Codex, Qwen agents
  - `discuss` tool in boxctl-analyst MCP for multi-agent discussions
- **Agent rate limit tracking** - Centralized rate limit detection and fallback
  - Automatic agent fallback chains: superclaude → supercodex → supergemini → superqwen
  - CLI commands: `abox usage status/probe/reset/fallback`
  - agentctl MCP tools for agents to check/report limits
- **Remote Q&A manager** - Telegram/webhook support for agent questions
  - Detects when agents are waiting for user input
  - Pattern matching for questions, confirmations, passwords
  - Notification with question summarization
- **Port conflict detection** - Cross-project port conflict detection
  - Live status display when exposing/forwarding ports
  - `abox ports list all` shows ports across all containers
- **Remote Chrome skill** - Control Chrome browser via CDP
  - Agents can interact with host Chrome through port forwarding
  - Requires Chrome with `--remote-debugging-port=9222`
- **Notification auto-dismiss** - Notifications auto-dismiss on session activity
- **Fast session discovery** - Daemon cache for faster session lookups
- **GitLab CLI (glab)** - Added to base image
- **FastMCP** - Added to base image for Python MCP development
- **python-is-python3** - Added to base image for compatibility
- **Native Claude Code installer** - Uses official installer instead of npm

### Changed

- **Unified agent configuration** - All agents share MCP config via symlinks
  - Single `mcp.json` distributed to all agent config directories
  - `distribute-mcp-config.py` handles config synchronization
  - Agent configs moved to home directories
- **Unified notification system** - Multi-channel notification dispatch
  - Single AI call generates short (6 words) and long (2 sentences) summaries
  - Desktop uses short summaries, Telegram uses long summaries
  - Easily extensible for Slack, Discord, etc.
- **Worktree command restructure** - Argument order changed to `BRANCH AGENT`
  - Removed `wt` alias for worktree command
  - More consistent with other CLI patterns
- **CLI consistency improvements**
  - Consistent arg patterns for session and agent commands
  - Removed deprecated ports aliases
  - Warns about active sessions before disruptive actions
- **Centralized paths module** - All path handling consolidated
- **Container name resolution** - Centralized with collision handling
- **Removed legacy code** - Migration and backward compatibility code cleaned up
- **Templates consolidated** - Unified config structure across agents

### Fixed

- **tmux session matching** - Exact match prevents wrong session attach
- **tmux socket handling** - Consistent socket detection across CLI and MCP
- **Gemini config path** - Corrected path resolution
- **Codex approval policy** - Fixed configuration
- **MCP installation** - Custom MCP installation and env var resolution fixed
- **Analyst fallback chain** - Improved with Qwen support
- **CLI error messages** - Better formatted panels
- **Notification AI summaries** - Compact for notification bubbles
- **agentctl tmux config** - Applied to sessions created via MCP
- **Reconfigure UX** - Improved experience and config saving

### Performance

- **Caching and parallelization** - Across CLI and web server
- **Session discovery cache** - Faster lookups via daemon

### Testing

- **Comprehensive CLI tests** - Command existence, execution, workflow, and regression tests
- **DinD test fixes** - Fixed test collection and unit test failures

### Breaking Changes

- **Worktree command argument order** - Changed from `AGENT BRANCH` to `BRANCH AGENT`
- **`wt` alias removed** - Use `agentctl worktree` or full command
- **Agent config locations** - Moved to home directories (migration automatic)

---

## [0.2.0] - 2026-01-18

Major release with new architecture, MCP servers, and mobile-friendly CLI.

### Added
- **agentctl MCP** - Worktree and session management from within agents
- **boxctl-analyst MCP** - Cross-agent review and analysis
- **boxctl-notify MCP** - Desktop notifications from container
- **Worktree support** - Run multiple agents on different branches in parallel
- **Session management** - Multiple agent sessions per container
- **Quick menu** (`abox q`) - Mobile-friendly single-keypress navigation
- **Port forwarding** - Expose container ports without restart
- **Container networking** - Connect to other Docker containers
- **Device passthrough** - GPU, audio, serial port access
- **Docker socket access** - Give agents Docker control
- **Stall detection** - Automatic notifications when agents appear stuck
- **Automatic credential sharing** - Claude, Codex, OpenAI, Gemini credentials auto-mount
- **SSH agent forwarding** - Support for hardware keys and passphrase-protected keys
- **Web UI** - PWA-ready status dashboard

### Changed
- **All CLI flags removed** - Positional arguments only (mobile-friendly)
- **Packages moved to `.agentbox.yml`** - Single config file
- **MCP library reorganized** - `boxctl-notify`, `boxctl-analyst`, `agentctl`
- **Documentation rewritten** - Story-driven guides, comprehensive reference

### Fixed
- OAuth token refresh in containers (directory mounts instead of file mounts)
- Terminal corruption after Docker/tmux operations
- Container init performance (removed slow chown operations)
- Session reattachment reliability

---

## Recent Improvements (January 2026)

### CLI Reorganization (Jan 9, 2026)

**Breaking Change: All Flags Removed**
- Converted ALL `--flags` to positional arguments for mobile-friendly CLI
- Examples:
  - `abox ps --all` → `abox list all`
  - `abox remove --force` → `abox remove force`
  - `abox service logs --lines 100` → `abox service logs 100`

**New Command Structure**
- Created logical command groups: `project`, `network`, `base`, `session`, `service`
- Added top-level shortcuts: `start`, `stop`, `list`, `ps`, `info`, `shell`, etc.
- Created dedicated `sessions.py` module for clean session management
- Removed duplicate `container.py` with old flagged commands

**Test Coverage**
- All CLI tests passing (13/13 session warning tests)
- Help text updated to reflect positional arguments
- See `COMPLETED_WORK_SUMMARY.md` for full details

### Codebase Refactoring - Phases 0-5 (Jan 8-9, 2026)

**Phase 0: Critical Bug Fixes**
- Fixed `AGENTBOX_DIR` hard-coded path (now auto-detects)
- Fixed notification socket path (uses proper runtime directory)

**Phase 1: Foundation**
- Created `boxctl/utils/` package:
  - `exceptions.py`: 12 custom exception classes
  - `logging.py`: BoxctlLogger with Rich console
  - `tmux.py`: 4 utility functions
  - `config_io.py`: JSON config I/O helpers
- Created `host_config.py`: Centralized HostConfig singleton

**Phase 2: Config Consolidation**
- **Breaking**: Moved packages from `packages.json` → `.agentbox.yml`
- Updated ProjectConfig with `packages` property
- Migration: Merge packages.json content into .agentbox.yml

**Phase 3: Remove Hard-coded Constants**
- Eliminated all hard-coded paths, ports, timeouts
- Everything now configurable via host config
- 30+ occurrences of hard-coded values removed

**Phase 4: Code Organization**
- Split `helpers.py` into 6 modular files:
  - `tmux_ops.py`, `agent_commands.py`, `completions.py`
  - `config_ops.py`, `context.py`, `utils.py`
- Removed duplicate functions
- Cleaned up imports

**Phase 5: Error Handling**
- Added logging framework
- Improved error messages
- Added exception hierarchy

**Results**
- 27 refactoring commits
- 149 unit tests passing
- No circular dependencies
- Zero duplicated functions
- See `REFACTORING_COMPLETE_PHASES_0-5.md` for full report

### Testing Infrastructure (Jan 8-9, 2026)

**Docker-in-Docker Integration Tests**
- Comprehensive DinD test suite for full workflow coverage
- 24+ tests covering:
  - Container lifecycle (24 tests)
  - Networking (9 tests)
  - Workspaces (11 tests)
  - Session management (6 tests)
  - MCP integration (7 tests)
  - Proxy service (5 tests)
- Path translation helpers for DinD scenarios
- Documentation: `tests/dind/README.md`, `tests/dind/STATUS.md`

### Session Monitoring (Jan 8, 2026)

**Stall Detection**
- Automatic session idle notifications
- 30-second idle threshold detection
- Background monitoring thread in proxy
- Session state tracking: IDLE → ACTIVE → STALE → NOTIFIED
- Task agent enhancement for better stall summaries
- Notification deduplication

### Research & Documentation (Jan 9, 2026)

**Comprehensive Feature Research**
- Consolidated all feature notes into `NOTES.md`
- Researched 14 major topics:
  - PWA best practices for terminal apps
  - Service Worker & WebSocket strategies
  - MCP server patterns and specifications
  - Mobile UI optimization (touch targets, thumb zones)
  - Push notification APIs
  - Git worktree patterns for parallel development
  - Session monitoring and observability
  - Tmux buffer capture techniques
  - Context compression strategies
  - Agent task handoff and orchestration
  - IndexedDB vs LocalStorage
  - Cache versioning and updates
  - Workbox library patterns
  - Autonomous agent workflows

**Documentation Improvements**
- Added 40+ authoritative references
- Created 10+ code examples
- Defined 6-phase implementation roadmap
- 935 lines of research added to NOTES.md
- File grew from 106 to 1,041 lines

### Documentation & Positioning

**Emphasizing Autonomous Agents**
- Repositioned Boxctl as a tool for autonomous background work
- Super modes (`superclaude`, `supercodex`, `supergemini`) now highlighted as primary workflow
- Updated all examples to show autonomous usage patterns
- Added comprehensive autonomous mode safety section
- Quick start now demonstrates super agent workflow

**Terminology Updates**
- Changed "volume" commands to "workspace" for consistency
- `boxctl workspace add/list/remove` now documented correctly

### Reliability Improvements

**Terminal Corruption Fix**
- Fixed terminal corruption after Docker and tmux operations
- Proper terminal reset after agent commands exit
- Cleaner exit handling for long-running sessions

**Container Init Performance**
- Optimized container startup time
- Removed slow `chown` operations for `/context` directory
- Faster initialization on first run

**Credential Bootstrapping**
- Fixed credential bootstrapping order to prevent conflicts
- Credentials copied in correct sequence (Claude → Codex → SSH → Git)
- SSH and Git configs remain read-only for security

### MCP Server Enhancements

**Expanded MCP Library**
- Added 5 commonly used MCP servers to library
- Total of 16 pre-configured MCPs available
- New servers: Brave Search, Google Maps, Slack, Redis, Playwright

**MCP Auto-Install**
- MCP dependencies now auto-install when added to project
- Support for npm packages (e.g., `@modelcontextprotocol/server-postgres`)
- Support for pip packages (e.g., MySQL connector)
- `boxctl mcp install <name>` for manual installation in running containers

**MCP Post-Install Support**
- Added `mcp-meta.json` to track MCP installation requirements
- Automatic dependency resolution
- Better error messages when dependencies missing

**MySQL MCP with Pip Support**
- Added MySQL MCP server configuration
- Auto-installs Python MySQL connector via pip
- Works with MySQL and MariaDB

### Configuration System

**Improved Config Sync**
- More reliable bidirectional config synchronization
- Better handling of concurrent config changes
- Config watcher stability improvements

**Environment Variable Support**
- `.boxctl/.env` files now auto-loaded on container start
- Reload detection (polled every 5 seconds)
- `.boxctl/.env.local` support for local overrides
- Variable substitution in MCP configs: `${VAR_NAME}`

**Workspace Mount Collision Prevention**
- Added validation to prevent mounting over `/workspace`
- Better error messages for mount path conflicts
- Safer volume management

### Testing & Quality

**Integration Test Suite**
- Comprehensive integration tests for CLI commands
- Tests for container lifecycle, MCP management, and config sync
- Automated test runs on changes
- Better reliability and fewer regressions

**Test Coverage**
- Fixed test suite issues
- All core functionality covered by tests
- CI/CD ready

### Documentation

**Comprehensive Guides**
- New [README.md](README.md) with complete feature overview
- New [MCP Server Catalog](docs/mcp-servers.md)
- Updated [Getting Started](docs/getting-started.md)
- Updated [Workflows](docs/workflows.md)
- Updated [Configuration Guide](docs/configuration.md)
- Updated [Architecture](docs/architecture.md)

**Detailed MCP Documentation**
- Individual README files for each MCP server
- Setup instructions and examples
- Security best practices
- Troubleshooting guides

### Agent Support

**Multi-Agent Parity**
- All agents (Claude, Codex, Gemini) now have IDE integration
- Consistent command structure across agents
- Same isolation and safety model
- Autonomous mode (super*) for all agents

**Agent Commands**
- `abox claude` - Standard Claude Code
- `abox superclaude` - Autonomous Claude with auto-approve
- `abox codex` - Standard Codex
- `abox supercodex` - Autonomous Codex
- `abox gemini` - Standard Gemini
- `abox supergemini` - Autonomous Gemini

### Developer Experience

**Session Management**
- Improved auto-reattach for agent sessions
- Session names now consistent and predictable
- Better handling of orphaned sessions

**Error Messages**
- Clearer error messages for common issues
- Better troubleshooting guidance
- Helpful suggestions when things go wrong

**Command Simplifications**
- Shorter command aliases still work (e.g., `abox` for `boxctl`)
- More intuitive command names
- Better help text

## Architecture Changes

### Base Image

**Added Tools**
- VSCode CLI (10MB standalone binary)
- Poetry and uv for Python package management
- Latest npm, yarn, and pnpm
- Up-to-date Claude Code, Codex, and Gemini CLIs

**Optimizations**
- Reduced layer count for faster builds
- Better caching of dependencies
- Smaller final image size

### Container Runtime

**Improved Lifecycle**
- Better container state management
- Cleaner shutdown and restart
- Preserved tmux sessions across rebuilds

**Performance**
- Faster container creation
- Quicker credential bootstrapping
- Optimized config sync polling

## Breaking Changes

### CLI Commands (Jan 9, 2026)

**All `--flags` removed** - Commands now use positional arguments only:

| Old Command (with flags) | New Command (positional) |
|--------------------------|--------------------------|
| `abox ps --all` | `abox list all` |
| `abox remove --force` | `abox remove force` |
| `abox service logs --lines 100` | `abox service logs 100` |
| `abox service logs --follow` | `abox service follow` |
| `abox start --name mycontainer` | `abox start` (auto-detects from directory) |

**Command structure reorganized**:
- `container` group → split into `project` and `network` groups
- `session list-all` → `session listall` (no hyphen)

### Configuration (Jan 8, 2026)

**Package configuration moved**:
- `packages.json` → `.agentbox.yml` (packages section)
- Migration required: Copy your packages.json content into .agentbox.yml

Other changes remain backward compatible with existing projects.

## Migration Guide

### Upgrading from Previous Versions

1. Pull latest changes:
   ```bash
   cd /path/to/boxctl
   git pull
   ```

2. Rebuild base image:
   ```bash
   abox update
   ```

3. (Optional) Rebuild project containers:
   ```bash
   cd ~/projects/my-app
   abox rebuild
   ```

### Migrating CLI Commands

**Update scripts and workflows** to use positional arguments instead of flags:

```bash
# Old (with flags)
abox ps --all
abox service logs --lines 100 --follow
abox remove --force

# New (positional)
abox list all
abox service logs 100
abox service follow
abox remove force
```

**Update command group references**:
- Replace `container` commands → use `project` or `network` groups
- Replace `session list-all` → use `session listall`

### Migrating Package Configuration

If you have a `packages.json` file in your `.boxctl/` directory:

1. Open `.agentbox.yml` in your editor
2. Add a `packages:` section:
   ```yaml
   packages:
     - package1
     - package2
   ```
3. Copy your packages from `packages.json` into the new section
4. Remove the old `packages.json` file

Example migration:

```json
// Old: .boxctl/packages.json
["ripgrep", "fd-find", "bat"]
```

```yaml
# New: .agentbox.yml
packages:
  - ripgrep
  - fd-find
  - bat
```

Other `.boxctl/` configurations work without changes.

### New Features to Try

After upgrading, try these new features:

**IDE Integration**:
```bash
# Install VSCode Dev Containers extension
code --install-extension ms-vscode-remote.remote-containers

# Attach to container
# VSCode Command Palette → "Dev Containers: Attach to Running Container"

# Now /ide commands work!
```

**MCP Auto-Install**:
```bash
boxctl mcp add postgres  # Auto-installs npm package
boxctl mcp add mysql     # Auto-installs pip package
```

**Environment Variables**:
```bash
# Create .boxctl/.env
echo "GITHUB_TOKEN=ghp_xxx" >> .boxctl/.env

# Use in configs with ${GITHUB_TOKEN}
# Auto-reloads when .env changes!
```

## Future Plans

### In Progress

- VSCode workspace trust configuration
- Additional MCP servers (AWS, GCP, Azure)
- Improved notification system
- Better multi-project dashboards

### Planned

- Support for more IDEs (JetBrains, Neovim remote)
- Web UI for container management
- Built-in MCP server for Kubernetes
- Agent collaboration (multiple agents on same task)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Areas We'd Love Help With

- **Documentation**: More examples, tutorials, and guides
- **MCP Servers**: Pre-configured setups for popular tools
- **Testing**: Additional test coverage and scenarios
- **Bug Fixes**: See [Issues](https://github.com/scharc/boxctl/issues)

## Acknowledgments

Boxctl is built on top of amazing open source projects:

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) by Anthropic
- [OpenAI Codex](https://github.com/openai/codex)
- [Google Gemini CLI](https://github.com/google/gemini-cli)
- [Model Context Protocol](https://modelcontextprotocol.io) specification
- [Docker](https://docker.com) for containerization
- [tmux](https://github.com/tmux/tmux) for session management

## Support

- **Issues**: https://github.com/scharc/boxctl/issues
- **Discussions**: https://github.com/scharc/boxctl/discussions
- **Documentation**: https://github.com/scharc/boxctl/tree/main/docs

---

**Thank you for using Boxctl!** 🚀
