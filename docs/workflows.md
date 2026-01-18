# Workflows

Common patterns for using Agentbox.

## Daily Usage

The typical flow once everything is set up:

```bash
cd ~/projects/my-app
abox claude
# Work with the agent
# Ctrl-a d to detach

# Later...
abox claude  # Auto-reattaches to the same session
```

No need to find session names or use attach commands. Typing the same command reconnects automatically.

## Autonomous Mode

Let the agent work in the background while you do other things.

```bash
cd ~/projects/my-app
abox superclaude
```

Give it a task:
```
Refactor the API handlers and add comprehensive tests
```

The agent runs with auto-approve enabled. It can make changes without asking permission each time.

Detach with `Ctrl-a d`. The agent keeps working. You get a desktop notification when it needs input.

Check on it later:
```bash
abox superclaude  # Reconnects to see progress
```

### Safe Because Isolated

Autonomous mode is powerful but safe because:
- Container only has access to this one project
- Other repos on your machine are unreachable
- SSH keys and credentials are read-only
- Host system files are inaccessible

If something goes wrong, the blast radius is just this one workspace.

## Multi-Directory Projects

Real projects often span multiple directories. Maybe you have:
- Frontend in `~/projects/my-app`
- Backend in `~/projects/api-server`
- Shared components in `~/projects/ui-lib`

Mount them all:

```bash
cd ~/projects/my-app
agentbox init
agentbox volume add ~/projects/api-server backend
agentbox volume add ~/projects/ui-lib shared
abox claude
```

Inside the container:
- `/workspace` → Frontend (current project)
- `/context/backend` → Backend
- `/context/shared` → Shared components

The agent can read across all of them but only write to `/workspace`.

## Project-Specific MCPs

Different projects need different tools. Configure per project:

```bash
# Frontend project
cd ~/projects/frontend
agentbox init
agentbox mcp add github
agentbox mcp add filesystem

# Backend project
cd ~/projects/backend
agentbox init
agentbox mcp add docker
agentbox mcp add github
```

Each project has its own MCP configuration in `.agentbox/config.json`.

## Session Management

### List Running Sessions

```bash
agentbox session list
```

Shows all tmux sessions in the container. But honestly, you rarely need this - just type `abox claude` to reconnect.

### Manual Attach (Alias)

```bash
agentbox session attach claude
```

Same as `abox claude` when a session already exists. The auto-reattach is the main workflow.

### Kill a Session

```bash
agentbox session remove claude
```

Useful if a session is stuck or you want to start fresh.

## Multiple Projects Running

Each project gets its own container. Run as many as you want:

```bash
# Terminal 1
cd ~/projects/frontend
abox superclaude
# Detach

# Terminal 2
cd ~/projects/backend
abox supercodex
# Detach

# Both agents working in parallel
agentbox ps  # See all containers
```

Switch between them by changing directories and running the command again.

## Container Management

### Start/Stop

Containers auto-start when you run `abox claude` or other commands. But if you want manual control:

```bash
agentbox start
agentbox stop
```

Stopped containers stay on disk. Start them again to resume.

### Remove Container

```bash
agentbox remove
```

Deletes the container but keeps your project files and `.agentbox/` config. Next `agentbox start` creates a fresh container with the same config.

### Rebuild from Scratch

```bash
agentbox rebuild
```

Removes the container and creates a new one. Useful if something got into a weird state.

### Clean Up

```bash
agentbox cleanup
```

Removes all stopped Agentbox containers across all projects.

## Updating Agentbox

When you pull new changes from the repo:

```bash
cd /path/to/agentbox
git pull
agentbox update
```

This rebuilds the base Docker image with any new tools or changes.

## Shell Access

Sometimes you want to poke around inside the container:

```bash
abox shell
```

Opens an interactive bash shell. You're at `/workspace` (your project). Explore, check logs, run commands manually.

Exit with `Ctrl-d` or `exit`.

## Desktop Notifications

Install the notification proxy to get desktop notifications from agents:

```bash
agentbox proxy install --enable
```

This creates a systemd user service that listens for notifications from containers.

Now when an autonomous agent needs input, you get a desktop notification via `notify-send`.

Check if it's running:
```bash
systemctl --user status agentbox-notify
```

## Adding Custom MCPs

1. Create the directory:
```bash
mkdir -p library/mcp/my-custom-mcp
```

2. Add `library/mcp/my-custom-mcp/config.json`:
```json
{
  "command": "npx",
  "args": ["-y", "my-mcp-package"]
}
```

3. Add `library/mcp/my-custom-mcp/README.md`:
```markdown
# My Custom MCP

Does cool stuff.
```

4. Enable in your project:
```bash
agentbox mcp add my-custom-mcp
```

## Working with Docker Inside

If your project needs Docker (to build images, run containers, etc.):

```bash
agentbox mcp add docker
```

This mounts the Docker socket into the container. The agent can now control Docker on your host.

**Careful**: This gives the agent significant power. Only enable when you need it.

## Credentials and SSH

On first container start, Agentbox copies credentials from your home directory:
- `~/.claude` → Container
- `~/.codex` → Container
- `~/.ssh` → Container (read-only)
- `~/.gitconfig` → Container (read-only)

If you update credentials on the host, stop and remove the container to re-bootstrap:

```bash
agentbox stop
agentbox remove
agentbox start
```

## Checking Container IP

If you run a web server inside the container:

```bash
agentbox ip
```

Shows the container IP. Access your app at `http://<ip>:3000`.

For stable hostnames:
```bash
agentbox hosts add my-app.local
```

Adds an entry to `/etc/hosts` pointing to the container IP.
