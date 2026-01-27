# Architecture: Two Worlds

Boxctl creates a clear separation between your machine and where agents work. Understanding this separation helps you understand why things work the way they do.

## Your World (The Host)

You sit at your laptop. This is your world - the host system.

You `cd` into your project directory and run `boxctl init` once to set things up. Then `boxctl superclaude` to start an agent. Simple commands, no flags to remember.

From here, you can:
- Start and stop containers
- Configure what tools agents have access to
- Add packages, mount directories, enable MCPs
- Check on running agents
- Connect to see what an agent is doing

**The commands you run here:** `boxctl init`, `boxctl superclaude`, `boxctl connect`, `boxctl stop`, `boxctl mcp add`, and all the other `boxctl` commands.

## The Agent's World (The Container)

When you run `boxctl superclaude`, an agent wakes up inside a Docker container.

It sees `/workspace` - your project code, mounted from your host. It has git, node, python, all the common dev tools. It starts working autonomously, reading files, making changes, running commands.

**Credentials are already there.** On first start, Boxctl sets up your git config and links API tokens (Claude, Codex, Gemini) into the container. The agent can authenticate with APIs and commit with your name - no manual setup required. API tokens stay synced so OAuth refresh works. SSH keys are configurable: copy them, mount them, or use agent forwarding for hardware keys.

The container is the agent's sandbox. Everything it does happens in there. If it goes haywire and corrupts something, your host system is safe. The worst case is you throw away the container and start fresh.

From inside, the agent can:
- Edit files in `/workspace`
- Run any dev commands (tests, builds, linters)
- Commit and push code
- Work on multiple branches using worktrees
- Send you notifications when something important happens

**The commands inside the container:** Agents use `agentctl` for session and worktree management. Desktop notifications are automatic (Claude via hooks, others via stall detection).

## The Boundary

Here's the key insight: **they can't directly talk to each other.**

The agent can't pop up a window on your desktop. It can't ring your phone. It doesn't know what other containers exist. It's isolated.

And you can't edit files inside the container directly (well, you can via Docker, but that's not the normal workflow). The container has its own filesystem, its own processes, its own world.

This isolation is the whole point. It's what makes autonomous agents safe.

## The Bridge: boxctld

But sometimes the agent needs to reach out. It finishes a task and wants to notify you. It's running a web server and wants to expose the port. It needs to copy something to your clipboard.

That's where `boxctld` comes in - a daemon running on your host that bridges the two worlds.

### How It Works

Each container establishes an SSH tunnel to the daemon. Through this tunnel, the container can:

1. **Send notifications** - Agent finishes a task, hook triggers notification, message appears on your desktop. Works even when you're away - the notification will be waiting when you get back.

2. **Forward ports** - Docker normally requires a container restart to change port mappings. With the SSH tunnel, ports are dynamic. Agent starts a web server on port 3000, wants to expose it - one command, no restart. Agent wants to debug Chrome remotely - expose the debug port, connect from host, see exactly what the agent sees.

3. **Detect stalls** - Sometimes agents get stuck. They're waiting for input, or they hit an error and stopped. The daemon monitors session activity and notifies you if an agent appears stalled. Useful when you're away from your desk.

4. **Enable tab completion** - The daemon tracks what's running so the CLI can offer fast tab completion for container names, sessions, and branches.

### Setting It Up

The daemon runs as a systemd user service:

```bash
boxctl service install          # Install as service
boxctl service status           # Check it's running
```

It starts automatically when you log in. Most of the time you don't think about it - it just works in the background.

### The Picture

```
┌─────────────────────────────────────────────────────────────┐
│ Your Host                                                   │
│                                                             │
│   You run: boxctl superclaude                            │
│                                                             │
│   boxctld (daemon)                                       │
│   ├── Receives notifications → Desktop alert               │
│   ├── Forwards ports → localhost:3000                      │
│   └── Monitors sessions → Stall detection                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                        ↕ SSH tunnel
┌─────────────────────────────────────────────────────────────┐
│ Container                                                   │
│                                                             │
│   Agent working on /workspace                              │
│   ├── Edits code                                           │
│   ├── Runs tests                                           │
│   ├── Commits changes                                      │
│   └── Hooks trigger → Tunnel → Your desktop                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Two isolated worlds. One secure tunnel connecting them. The agent works safely, and you stay informed.

## Origin Story

The daemon came from a practical need. Someone on Hacker News mentioned they wrote a Claude hook to notify them on Slack so they could work from their Android phone anywhere. That's a great idea - that's exactly the workflow worth enabling.

The SSH tunnel approach means it works everywhere. No firewall issues, no complex networking. Just a simple, encrypted connection between container and host.

Stall detection came from the same thinking. If you're away from your desk and an agent gets stuck, you want to know. The daemon watches session activity and pings you when something seems wrong.

## What Gets Mounted

When a container starts, Boxctl sets up these mount points:

### Your Code

| Container Path | Host Path | Mode | Purpose |
|----------------|-----------|------|---------|
| `/workspace` | Your project directory | rw | Where the agent works |
| `/context/*` | Configured workspaces | ro/rw | Additional directories you mount |

### Agent Credentials

| Container Path | Host Path | Mode | Purpose |
|----------------|-----------|------|---------|
| `/home/abox/host-claude` | `~/.claude` | rw | Claude OAuth tokens (synced for refresh) |
| `/home/abox/host-codex` | `~/.codex` | rw | Codex credentials |
| `/home/abox/claude.json` | `~/.claude.json` | rw | Claude state file |
| `/home/abox/openai-config` | `~/.config/openai` | rw | OpenAI config (if exists) |
| `/home/abox/gemini-config` | `~/.config/gemini` | rw | Gemini config (if exists) |

These are mounted read-write so OAuth token refresh works - when the agent refreshes a token, it updates your host credentials too.

### Agent Home Directories

Agent configurations are set up at container startup in the home directory:

| Directory | Purpose |
|-----------|---------|
| `~/.claude/` | Claude Code settings, CLAUDE.md instructions, skills |
| `~/.codex/` | Codex CLI config.toml (from host mount) |
| `~/.gemini/` | Gemini CLI settings with MCP |
| `~/.qwen/` | Qwen Code settings with MCP |

Configs are initialized from library templates, with optional project-level overrides from `.boxctl/config/`.

Note: Claude state (history, todos, etc.) is stored in container-local paths. History from one project doesn't leak into another.

### SSH (Configurable)

Depends on `ssh.mode` in `.boxctl.yml`:

| Mode | What's Mounted | Result |
|------|----------------|--------|
| `keys` | `~/.ssh` → `/host-ssh` (ro) | Keys copied into container on init |
| `mount` | `~/.ssh` → `/home/abox/.ssh` (rw) | Direct mount, changes sync both ways |
| `config` | `~/.ssh` → `/host-ssh` (ro) | Only config/known_hosts copied (no keys) |
| `none` | Nothing | No SSH setup |

With `forward_agent: true`, the SSH agent socket is also mounted for passphrase-protected or hardware keys.

### Boxctl Library

| Container Path | Host Path | Mode | Purpose |
|----------------|-----------|------|---------|
| `/boxctl/library/config` | Boxctl install | ro | Config templates |
| `/boxctl/library/mcp` | Boxctl install | ro | MCP server library |
| `/boxctl/library/skills` | Boxctl install | ro | Skills library |

### Optional

| Container Path | Host Path | Mode | When |
|----------------|-----------|------|------|
| `/var/run/docker.sock` | Docker socket | rw | `docker.enabled: true` |
| MCP-specific mounts | Varies | Varies | When MCPs require them |
| Boxctld socket | `~/.boxctl/` | ro | Always (for notifications) |

### Devices

Pass through host devices to the container for hardware access:

```bash
boxctl devices              # Interactive chooser - shows available devices
boxctl devices add /dev/snd # Add a specific device
```

The chooser auto-detects devices by category: audio (`/dev/snd`), GPUs (`/dev/dri/*`, `/dev/nvidia*`), serial ports (`/dev/ttyUSB*`), and cameras (`/dev/video*`).

**Safe for disconnection:** If a device goes offline (USB unplugged, etc.), the container won't fail to start - missing devices are skipped with a warning. This is important for IoT workflows where devices come and go.

## What's Next

- **[Getting Started](03-first-steps.md)** - Get your first agent running
- **[Agent Types](04-dangerous-settings.md)** - Choose the right agent for your task
- **[Configuration](08-configuration.md)** - Customize your setup

## Technical References

- **[boxctld](REF-B-daemon.md)** - Daemon configuration and capabilities
- **[agentctl](REF-C-agentctl.md)** - Container-side CLI reference
- **[Tunnel Protocol](REF-D-tunnel.md)** - Technical details of the SSH tunnel
