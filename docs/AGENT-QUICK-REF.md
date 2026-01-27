# Quick Reference for AI Agents

## Where Am I?
You are **inside a Docker container**. This is your sandbox.

## The Two Worlds

### INSIDE (Where You Are)
```
Location: Docker container
Tools:
  - agentctl         # Manage git worktrees & tmux sessions
  - git, node, python, docker CLI, etc.
  - Notifications: Claude via hooks, others via stall detection

Directories:
  /workspace         # Your project (read-write)
  /context/*         # Extra mounts (usually read-only)
  /home/abox/        # Container home directory
```

### OUTSIDE (Host System)
```
Location: User's laptop/workstation
Tools:
  - boxctl         # Manage containers, MCP servers, config
  - abox             # Quick launcher (abox claude, abox shell)
  - Web proxy        # Notification bridge + web UI

You CANNOT run these from inside the container!
```

## Key Commands

### What YOU Can Run (Inside Container)
```bash
# Manage worktrees and branches
agentctl switch_branch feature/new-api
agentctl list_worktrees
agentctl get_current_context

# Regular development
git status
npm test
python script.py

# Notifications are sent automatically via hooks on task completion
```

### What USER Runs (Host System)
```bash
# Manage your container
boxctl start
boxctl stop
boxctl rebuild

# Add resources
boxctl mcp add boxctl-analyst
boxctl workspace add /path/to/code ro ref

# Launch agents
abox superclaude
abox shell
```

## Communication Flow

```
┌──────────────────┐
│   Host System    │
│                  │
│  boxctl CLI    │──┐
│  abox launcher   │  │ Creates/manages
│  Web proxy       │  │
└──────────────────┘  │
         ↕            │
    Unix socket       │
         ↕            ↓
┌──────────────────────────┐
│  Container (You)         │
│                          │
│  Agent CLI               │
│  agentctl                │
│  Hooks ──────────────────┤→ Notifications (automatic)
│  /workspace (your code)  │
└──────────────────────────┘
```

## Coding Style (IMPORTANT)

When adding features to boxctl or agentctl:

### NO FLAGS - Use Positional Args Only
```bash
# ✅ CORRECT - positional arguments
boxctl workspace add /path/to/dir ro mydir
boxctl mcp add boxctl-analyst
agentctl worktree add feature-branch

# ❌ WRONG - do not use flags
boxctl workspace add /path/to/dir --mode ro --name mydir
boxctl mcp add boxctl-analyst force
agentctl worktree add feature-branch create
```

**Rule:** All boxctl/agentctl commands use positional arguments in the correct order. No flags, no options. Follow existing command patterns.

## Important Files

### Container-side (you can edit & test these)
```
bin/container-init.sh       # Container startup script
bin/agentctl               # Worktree management CLI
bin/abox-notify            # Notification command (used by hooks)
library/mcp/agentctl/      # Agentctl MCP server
```

### Host-side (edit but test from host)
```
boxctl/container.py      # Container lifecycle
boxctl/proxy.py          # Notification proxy + web UI
boxctl/cli.py           # Main CLI
Dockerfile.base           # Base image definition
pyproject.toml            # Poetry dependencies (DO NOT use pip)
```

### Templates (copied to user projects)
```
.boxctl/agents.md        # Agent instructions
.boxctl/superagents.md   # Super agent instructions
.boxctl/config.yml       # Project config
```

### Python Dependencies (Poetry Project)
**Boxctl uses Poetry** for dependency management:
```bash
# Add dependency - edit pyproject.toml:
[project.dependencies]
new-package = ">=1.0.0,<2.0.0"

# Add dev dependency:
[tool.poetry.group.dev.dependencies]
pytest-mock = "^3.12.0"

# User must install (from host):
poetry install
```

**Important:** Don't use `pip install` for boxctl dependencies - use Poetry.

## Testing Your Changes

### Run unit tests (fast, no Docker needed)
```bash
pytest tests/                    # All unit tests
pytest tests/test_config.py      # Specific test file
pytest -k "test_mcp"            # Tests matching pattern
pytest -v                        # Verbose output
```

### Run integration tests (Docker-in-Docker)
```bash
./tests/dind/run_dind_tests.sh              # All DinD tests
./tests/dind/run_dind_tests.sh -k networking # Specific tests
./tests/dind/run_dind_tests.sh -v           # Verbose
```

### Before committing new features
```bash
# 1. Run your specific tests
pytest tests/test_yourfeature.py -v

# 2. Run full suite to check for regressions
pytest tests/

# 3. For container/Docker changes, run DinD tests
./tests/dind/run_dind_tests.sh -k relevant_pattern
```

## Common Tasks

### Work on a new branch in parallel
```bash
agentctl switch_branch feature/awesome-feature
agentctl switch_session feature/awesome-feature-superclaude
# Now you're in a new worktree for that branch
```

### Notifications
Notifications are automatic - no manual commands needed:
- **Claude**: Hooks trigger on task completion and permission requests
- **Codex/Gemini/Qwen**: Stall detection notifies when agent appears idle

## Quick Troubleshooting

### "Command not found: boxctl"
You're inside the container. `boxctl` runs on the host only.
Use `agentctl` instead, or ask the user to run `boxctl` commands.

### "Notification didn't appear"
Check if notification socket exists:
```bash
ls -la /home/abox/.boxctl/notify.sock
```
If missing, user needs to run: `boxctl service start` on host

### "Can't modify container config"
You can't add MCP servers or workspaces from inside.
User must run on host: `boxctl mcp add <name>` or `boxctl rebuild`

## Remember

✅ You CAN:
- Edit any file in /workspace
- Run agentctl for worktrees
- Use all installed dev tools and MCP servers
- Run tests with pytest
- Notifications are automatic (Claude via hooks, others via stall detection)

❌ You CANNOT:
- Run boxctl/abox commands (host-only)
- Add MCP servers (requires host rebuild)
- Mount new directories (requires host config)
- Access host filesystem outside mounts

🎯 Your job is to:
1. Work on the code
2. Write tests for new features
3. Run `pytest tests/` to ensure tests pass
4. Commit changes (code + tests together)
5. **After completing work:** Update `.boxctl/agents.md` or `.boxctl/superagents.md` with learnings to help future agents

## Self-Improvement

After completing tasks, update the agent instructions to help future sessions:

**Add project-specific notes to `.boxctl/agents.md` or `.boxctl/superagents.md`:**
- Architecture details (key directories, files, patterns)
- Common workflows or commands
- Testing procedures
- Pitfalls to avoid
- Anything that would have helped you work faster

**Example:**
```markdown
## Project-Specific Guidelines

### API Structure
- Backend uses FastAPI, all routes in /api
- Auth via JWT tokens in headers
- Models in /api/models using SQLAlchemy

### Testing
- Run with test DB: `pytest --db=test`
- Mock external APIs using pytest-mock
```

Keep it concise, actionable, and helpful for future agents!
