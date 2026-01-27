# Configuration

Boxctl is customizable but has sensible defaults. You can go deep or just use it out of the box.

This guide covers all configuration options - but you don't need to read it all. Start with the defaults, customize when you need to.

## The Philosophy

**Project-level config** (`.boxctl.yml`) controls what an agent can do in a specific project. Packages, mounts, MCPs, ports. Different projects can have different setups.

**Host-level config** (`~/.config/boxctl/`) sets your personal defaults and daemon settings. These apply across all your projects.

**Agent instructions** (`.boxctl/agents.md`, `.boxctl/superagents.md`) tell agents how to behave. Project conventions, things to avoid, workflow guidelines. Edit freely - they're yours.

---

## Quick Reference

**Add packages:**
```bash
boxctl packages add npm typescript
boxctl packages add pip pytest
# Auto-rebuilds the container
```

**Mount another directory:**
```bash
boxctl workspace add ~/other-repo ro reference
# Auto-rebuilds the container
```

**Enable an MCP:**
```bash
boxctl mcp add boxctl-analyst
# Auto-rebuilds if the MCP needs mounts
```

All these commands automatically rebuild the container to apply changes.

---

## Configuration Hierarchy

```
~/.config/boxctl/           # Host-level config (user preferences)
├── config.yml                # boxctld settings, timeouts, web server
├── mcp/                      # Custom MCP servers (override library)
└── skills/                   # Custom skills (override library)

/path/to/project/             # Project-level config
├── .boxctl.yml             # Main project config (SSH, packages, ports, etc.)
└── .boxctl/                # Generated runtime files
    ├── agents.md             # Agent instructions template
    ├── superagents.md        # Super agent instructions template
    ├── skills/               # Installed skills (shared by all agents)
    ├── mcp/                   # Installed MCP server code
    ├── mcp-meta.json         # MCP installation tracking (deployed to ~/.mcp.json)
    ├── config/               # Project-level agent config overrides (optional)
    │   └── claude/           # Claude settings overrides
    ├── LOG.md                # Development log
    └── workspaces.json       # Workspace mount tracking

/boxctl/library/            # Built-in library (inside container)
├── config/                   # Config templates
│   └── boxctl.yml.template
├── mcp/                      # Built-in MCP servers
└── skills/                   # Built-in skills
```

---

## 1. Project Config: `.boxctl.yml`

**Location:** Project root (e.g., `/workspace/.boxctl.yml`)
**Purpose:** Configure the container for this specific project
**Applied:** On `boxctl rebase` or container creation
**Model:** `boxctl/models/project_config.py`

### SSH Configuration

```yaml
ssh:
  enabled: true          # Enable SSH access (default: true)
  mode: keys             # How to provide SSH credentials
  forward_agent: false   # Forward SSH agent socket
```

**SSH Modes:**
| Mode | What it does | Use case |
|------|--------------|----------|
| `none` | No SSH setup | Projects that don't need git SSH |
| `keys` | Copy all ~/.ssh files into container | Default, works for most setups |
| `mount` | Bind mount ~/.ssh read-write | Keys change frequently |
| `config` | Copy only config/known_hosts | Use with `forward_agent: true` for hardware keys |

**forward_agent:** Required when `mode: config` since no private keys are copied. Also useful for passphrase-protected keys.

### Automatic Credential Sharing

Boxctl automatically shares your host AI credentials with the container. No configuration needed.

**How it works:**

| Host Path | Container Access | Purpose |
|-----------|------------------|---------|
| `~/.claude/` | Symlinked to `~/.claude/.credentials.json` | Claude OAuth tokens |
| `~/.codex/` | Symlinked to `~/.codex/auth.json` | Codex authentication |
| `~/.config/openai/` | Symlinked to `~/.config/openai/` | OpenAI CLI config |
| `~/.config/gemini/` | Symlinked to `~/.config/gemini/` | Gemini CLI config |
| `~/.claude.json` | Symlinked to `~/.claude.json` | Claude client state |

**Technical details:**

- Host directories are mounted read-write (not individual files)
- Container-init creates symlinks to expected locations
- Directory mounts avoid stale inode issues when OAuth tokens refresh
- Credentials authenticated on host work immediately in containers

**Why directory mounts?**

When OAuth tokens refresh, the credential file is replaced (new inode). If we mounted the file directly, the container would still see the old content. By mounting the parent directory, the container sees file updates even after replacement.

**Git author:**

Git commits use your host's `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL` environment variables. If not set, defaults to your username.

### CLI Credentials (gh/glab)

GitHub CLI (`gh`) and GitLab CLI (`glab`) credentials are **opt-in** for security. Enable them in `.boxctl.yml`:

```yaml
credentials:
  gh: true      # Mount ~/.config/gh (GitHub CLI)
  glab: true    # Mount ~/.config/glab-cli (GitLab CLI)
```

Or use `boxctl reconfigure` to enable interactively.

When enabled:
- Credentials are mounted **read-only** from your host
- `gh` and `glab` commands in the container use your existing authentication
- No need to re-authenticate inside the container

### Workspace Mounts

```yaml
workspaces:
  - path: ~/projects/shared-lib    # Host path
    mount: shared-lib              # Name (mounted at /context/shared-lib)
    mode: ro                       # ro (read-only) or rw (read-write)
```

### Container Connections

```yaml
containers:
  - name: postgres-dev      # Docker container name
    auto_reconnect: true    # Reconnect if container restarts
```

Adds the boxctl container to the same Docker network as the specified container.

### Packages

```yaml
system_packages:           # apt packages (legacy, same as packages.apt)
  - ffmpeg
  - imagemagick

packages:
  apt: []                  # apt install <package>
  npm: []                  # npm install -g <package>
  pip: []                  # pip install <package>
  cargo: []                # cargo install <package>
  post: []                 # Custom shell commands after packages
```

### Environment Variables

```yaml
env:
  NODE_ENV: development
  DATABASE_URL: postgres://localhost/mydb
```

### Port Configuration

```yaml
ports:
  mode: tunnel             # tunnel (via boxctld) or docker (native)
  host:                    # Expose container ports on host
    - "3000"               # container:3000 -> host:3000
    - "8080:3000"          # container:3000 -> host:8080
  container:               # Forward host ports into container
    - "5432"               # host:5432 -> container:5432
```

**Port modes:**
- `tunnel`: Uses SSH tunnel via boxctld (preferred, survives container restart)
- `docker`: Native Docker port mapping (requires rebuild to change)
- `auto`: Automatically selects tunnel if boxctld is running, otherwise docker

### Resources

```yaml
resources:
  memory: 4g               # Memory limit
  cpus: 2.0                # CPU limit
```

### Security

```yaml
security:
  seccomp: unconfined      # Required for debugging tools (strace, gdb)
  capabilities:
    - SYS_PTRACE           # For debugging
```

### Devices

Pass through hardware devices to the container:

```bash
boxctl devices              # Interactive chooser
boxctl devices list         # See configured and available
boxctl devices add /dev/snd # Add specific device
```

Or configure directly in `.boxctl.yml`:
```yaml
devices:
  - /dev/snd               # Audio device
  - /dev/dri/renderD128    # GPU
```

**Note:** Devices that are unavailable at container start are skipped automatically - the container won't fail if a USB device is unplugged.

### Docker Socket Access

```yaml
docker:
  enabled: true            # Mount /var/run/docker.sock
```

### Task Agents (Notification Enhancement)

```yaml
task_agents:
  enabled: false           # Enable AI-enhanced notifications
  agent: claude            # Agent to use (claude, codex)
  model: fast              # Model alias (see below)
  timeout: 30              # Seconds to wait for response
  buffer_lines: 50         # Lines of terminal buffer to analyze
  enhance_hooks: true      # Enhance hook notifications
  enhance_stall: true      # Enhance stall detection notifications
  prompt_template: "..."   # Custom prompt for summarization
```

**Model aliases:** Use these generic names that work with any agent:

| Alias | Claude | Codex (OpenAI) | Use case |
|-------|--------|----------------|----------|
| `fast` | haiku | gpt-4o-mini | Quick summaries, low cost |
| `balanced` | sonnet | gpt-4o | Good quality, moderate cost |
| `powerful` | opus | o3 | Best quality, higher cost |

You can also use agent-specific model names directly (e.g., `haiku`, `gpt-4o`).

### Stall Detection

```yaml
stall_detection:
  enabled: true            # Detect when agent appears stuck
  threshold_seconds: 30.0  # Seconds of inactivity before notification
```

### MCP Servers and Skills

```yaml
mcp_servers:
  - agentctl               # Names of MCP servers to enable
  - boxctl-analyst

skills:
  - westworld              # Names of skills to enable
```

---

## 2. Host Config: `~/.config/boxctl/config.yml`

**Location:** `~/.config/boxctl/config.yml`
**Purpose:** User preferences for boxctld daemon and host behavior
**Applied:** On boxctld startup
**Model:** `boxctl/models/host_config.py`

### Web Server

```yaml
web_server:
  enabled: true            # Enable web UI
  host: 127.0.0.1          # Legacy single host (if hosts is empty)
  hosts:                   # Bind to multiple addresses
    - 127.0.0.1
    - tailscale            # Special: resolves to Tailscale IP
  port: 8080
  log_level: info
```

### Network (Port Tunneling)

```yaml
network:
  bind_addresses:          # Addresses for port tunnels
    - 127.0.0.1
    - tailscale            # Expose on Tailscale network
```

### Tailscale Monitor

```yaml
tailscale_monitor:
  enabled: true
  check_interval_seconds: 30.0   # How often to check for IP changes
```

### Notifications

```yaml
notifications:
  timeout: 2.0             # Timeout for notify-send
  timeout_enhanced: 60.0   # Timeout for AI-enhanced notifications
  deduplication_window: 10.0  # Seconds to deduplicate same notification
  hook_timeout: 5.0        # Timeout for user notify hooks
```

### Host Task Agents

```yaml
task_agents:
  enabled: false           # Host-level task agent config
  agent: claude
  model: fast              # Model alias: fast, balanced, powerful
  timeout: 30
  buffer_lines: 50
```

See [Task Agents](#task-agents-notification-enhancement) for model alias details.

### Stall Detection (Host-level)

```yaml
stall_detection:
  enabled: true
  threshold_seconds: 30.0
  check_interval_seconds: 5.0
  cooldown_seconds: 60.0
```

### LiteLLM Proxy

LiteLLM provides multi-provider LLM access with automatic fallback. When enabled, a LiteLLM proxy runs in the container, providing an OpenAI-compatible API that can route to multiple providers.

```yaml
litellm:
  enabled: true
  port: 4000                    # Proxy port (localhost only)

  # Provider configurations
  providers:
    openai:
      api_key: ${OPENAI_API_KEY}

    anthropic:
      api_key: ${ANTHROPIC_API_KEY}

  # Model aliases with fallback chains
  models:
    default:                    # Primary model alias
      - provider: openai
        model: gpt-4o

    fast:
      - provider: openai
        model: gpt-4o-mini

  # Fallback behavior
  fallbacks:
    on_rate_limit: true         # Fallback on 429 errors
    on_context_window: true     # Fallback on context exceeded
    on_error: true              # Fallback on other errors

  # Router settings
  router:
    num_retries: 3
    timeout: 120
    retry_after_seconds: 60
```

**API Keys:** Use `${ENV_VAR}` syntax to reference environment variables. Set them in your shell or in `~/.config/boxctl/.env`.

**Usage:** Once enabled, the proxy is available at `http://127.0.0.1:4000/v1` inside the container. Use the `litellm` MCP server for tool-based access.

### Timeouts

```yaml
timeouts:
  container_wait: 6.0           # Wait for container to start
  container_wait_interval: 0.25 # Polling interval
  web_connection: 2.0           # Web socket connection timeout
  web_resize_wait: 0.1          # Wait after terminal resize
  proxy_connection: 2.0         # Proxy connection timeout
  stream_registration: 5.0      # Stream registration timeout
  tmux_command: 2.0             # Tmux command timeout
```

### Polling

```yaml
polling:
  web_output: 0.1          # Web terminal output polling
  stream_monitor: 0.01     # Stream data monitoring
  session_check: 5.0       # Session health check
```

### Terminal Defaults

```yaml
terminal:
  default_width: 80
  default_height: 24
```

### Paths

```yaml
paths:
  boxctl_dir: null       # Override boxctl installation dir
```

---

## 3. MCP Server Library

**Locations:**
- Built-in: `/boxctl/library/mcp/` (inside container)
- Custom: `~/.config/boxctl/mcp/` (user overrides)

**Structure:**
```
mcp/<server-name>/
├── config.json           # Server configuration
├── server.py             # Server implementation (or package.json for npm)
├── README.md             # Description
└── commands/             # Optional slash commands
    └── <command>.md
```

**config.json format:**
```json
{
  "name": "server-name",
  "description": "What this server does",
  "config": {
    "command": "python3",
    "args": ["/path/to/server.py"],
    "env": {}
  },
  "install": {
    "pip": ["fastmcp>=2.0.0"],
    "npm": []
  }
}
```

**MCP-level .env files:**

MCPs can include a `.env` file in their directory for default environment variables:

```
mcp/<server-name>/
├── config.json
├── .env              # Optional: default env vars
└── server.py
```

When an MCP is added to a project, variables from `.env` are merged into the config's `env` section. This is useful for:
- API keys that should be shared across all projects
- Default configuration values
- Secrets that shouldn't be committed to git (add `.env` to `.gitignore`)

Variables defined in `config.json`'s `env` section take precedence over `.env` values.

**Usage:** Add to `.boxctl.yml`:
```yaml
mcp_servers:
  - agentctl
  - my-custom-server
```

Or use CLI: `boxctl mcp add <name>`

---

## 4. Skills Library

**Locations:**
- Built-in: `/boxctl/library/skills/` (inside container)
- Custom: `~/.config/boxctl/skills/` (user overrides)

**Structure:**
```
skills/<skill-name>/
├── SKILL.md              # Main skill definition with YAML frontmatter
└── commands/             # Optional slash commands
    └── <command>.md
```

**SKILL.md format:**
```markdown
---
name: westworld
description: Diagnostic modes for coding agents
triggers:
  - diagnostic mode
  - show goals
---

# Instructions for the agent when skill is activated
...
```

**Usage:** Add to `.boxctl.yml`:
```yaml
skills:
  - westworld
```

Or use CLI: `boxctl skill add <name>`

---

## 5. Agent Instructions

Understanding how agent instructions work is key to customizing agent behavior.

### How Instructions Are Assembled

When you run `boxctl claude` or `boxctl superclaude`, the system assembles a system prompt from multiple sources:

```
┌─────────────────────────────────────────────────────────┐
│ Final System Prompt (what the agent sees)               │
├─────────────────────────────────────────────────────────┤
│ 1. .boxctl/agents.md         (base instructions)      │
│ 2. .boxctl/superagents.md    (if super* agent)        │
│ 3. Dynamic Context             (generated at runtime)   │
│    - Available MCP servers                              │
│    - Workspace mounts                                   │
│    - Installed skills                                   │
│    - Slash commands                                     │
└─────────────────────────────────────────────────────────┘
```

**Regular agents** (`claude`, `codex`, `gemini`) get `agents.md` + dynamic context.

**Super agents** (`superclaude`, `supercodex`, `supergemini`) get `agents.md` + `superagents.md` + dynamic context.

### agents.md - Base Instructions

**Location:** `.boxctl/agents.md`
**Editable:** Yes
**Copied from:** `library/config/default/agents.md` on `boxctl init`

This file tells agents about their environment:
- They're running inside a Docker container
- Working directory is `/workspace`
- What tools are available (`agentctl`, automatic notifications via hooks)
- What they CAN'T do (run `boxctl` commands, access host filesystem)
- Workflow best practices

**Customize this file** to add project-specific instructions that apply to all agents. Add your notes below the `---` separator line.

Example customizations:
```markdown
---

## Project Notes

- This is a Python/FastAPI project
- Run tests with `pytest tests/`
- Database migrations: `alembic upgrade head`
- Never commit directly to main branch
```

### superagents.md - Autonomous Mode Instructions

**Location:** `.boxctl/superagents.md`
**Editable:** Yes
**Copied from:** `library/config/default/superagents.md` on `boxctl init`

This file adds instructions for autonomous agents running with `--dangerously-skip-permissions`:
- Auto-approve mode reminder
- Autonomous workflow guidelines
- Commit frequently, notify on completion
- Safety guidelines even with full permissions

**Customize this file** for project-specific autonomous behavior. Add notes below the `---` separator.

Example customizations:
```markdown
---

## Autonomous Guidelines

- Always run `make test` before committing
- Push to feature branches, never directly to main
- Send notification after completing major tasks
- If tests fail, fix before moving on
```

### Dynamic Context

Dynamic context is generated at runtime and appended to agent instructions. You don't edit this directly—it's assembled from your configuration:

**MCP Servers:** Lists all MCP servers configured in `.boxctl/mcp-meta.json` (deployed to `~/.mcp.json`). Agents use this to know what tools they have.

**Workspace Mounts:** Shows additional directories mounted at `/context/`. Helps agents know what external files they can access.

**Skills:** Lists available skills from `.boxctl/skills/`. Tells agents to use the Skill tool to invoke them.

**Slash Commands:** Lists available `/commands` from `.claude/commands/`. Tells agents when to use them.

### Why Two Files?

The separation exists because:

1. **Different trust levels.** Regular agents ask for permission. Super agents execute autonomously. Different instructions are appropriate.

2. **Gradual escalation.** Start with `boxctl claude`, switch to `boxctl superclaude` when you trust the agent's judgment.

3. **Customization flexibility.** You might want all agents to know about your test framework, but only super agents to auto-push to remote.

### Updating Instructions

After editing instruction files:
- **New sessions** pick up changes immediately
- **Existing sessions** keep their original instructions
- Kill the session and start fresh to apply changes

---

## 6. Runtime Files (`.boxctl/`)

These files are generated/managed automatically:

| File | Purpose | Editable |
|------|---------|----------|
| `agents.md` | Base agent instructions | Yes (template) |
| `superagents.md` | Super agent instructions | Yes (template) |
| `skills/` | Installed skills (shared by all agents) | No (managed) |
| `mcp/` | Installed MCP server code | No (managed) |
| `mcp-meta.json` | Tracks MCP installations (deployed to ~/.mcp.json) | No (managed) |
| `config/` | Project-level agent config overrides | Yes (optional) |
| `LOG.md` | Development log | Yes (append) |
| `workspaces.json` | Workspace mount tracking | No (managed) |

---

## 7. Configuration Priority

1. **Environment variables** (highest priority)
   - `AGENTBOX_DIR` - Override boxctl installation path
   - `AGENTBOX_PROJECT_DIR` - Override project directory

2. **Project config** (`.boxctl.yml`)
   - Per-project settings

3. **Host config** (`~/.config/boxctl/config.yml`)
   - User preferences

4. **Library defaults** (`library/config/`)
   - Built-in defaults

5. **Pydantic model defaults** (lowest priority)
   - Hardcoded fallbacks

---

## 8. Common Workflows

### Adding packages
```yaml
# Edit .boxctl.yml
packages:
  pip:
    - requests
    - pandas
```
Then run: `boxctl rebase`

### Exposing a port (no rebuild needed)
```bash
boxctl ports expose 3000        # Container:3000 -> Host:3000
boxctl ports expose 3000 8080   # Container:3000 -> Host:8080
```

### Forwarding host port (no rebuild needed)
```bash
boxctl ports forward 5432       # Host:5432 -> Container:5432
```

### Adding an MCP server
```bash
boxctl mcp add boxctl-analyst             # Add from library
boxctl rebase                  # Apply changes
```

### Adding a workspace mount
```yaml
# Edit .boxctl.yml
workspaces:
  - path: ~/other-project
    mount: other
    mode: ro
```
Then run: `boxctl rebase`

### Customizing agent instructions
Edit `.boxctl/agents.md` or `.boxctl/superagents.md` directly. Changes apply to new sessions.

---

## 9. Validation

Configurations are validated using Pydantic models:
- Invalid values show warnings but fall back to defaults
- Version mismatches are warned about
- Package names are validated for shell safety

Run `boxctl config migrate` to update old configs to the latest format.

---

## See Also

- [CLI Reference](REF-A-cli.md) - All `boxctl` commands
- [boxctld](REF-B-daemon.md) - Host daemon configuration details
- [agentctl](REF-C-agentctl.md) - Container-side CLI
- [Library](REF-E-library.md) - MCPs and skills
