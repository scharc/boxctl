# Configuration

Agentbox keeps configuration in `.agentbox/` in your project directory.

## The Basics

When you run `agentbox init`, you get:

```
.agentbox/
├── config.json    # Claude settings and MCP servers
├── codex.toml     # Codex settings and MCP servers
└── volumes.json   # Extra directory mounts
```

These files sync with the runtime config inside the container. Edit on host, agent sees changes. Agent edits inside container, you see changes on host.

## MCP Servers

MCP servers give agents extra capabilities. Agentbox has a library of pre-configured MCPs you can enable per project.

### See What's Available

```bash
agentbox mcp list
```

Shows all MCPs in the library with descriptions.

### Enable for This Project

```bash
agentbox mcp add github
agentbox mcp add filesystem
```

This updates `.agentbox/config.json` and `.agentbox/codex.toml`. The config watcher inside the container picks up changes within 2 seconds.

### Remove

```bash
agentbox mcp remove github
```

### Default MCPs

The `notify` MCP is enabled by default for all new projects. It lets agents send desktop notifications to your host.

### Add Your Own

Create `library/mcp/your-mcp/` in the agentbox repo:

```
library/mcp/your-mcp/
├── config.json    # MCP server definition
└── README.md      # Description
```

Then `agentbox mcp add your-mcp` enables it for the current project.

## Skills

Skills are reusable instruction bundles. Think of them as playbooks you can enable per project.

```bash
agentbox skill list              # See available skills
agentbox skill add python-project
agentbox skill remove python-project
```

Skills work like MCPs - add a folder under `library/skills/` and enable per project.

## Extra Volume Mounts

Real projects often span multiple directories. Mount them with:

```bash
agentbox volume add ~/projects/backend api
agentbox volume add ~/projects/shared-lib components
```

Inside the container:
- `/context/api` → Your backend code
- `/context/components` → Shared library

The agent can read across all of them.

List mounts:
```bash
agentbox volume list
```

Remove:
```bash
agentbox volume remove api
```

## How Config Sync Works

Each agent has its own config format:
- Claude uses JSON
- Codex uses TOML

Agentbox needs to:
1. Store project-specific MCPs and settings
2. Merge with global defaults
3. Sync changes bidirectionally

### The Flow

**Merge (Host → Container)**:
```
Global baseline config
    +
Project config (.agentbox/config.json)
    ↓
Runtime config (~/.claude/config.json)
```

**Split (Container → Agent)**:
```
Runtime config (edited by agent)
    -
Global baseline
    ↓
Project config (only differences)
```

A watcher inside the container polls every 2 seconds and syncs in both directions.

### Why Polling?

Works across all filesystem types (NFS, bind mounts, etc.) without relying on inotify events that don't always propagate.

### What Gets Preserved

MCP servers and skills are always kept in project config, even if they match the global baseline. This makes it clear which MCPs are enabled for each project.

## AGENTS.md Auto-Generation

When you `agentbox init`, it creates `AGENTS.md` in your project root. This file gives the agent context about your setup.

### Structure

```markdown
# Agent Context

<!-- AGENTBOX:BEGIN -->
## Agentbox Managed Context

### MCP
- MCP servers: github, filesystem

### Context Mounts
- `/context/backend` (ro)
- `/context/shared` (ro)

<!-- AGENTBOX:END -->

## Notes
- Your custom notes here
```

The section between `<!-- AGENTBOX:BEGIN -->` and `<!-- AGENTBOX:END -->` is auto-generated. When you add/remove MCPs, skills, or volumes, this section updates automatically.

Everything outside that section is yours to edit.

### Symlinks

`AGENT.md` and `CLAUDE.md` are symlinks to `AGENTS.md`. Different agent conventions can all read the same file.

## Direct Editing

You can also edit `.agentbox/config.json` or `.agentbox/codex.toml` directly. The changes sync to the container automatically.

Example (`.agentbox/config.json`):
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

Save the file, wait 2 seconds, and the agent inside the container sees the new MCP.
