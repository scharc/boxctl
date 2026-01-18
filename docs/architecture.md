# Architecture

How Agentbox works under the hood.

## The Big Picture

One base Docker image with all the tools. One container per project directory.

```
agentbox-base:latest        # Built once, reused for all projects
    ↓
agentbox-frontend           # Container for ~/projects/frontend
agentbox-backend            # Container for ~/projects/backend
agentbox-my-app             # Container for ~/projects/my-app
```

Each container mounts its project directory at `/workspace`. Your code stays on your host, the container just has access to that one directory.

## File Layout

### Your Project

```
my-app/
├── .agentbox/
│   ├── config.json         # Claude settings, synced to container
│   ├── codex.toml          # Codex settings, synced to container
│   ├── volumes.json        # Extra directory mounts
│   └── state/              # Runtime state (gitignored)
├── AGENTS.md               # Agent context (auto-managed section)
├── AGENT.md                # Symlink → AGENTS.md
├── CLAUDE.md               # Symlink → AGENTS.md
└── [your code here]
```

### Inside the Container

```
/workspace/                 # Your project (read-write)
/home/abox/.claude/         # Runtime Claude config (read-write, synced)
/home/abox/.codex/          # Runtime Codex config (read-write, synced)
/home/abox/.agentbox/       # notify.sock symlink
/agentbox/library/          # MCP and skill library (read-only)
/context/<name>/            # Extra volume mounts
/root/.claude/              # Bootstrapped credentials (read-only)
/root/.ssh/                 # SSH keys (read-only)
/root/.gitconfig/           # Git config (read-only)
```

## Config Sync System

The challenge: Claude uses JSON, Codex uses TOML. You want changes to sync between host and container, but also between different agent formats.

The solution: split and merge scripts.

### Scripts

**Claude**:
- `bin/merge-config.py` - Merge host configs into runtime
- `bin/split-config.py` - Extract changes back to host

**Codex**:
- `bin/merge-codex-config.py` - Merge host configs into runtime
- `bin/split-codex-config.py` - Extract changes back to host

### How Merge Works

When the container starts or when config files change:

1. Read global baseline from `/agentbox/library/config/default/config.json`
2. Read project config from `/workspace/.agentbox/config.json`
3. Deep merge them (project takes precedence)
4. Write to `/home/abox/.claude/config.json` (runtime config)

The agent reads from the runtime config and sees both global defaults and project-specific overrides.

### How Split Works

When the agent edits config inside the container:

1. Read runtime config from `/home/abox/.claude/config.json`
2. Read global baseline
3. Calculate differences (what changed from baseline)
4. Write only differences to `/workspace/.agentbox/config.json`

This keeps project config minimal - just the overrides.

### Special Handling

MCP servers and skills are always preserved in project config, even if they happen to match the global baseline. This makes it explicit which MCPs are enabled for each project.

### The Watcher

`bin/config-watcher.sh` runs inside the container and polls every 2 seconds:

1. Check if `/workspace/.agentbox/config.json` changed → run merge
2. Check if `/home/abox/.claude/config.json` changed → run split

Polling instead of inotify because it works across all filesystem types (NFS, bind mounts, etc.).

## Container Lifecycle

### 1. Build Base Image

One time (or when you run `agentbox update`):

```bash
docker build -f Dockerfile.base -t agentbox-base:latest .
```

This image has:
- Ubuntu 24.04
- Bash (default shell)
- Node.js, Python, Git, Docker CLI
- Claude, Codex, Gemini CLIs
- tmux for session management

### 2. Init Project

```bash
cd ~/projects/my-app
agentbox init
```

Creates `.agentbox/` directory with default configs and `AGENTS.md`.

### 3. Start Container

```bash
agentbox start
```

Or just run `abox claude` - it auto-starts if needed.

Creates container `agentbox-my-app` with:
- Project directory mounted at `/workspace`
- Extra volumes mounted under `/context/<name>`
- Credentials copied from host (bootstrap)
- Config watcher started in background
- Container stays running (detached)

### 4. Run Commands

```bash
abox claude
abox superclaude
abox shell
```

All commands:
1. Check if container exists → create if needed
2. Check if container is running → start if needed
3. Execute command inside container via `docker exec`

For agent commands, they run in tmux. If a session with that name exists, attach to it. Otherwise create new session.

### 5. Stop/Remove

```bash
agentbox stop        # Stop container, keep it on disk
agentbox remove      # Delete container entirely
```

Your project files and `.agentbox/` stay on host. Next start creates a fresh container with the same config.

## AGENTS.md Generation

`AGENTS.md` has an auto-managed section and a user-editable section.

### Auto-Managed Section

Surrounded by `<!-- AGENTBOX:BEGIN -->` and `<!-- AGENTBOX:END -->`.

Generated by `_render_managed_section()` in `agentbox/cli.py`:

1. Read `.agentbox/config.json` for MCP servers
2. Read `.agentbox/volumes.json` for extra mounts
3. Render markdown listing enabled MCPs, skills, mounts
4. Include workflow instructions (commit often, use notify)

### Update Triggers

The managed section updates when you:
- Run `agentbox init`
- Run `agentbox mcp add/remove`
- Run `agentbox skill add/remove`
- Run `agentbox volume add/remove`

The update preserves everything outside the managed section.

### Symlinks

`AGENT.md` and `CLAUDE.md` are symlinks to `AGENTS.md`. Different agent conventions can read the same context file.

## Notification Flow

Desktop notifications from autonomous agents.

### Setup

```bash
agentbox proxy install --enable
```

Creates systemd user service at `~/.config/systemd/user/agentbox-notify.service`.

The service runs a Python proxy that:
1. Listens on `/run/user/<uid>/agentbox-notify.sock` (Unix socket)
2. Receives JSON messages
3. Calls `notify-send` to show desktop notifications

### Inside Container

The socket is symlinked at `/home/abox/.agentbox/notify.sock`.

The notify MCP sends messages to this socket.

When an autonomous agent needs input, it uses the notify MCP to send a message. You see a desktop notification.

## Multi-Agent Support

Adding a new agent CLI (e.g., Mistral):

1. **Add to base image** (`Dockerfile.base`):
   ```dockerfile
   RUN npm install -g mistral-cli
   ```

2. **Create split/merge scripts**:
   - `bin/merge-mistral-config.py` - Handle Mistral's config format
   - `bin/split-mistral-config.py` - Extract changes

3. **Add CLI commands** (`agentbox/cli.py`):
   ```python
   @cli.command()
   def mistral(project, args):
       _run_agent_command("mistral", args, ...)

   @cli.command()
   def supermistral(project, args):
       _run_agent_command("mistral", ("--auto",) + args, ...)
   ```

4. **Update watcher** (`bin/config-watcher.sh`):
   Add Mistral to the sync loop.

5. **Rebuild**: `agentbox update`

The pattern is: implement split/merge for the agent's config format, add CLI commands, done.

## Security Model

### Read-Only Mounts

Credentials and SSH keys are mounted read-only. The agent can use them but not modify them.

### Workspace Isolation

The container can only write to `/workspace` (your project directory). It cannot access:
- Other projects on your machine
- System files
- Your home directory (except bootstrapped credentials, read-only)

### Docker Socket

The Docker socket is NOT mounted by default. Only when you explicitly:

```bash
agentbox mcp add docker
```

This gives the agent Docker control for tasks that need it (building images, running containers). Be aware this is powerful.

### Network Isolation

Containers use Docker's default bridge network. They can access the internet but not other containers unless you set up networking explicitly.

## Why Polling for Config Sync?

You might wonder why we poll every 2 seconds instead of using inotify (filesystem events).

Reasons:
- Works across all filesystem types (NFS, CIFS, bind mounts)
- inotify events don't always propagate through bind mounts
- Simpler implementation, fewer edge cases
- 2 seconds is fast enough for config changes

## Adding to the Library

### Custom MCP

```
library/mcp/my-mcp/
├── config.json
└── README.md
```

The `config.json` follows Claude's MCP server format:
```json
{
  "command": "npx",
  "args": ["-y", "my-mcp-package"]
}
```

Run `agentbox mcp add my-mcp` to enable for a project.

### Custom Skill

```
library/skills/my-skill/
├── instructions.md
└── README.md
```

The format is up to you. When enabled, the skill name appears in `AGENTS.md` for the agent to see.

## Container Naming

Containers are named `agentbox-{project-directory-name}`.

If your project is at `~/projects/my-app`, the container is `agentbox-my-app`.

This keeps things predictable and makes it easy to identify which container belongs to which project.
