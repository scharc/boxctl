# Agentbox

Agentbox is a CLI that spins up per project Docker containers with Claude, Codex, and Gemini ready to run. It keeps your workspace and config isolated while staying close to your normal development workflow. If you have ever wished that every project came with a clean desk, a fresh toolbelt, and no mysterious crumbs left by the last task, this is that wish in command line form.

This project is a work in progress. It currently targets Linux and is developed and tested on Ubuntu. Other platforms may work but are not tested. Contributions and feature requests are welcome.

Agentbox exists because of autonomous agents. The goal is to run long lived, auto approved agents in the background, keep them safely contained, and still get a clear signal when human input is needed. That signal is delivered through a small notify proxy that uses notify-send on the host.

If you are new to Agentbox, think of it as a way to get one container per project with the right tools and guardrails already set up. You enter the project directory, run a single command, and the container is there. No manual Docker run flags, no guessing which config to copy, and no clutter in your host environment.

Autonomous mode is the center of this project. The super commands run with auto approve enabled, so the agent can keep working unattended inside the container. You can detach, leave it running in the background, and rely on host notifications when it needs input. The whole point is that it runs inside the container, not your host, so you get isolation for the tools, logs, and config while the agent is busy thinking.

## Goals

The goal is simple and a little ambitious. Give each project a safe, repeatable, and comfortable environment without forcing you to relearn your workflow.

- Isolate tools and credentials per project
- Keep the developer workflow fast and familiar
- Support multiple projects running at the same time
- Make it easy to experiment without polluting the host

## Requirements

- Docker
- Python 3.12
- Poetry

## Installation

```bash
git clone git@github.com:scharc/agentbox.git
cd agentbox
poetry install
```

## Quick start

```bash
cd ~/projects/my-app
agentbox start
agentbox shell
```

That is the short version. You now have a dedicated container for the project, your code mounted at `/workspace`, and the agent CLIs waiting for you.

Agentbox will also attempt to bootstrap existing CLI credentials from your home directory so the agents can work without extra setup. It looks for known config folders and copies them into the container when available. Current sources include `~/.claude`, `~/.claude.json`, `~/.codex`, `~/.config/openai`, and `~/.config/gemini` (Gemini CLI bootstrap is included but not yet tested).

The CLI also keeps a project level agent context file up to date. When you run `agentbox init` or add MCP servers and skills, it updates `AGENTS.md` with a managed section so the active project configuration is visible at a glance. It also writes compatibility symlinks for `AGENT.md` and `CLAUDE.md` so different agents can pick up the same context.

The default agent context includes a few behavioral nudges such as commit often and keep a log in `.agentbox/LOG.md`. You can edit the file after `agentbox init` to tailor it to your workflow.

## Common commands

- `agentbox start` - Start a container for the current project
- `agentbox stop` - Stop the project container
- `agentbox ps` - List containers
- `agentbox shell` - Open an interactive shell
- `agentbox claude [ARGS]` - Run Claude Code
- `agentbox codex [ARGS]` - Run Codex
- `agentbox gemini [ARGS]` - Run Gemini
- `agentbox superclaude [ARGS]` - Run Claude Code with auto approve
- `agentbox supercodex [ARGS]` - Run Codex with auto approve
- `agentbox supergemini [ARGS]` - Run Gemini with auto approve
- `agentbox ip` - Show the container IP
- `agentbox update` - Rebuild the base image
- `abox` - Short alias for `agentbox`

## Autonomous mode

If you want a hands off workflow, start an auto approved agent and detach it in tmux. The container keeps running, and the notify proxy sends a host notification when the agent asks for human input.

```bash
agentbox superclaude
agentbox supercodex
agentbox supergemini
```

Run these from your project directory so the container is scoped to the right repo. If you want your API money to burn, this is the way to go. Let the agent explore, prototype, and dig into problems you did not think about. I have seen auto mode used to reverse an ARM binary and to poke at a stubborn IoT device until it started talking.

```bash
agentbox superclaude
# Detach from tmux with C-a d
```

## Shell completion

Agentbox ships with zsh and bash completion. Source the file that matches your shell from `completions/`.

```bash
# Zsh
source completions/agentbox-completion.zsh

# Bash
source completions/agentbox-completion.bash
```

The completion uses click's built in completion to suggest commands and session names.

## How it works

Agentbox manages a base image with tools preinstalled and then creates one container per project. The project directory is mounted at `/workspace` and a small project config lives in `.agentbox/`.

```
Host project directory            Container
--------------------            ------------------------
project/                        /workspace
  .agentbox/                    /home/abox
    config.json                 /home/abox/.claude
    codex.toml                  /home/abox/.codex
    volumes.json                /home/abox/.agentbox/notify.sock
  src/                          /agentbox/library
```

## Session management

Agentbox runs commands in tmux so you can detach and reattach without stopping the container. This is useful for long running tasks, experiments you want to park for later, or when you simply need to close your laptop and pretend it never happened.

- `agentbox session list` - List tmux sessions
- `agentbox session attach SESSION` - Attach to a tmux session
- `agentbox session remove SESSION` - Kill a tmux session

Detach from a session with `C-a d` if you already run tmux on the host. Override the prefix with `AGENTBOX_TMUX_PREFIX=C-b` or `AGENTBOX_TMUX_PREFIX=default` when launching `agentbox shell`, `agentbox claude`, and others.

## Hosts and networking

Agentbox can show the container IP or manage hostnames for local access. Use this when you want a stable name for a project service or when you are tired of remembering IPs.

- `agentbox ip` - Show the container IP
- `agentbox hosts add` - Add a hostname entry for the project container
- `agentbox hosts remove <hostname>` - Remove a hostname entry
- `agentbox hosts list` - List current hostnames

## MCP server library

Agentbox ships with a library of MCP server configs and can manage them per project. Think of it as a pantry you can pull from when a project needs extra tools.

- `agentbox mcp list` - List available MCP servers
- `agentbox mcp show <name>` - Show server details
- `agentbox mcp add <name>` - Add server to the project config
- `agentbox mcp remove <name>` - Remove server from the project config

The notify MCP is included by default for new projects. It lets an agent send a host notification through the proxy socket.

The Docker MCP is also available in the library. When you enable it, Agentbox mounts the Docker socket into the container so the agent can control Docker on the host. This is disabled by default and only mounted when you explicitly add the MCP to the project.

If you want your own MCP, add a new folder under `library/mcp/<name>` with a `config.json` and `README.md`. Once it exists, `agentbox mcp add <name>` wires it into the project config.

## Skills library

Skills are reusable instruction bundles you can enable per project. They act like short playbooks that guide the agent without you rewriting the same rules each time.

- `agentbox skill list` - List available skills
- `agentbox skill show <name>` - Show skill details
- `agentbox skill add <name>` - Add a skill to the project config
- `agentbox skill remove <name>` - Remove a skill from the project config

To create your own skill, add a new entry under `library/skills` and give it a short name you can refer to. Once it exists, `agentbox skill add` makes it available to the project container.

## Extra mounts

You can add extra host directories to the container under `/context/<name>`. This is useful for shared data, design assets, or that one reference repo you do not want to copy around.

- `agentbox volume list` - List mounts
- `agentbox volume add <path> <mount>` - Add a mount
- `agentbox volume remove <mount>` - Remove a mount

## Configuration

Optional `.agentbox.yml` in the project directory:

```yaml
version: "1.0"

system_packages:
  - ffmpeg
  - imagemagick

mcp_servers:
  - filesystem
  - github

hostname: my-app.local

env:
  NODE_ENV: development
```

Agentbox also keeps live project configuration in `.agentbox/`. When you run `agentbox init`, it creates these files and keeps them in sync with the runtime configs inside the container:

- `.agentbox/config.json` for Claude settings and MCP servers
- `.agentbox/codex.toml` for Codex settings and MCP servers
- `.agentbox/volumes.json` for extra mounts under `/context`

Config sync uses a lightweight polling watcher so edits on either side are reflected back to the project. This is intentional so it works across filesystems and bind mounts without relying on inotify.

## Notify proxy and systemd service

Agentbox can install a user systemd service for the host notification proxy. This is used by the notify MCP and any agent inside the container. It is the small but important piece that lets a container tap you on the shoulder without shouting across the room. Notifications are delivered via notify-send on the host.

The notify socket is exposed in the container at `/home/abox/.agentbox/notify.sock` and is backed by a stable symlink to `/run/user/<uid>/agentbox-notify.sock` so it survives proxy restarts.

- `agentbox proxy install` - Install the user service
- `agentbox proxy install --enable` - Install and start the service
- `agentbox proxy uninstall` - Remove the service

## Security notes

- Read only mounts for dotfiles and SSH keys
- Workspace limited to the mounted project directory
- Container cannot modify host files outside the workspace
- Host Docker access is disabled by default and only enabled via the Docker MCP

Docker socket access is only mounted when the Docker MCP is enabled for the project.

## Contributing

If this sounds useful, open an issue or send a pull request. Feature requests are welcome. The project grows by real world use and the stories that come with it.

## License

MIT
