# Getting Started

This guide walks you through your first Agentbox session.

## Prerequisites

You need:
- **Docker** - `docker run hello-world` should work
- **Python 3.12+** - `python3 --version`
- **Poetry** - `poetry --version`
- **An agent CLI** - At least one of Claude Code, Codex, or Gemini installed

If you don't have these, see the [Installation section](#installation) below.

## First Run

### 1. Install Agentbox

```bash
git clone git@github.com:scharc/agentbox.git
cd agentbox
bash bin/setup.sh --shell zsh
```

This takes a few minutes the first time - it builds a Docker image with all the tools.

### 2. Go to Your Project

```bash
cd ~/projects/my-app
```

Any directory with code works. Agentbox creates a container just for this project.

### 3. Initialize

```bash
agentbox init
```

Creates `.agentbox/` with config files and `AGENTS.md` with agent context.

### 4. Run an Agent

```bash
abox claude
```

You're now in Claude inside a container. Your project is at `/workspace`.

Try: "List the files in this directory"

### 5. Detach and Reattach

Press `Ctrl-a d` to detach. The agent stays running.

Type `abox claude` again - it reconnects to the same session. No need to find session names or use attach commands.

### 6. Try Autonomous Mode

```bash
abox superclaude
```

Give it a task: "Create a new file called test.txt with hello world in it"

It creates the file without asking permission. Because it runs in a container scoped to this project, that's safe. It can't touch your other repos.

Detach (`Ctrl-a d`) and let it work in the background.

## Next Steps

- Read [Workflows](workflows.md) for common usage patterns
- Read [Configuration](configuration.md) to add MCP servers and mount extra directories
- Check `agentbox --help` to see all commands

## Installation Details

### Docker

Ubuntu/Debian:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in
```

Verify: `docker run hello-world`

### Python 3.12

Ubuntu 24.04 includes it. For older versions:
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.12 python3.12-venv
```

### Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"
```

Add the export to your `.bashrc` or `.zshrc`.

### Agent CLIs

- **Claude Code**: https://docs.anthropic.com/en/docs/claude-code/overview
- **Codex**: Install via npm
- **Gemini**: Install Gemini CLI

Agentbox bootstraps credentials from your home directory automatically on first container start.
