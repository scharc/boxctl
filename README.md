# Agentbox

```
 ______   ______  ________ __    __ ________ __
 /      \ /      \|        \  \  |  \        \  \
|  ▓▓▓▓▓▓\  ▓▓▓▓▓▓\ ▓▓▓▓▓▓▓▓ ▓▓\ | ▓▓\▓▓▓▓▓▓▓▓ ▓▓____   ______  __    __
| ▓▓__| ▓▓ ▓▓ __\▓▓ ▓▓__   | ▓▓▓\| ▓▓  | ▓▓  | ▓▓    \ /      \|  \  /  \
| ▓▓    ▓▓ ▓▓|    \ ▓▓  \  | ▓▓▓▓\ ▓▓  | ▓▓  | ▓▓▓▓▓▓▓\  ▓▓▓▓▓▓\\▓▓\/  ▓▓
| ▓▓▓▓▓▓▓▓ ▓▓ \▓▓▓▓ ▓▓▓▓▓  | ▓▓\▓▓ ▓▓  | ▓▓  | ▓▓  | ▓▓ ▓▓  | ▓▓ >▓▓  ▓▓
| ▓▓  | ▓▓ ▓▓__| ▓▓ ▓▓_____| ▓▓ \▓▓▓▓  | ▓▓  | ▓▓__/ ▓▓ ▓▓__/ ▓▓/  ▓▓▓▓\
| ▓▓  | ▓▓\▓▓    ▓▓ ▓▓     \ ▓▓  \▓▓▓  | ▓▓  | ▓▓    ▓▓\▓▓    ▓▓  ▓▓ \▓▓\
 \▓▓   \▓▓ \▓▓▓▓▓▓ \▓▓▓▓▓▓▓▓\▓▓   \▓▓   \▓▓   \▓▓▓▓▓▓▓  \▓▓▓▓▓▓ \▓▓   \▓▓
```

**Run autonomous AI agents safely, without the Docker ceremony.**

I watched a YouTuber race an autonomous agent to hack an IoT device. The agent won. That kind of power is incredible, but running `claude --dangerously-skip-permissions` on your host machine? You just gave the agent your entire filesystem, every credential, all your projects.

Agentbox fixes this. One Docker container per project. The agent gets auto-approve power inside, you get blast radius control outside. Simple CLI, no Docker expertise needed.

## Quick Example

```bash
cd ~/projects/my-app
agentbox init
abox superclaude
> Your task: refactor the API endpoints and add tests

# Press Ctrl-a d to detach
# Agent keeps working in background
# Desktop notification when it needs you

abox superclaude  # Auto-reattaches to same session
```

The agent runs at full speed but can only touch this one project. Your other repos, your SSH keys, your host system - all safe.

## What You Get

- **Simple CLI**: `agentbox claude` instead of Docker flags
- **Auto-approve safely**: Run agents with full permissions in isolated containers
- **Auto-reattach**: Type the same command again to reconnect to your session
- **Real workflow support**: Mount related directories (backend, frontend, shared libs)
- **Library system**: Reusable MCP servers and skills, enable per project
- **Multi-agent**: Claude, Codex, Gemini all work the same way
- **Desktop notifications**: Get notified when background agents need input

## Installation

**Requirements**: Docker, Python 3.12+, Poetry

```bash
git clone git@github.com:scharc/agentbox.git
cd agentbox
bash bin/setup.sh --shell zsh
```

The setup script installs dependencies, builds the base image, and sets up shell completion.

See [Getting Started](docs/getting-started.md) for detailed first-run walkthrough.

## Common Commands

```bash
agentbox init              # Set up current project
agentbox claude            # Run Claude (interactive)
agentbox superclaude       # Run Claude (auto-approve)
agentbox codex             # Run Codex
agentbox gemini            # Run Gemini

# Detach with Ctrl-a d, reattach by typing the command again

agentbox mcp add github    # Enable GitHub MCP for this project
agentbox volume add ~/backend api   # Mount backend code

agentbox session list      # See running sessions
agentbox ps                # List containers
agentbox update            # Rebuild base image
```

Short alias: `abox` = `agentbox`

## Documentation

- **[Getting Started](docs/getting-started.md)** - First run walkthrough
- **[Configuration](docs/configuration.md)** - How configs work, MCP/skills, volumes
- **[Workflows](docs/workflows.md)** - Common workflows and examples
- **[Notifications](docs/notifications.md)** - Desktop notifications for autonomous agents
- **[Architecture](docs/architecture.md)** - How it works under the hood

## Why Agentbox?

Docker gives you isolation but comes with complexity. Agentbox abstracts it:

- No memorizing Docker commands
- Credentials bootstrapped automatically
- Config syncs between host and container
- Multiple related directories mounted cleanly
- One container per project, managed for you
- Works with any CLI agent (Claude, Codex, Gemini, future ones)

If you have a workflow that already works with agents, Agentbox fits right in. You get isolation without changing how you work.

## Platform Support

Currently targets Linux, developed and tested on Ubuntu. Other platforms may work but are not tested. Contributions welcome.

## Contributing

Open an issue or send a pull request. The project grows by real world use and the stories that come with it.

## License

MIT
