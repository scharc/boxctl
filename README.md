<p align="center">
  <img src="docs/assets/logo.svg" alt="Boxctl Logo" width="120"/>
</p>

<h1 align="center">Boxctl</h1>

<code>


 ███████████     ███████    █████ █████           █████    ████ 
░░███░░░░░███  ███░░░░░███ ░░███ ░░███           ░░███    ░░███ 
 ░███    ░███ ███     ░░███ ░░███ ███    ██████  ███████   ░███ 
 ░██████████ ░███      ░███  ░░█████    ███░░███░░░███░    ░███ 
 ░███░░░░░███░███      ░███   ███░███  ░███ ░░░   ░███     ░███ 
 ░███    ░███░░███     ███   ███ ░░███ ░███  ███  ░███ ███ ░███ 
 ███████████  ░░░███████░   █████ █████░░██████   ░░█████  █████
░░░░░░░░░░░     ░░░░░░░    ░░░░░ ░░░░░  ░░░░░░     ░░░░░  ░░░░░ 

</code>

**Safe containers for autonomous AI agents**

Run Claude, Codex, Gemini, or Qwen with full auto-approve permissions. They can't wreck your system because they're in a container. They can work while you sleep because git tracks everything. If something goes wrong, `git reset --hard` and you're back to normal.

**[See all features →](docs/features.md)**

## The Origin Story

I saw [Matt Brown](https://www.youtube.com/@mattbrwn) on YouTube do something wild: he set up a race between himself and an AI agent to reverse engineer an IoT binary exploit using Ghidra and Binary Ninja. Human vs machine, both working in parallel on the same problem.

I thought: **"I want this."**

Not just the competition - the workflow itself. An autonomous agent with full access to specialized tools, multiple directories mounted, complete isolation, safe to detach and let work in the background.

The closest thing was Dev Containers, but those are designed for IDE workflows. I wanted something simpler: Docker for isolation, agent CLIs for execution, no editor dependencies. Just give the agent a sandbox, point it at your project, and let it work.

That's Boxctl.

## Quick Start

```bash
# Install
git clone git@github.com:scharc/boxctl.git
cd boxctl
bash bin/setup.sh --shell zsh  # or bash

# Use it
cd ~/myproject
boxctl init
boxctl superclaude
```

That's it. Claude starts working with auto-approve enabled. Give it a task, detach (`Ctrl+A, D`), come back later.

**Short aliases:** `box` and `abox` are aliases for `boxctl`. Use whichever feels natural.

## Features

### Agents

**Autonomous agents** run with auto-approve - no permission prompts, continuous execution:
```bash
boxctl superclaude     # Claude with --dangerously-skip-permissions
boxctl supercodex      # Codex autonomous
boxctl supergemini     # Gemini autonomous
boxctl superqwen       # Qwen autonomous
```

**Interactive agents** ask permission for each action - good for exploration:
```bash
boxctl claude
boxctl codex
boxctl gemini
boxctl qwen
```

**Non-interactive** for automation and scripting:
```bash
boxctl run superclaude "implement feature X"
boxctl run claude "analyze this codebase"
```

→ [Agent Types](docs/04-dangerous-settings.md)

### agentctl (Container-Side CLI)

One of the most powerful features for daily work. Agents can manage their own sessions and worktrees from inside the container via MCP:

- **Switch branches** without leaving the conversation
- **Spawn parallel agents** on different worktrees
- **Detach and continue** working in the background
- **Session management** - list, attach, peek, kill

```bash
# Inside container (or via MCP tools)
agentctl worktree switch feature-auth superclaude
agentctl detach "implementing auth feature"
agentctl list
```

→ [agentctl Reference](docs/REF-C-agentctl.md)

### Parallel Work with Worktrees

Run multiple agents on different branches simultaneously:
```bash
boxctl worktree add feature-auth       # Create worktree
boxctl worktree superclaude feature-auth   # Run agent there
boxctl worktree list                   # See all worktrees
```

Each branch gets its own directory. Agents don't interfere.

→ [Parallel Work](docs/05-parallel.md)

### Sessions

Run multiple agents in one container:
```bash
boxctl session new superclaude feature     # New session
boxctl session list                        # See sessions
boxctl session attach feature              # Jump to one
```

### Multi-Agent Collaboration

Cross-agent review, analysis, and discussion via MCP:
```bash
boxctl mcp add boxctl-analyst
```

Agents can request peer review, get second opinions on plans, and run multi-agent discussions.

→ [Agent Collaboration](docs/REF-F-collaboration.md) · [Analyst MCP](docs/REF-H-analyst.md)

### Quick Menu (Mobile-Friendly)

Single-keypress navigation for phone keyboards:
```bash
boxctl q
```

Shows sessions, worktrees, actions. Press a letter to act. No typing commands.

→ [Work From Anywhere](docs/06-mobile.md)

### Packages and Workspaces

```bash
# Add packages the agent can use
boxctl packages add npm typescript eslint
boxctl packages add pip pytest black
boxctl packages add apt ffmpeg imagemagick

# Mount additional directories
boxctl workspace add ~/other-repo ro reference
boxctl workspace add ~/data rw datasets
```

→ [Configuration](docs/08-configuration.md)

### Port Forwarding

Ever given a container access to your local Chrome? With port forwarding, agents can control your browser via Chrome DevTools Protocol:

```bash
# Start Chrome with remote debugging
google-chrome --remote-debugging-port=9222

# Forward the port into the container
boxctl ports forward 9222
```

Now the agent can automate your browser, take screenshots, scrape pages - all from inside the container.

Works both ways:
```bash
boxctl ports expose 3000           # Container → Host (dev server)
boxctl ports forward 5432          # Host → Container (local postgres)
```

→ [CLI Reference](docs/REF-A-cli.md)

### Zero-Config Credential Sharing

Authenticate once on your host, every container just works. Boxctl auto-mounts:

| Credential | What it enables |
|------------|-----------------|
| **Claude** (`~/.claude/`) | No `claude login` in containers |
| **Codex** (`~/.codex/`) | OpenAI Codex auth |
| **OpenAI** (`~/.config/openai/`) | API keys |
| **Gemini** (`~/.config/gemini/`) | Google AI auth |
| **Qwen** (`~/.qwen/`) | Alibaba Qwen auth |
| **Git** (env vars) | Author name/email |
| **SSH** (configurable) | Git clone/push |

OAuth tokens auto-refresh. New containers immediately have access. No setup required.

GitHub CLI (`gh`) and GitLab CLI (`glab`) can be enabled in config.

→ [Configuration](docs/08-configuration.md)

### Desktop Notifications

The daemon bridges container and host:
```bash
boxctl service install     # Install as systemd service
```

Get notified when tasks complete, agents stall, or something needs attention.

→ [Daemon](docs/REF-B-daemon.md)

### Container Networking

Connect to other Docker containers running on your host:

```bash
boxctl network connect postgres-dev
boxctl network connect redis-cache
# Agent can now reach postgres-dev:5432 and redis-cache:6379
```

Your agent can interact with databases, message queues, APIs - any containerized service.

→ [Networking](docs/REF-G-network.md)

### Device Passthrough

Give agents access to hardware - audio, GPU, serial ports, cameras:

```bash
boxctl devices              # Interactive chooser
boxctl devices add /dev/snd # Audio devices
boxctl devices add /dev/dri/renderD128  # GPU
```

Devices that go offline won't break the container - they're skipped at startup.

→ [CLI Reference](docs/REF-A-cli.md)

### Conversation Logs

Review and export agent conversations:

```bash
boxctl logs list                   # See tracked sessions
boxctl logs show superclaude-1     # View recent messages
boxctl logs export superclaude-1   # Export to markdown
```

Full history with timestamps. Perfect for review or documentation.

→ [CLI Reference](docs/REF-A-cli.md)

### Docker-in-Docker

Give agents full Docker access (use with caution):

```bash
boxctl docker enable
```

Now your agent can build images, run containers, manage compose stacks. Powerful for DevOps tasks, but enables container escape - only use for trusted work.

→ [Configuration](docs/08-configuration.md)

## How It Works

```
┌─────────────────────────────────────────┐
│ YOUR MACHINE (Host)                     │
│                                         │
│   boxctl superclaude                    │
│   boxctl connect                        │
│   boxctl stop                           │
│                                         │
│   boxctld (daemon)                      │
│   ├── Desktop notifications             │
│   ├── Stall detection                   │
│   └── Port forwarding                   │
└─────────────────────────────────────────┘
              ↕
┌─────────────────────────────────────────┐
│ CONTAINER (Agent's World)               │
│                                         │
│   /workspace (your code)                │
│   /context/* (extra mounts)             │
│                                         │
│   agentctl (session/worktree mgmt)      │
│                                         │
│   Agent working autonomously...         │
│   ├── Edits files                       │
│   ├── Runs tests                        │
│   ├── Commits changes                   │
│   └── Notifies when done                │
└─────────────────────────────────────────┘
```

→ [Two Worlds](docs/02-two-worlds.md)

## Container Management

```bash
boxctl list            # Running containers
boxctl list all        # Include stopped
boxctl info            # Container details
boxctl stop            # Stop container
boxctl remove          # Delete container
boxctl rebase          # Rebuild with new config
```

→ [Day-to-Day](docs/07-containers.md)

## Migrating from Agentbox

If you're upgrading from the previous `agentbox` naming:

```bash
# Migrate global config (~/.config/agentbox → ~/.config/boxctl)
boxctl migrate

# Project directories are auto-migrated on first use
# (.agentbox → .boxctl)
```

The `boxctl migrate` command will also warn about any legacy containers or environment variables.

## Safety

**Container isolation:** Agents can only access the project directory and explicitly mounted paths. Your system, other projects, and home directory are unreachable.

**Git safety net:** Every change is tracked. Easy to review (`git diff`), easy to undo (`git reset --hard`).

**Credential isolation:** SSH keys (in `keys` mode) are copied into the container - changes don't affect your host. API tokens are synced to support OAuth refresh.

**Worst case:** Agent corrupts the project? `git reset --hard`. Container breaks? `boxctl remove && boxctl superclaude`. Back to normal in seconds.

## Prerequisites

- **Docker** - Container runtime
- **Python 3.12+** - For the CLI
- **Poetry** - Python dependency management
- **Agent CLI** - At least one: [Claude Code](https://docs.anthropic.com/en/docs/claude-code), Codex, Gemini, or Qwen

## Documentation

**[✨ Full Feature Guide](docs/features.md)** - Everything Boxctl can do

**Getting Started:**
- [Why Boxctl Exists](docs/01-why.md) - The origin story
- [Two Worlds](docs/02-two-worlds.md) - Architecture
- [First Steps](docs/03-first-steps.md) - Your first agent
- [Agent Types](docs/04-dangerous-settings.md) - Autonomous vs interactive
- [Parallel Work](docs/05-parallel.md) - Sessions and worktrees
- [Work From Anywhere](docs/06-mobile.md) - Mobile workflow
- [Day-to-Day](docs/07-containers.md) - Container management
- [Configuration](docs/08-configuration.md) - All the options

**Reference:**
- [CLI Reference](docs/REF-A-cli.md) - All commands
- [Daemon](docs/REF-B-daemon.md) - boxctld
- [agentctl](docs/REF-C-agentctl.md) - Container-side CLI
- [Library](docs/REF-E-library.md) - MCPs and skills
- [Collaboration](docs/REF-F-collaboration.md) - Peer review workflow
- [Networking](docs/REF-G-network.md) - Container networking
- [Analyst MCP](docs/REF-H-analyst.md) - Cross-agent analysis

## Contributing

Boxctl is my daily driver. Every feature exists because I needed it during real work - port forwarding for Chrome automation, gh/glab support for releasing to GitHub, worktree switching for parallel tasks.

**Using Boxctl and need something?** Open an issue with your story. What are you trying to do? What's missing? If it makes sense, I'll add it.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Contributors

Thanks to everyone who has contributed to Boxctl:

- **[@stephanj](https://github.com/stephanj)** - macOS compatibility fixes, non-interactive mode concept

## Acknowledgments

Boxctl was developed during my time at [ZKM | Center for Art and Media Karlsruhe](https://zkm.de) ([GitHub](https://github.com/zkmkarlsruhe/)). Thanks for providing the environment and support that made this project possible.

## License

MIT

## Support

- [Issues](https://github.com/scharc/boxctl/issues)
- [Discussions](https://github.com/scharc/boxctl/discussions)
