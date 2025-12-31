# Default Config Preset

This is the default Claude Code configuration for Agentbox containers.

## Philosophy

**Auto-accept everything, but break when Claude is uncertain.**

This config enables Claude to work autonomously inside the isolated container while preserving your control over critical decisions.

## Auto-Approve Settings

### Always Auto-Approved (No prompts)

These tools are auto-approved because they operate within the isolated container workspace:

- **Bash**: Execute commands (safe because container is isolated)
- **Read**: Read files (read-only operations are safe)
- **Write**: Write files (limited to workspace directory)
- **Edit**: Edit files (limited to workspace directory)
- **Glob**: Find files by pattern (read-only)
- **Grep**: Search file contents (read-only)
- **NotebookEdit**: Edit Jupyter notebooks
- **Task**: Launch specialized agents
- **WebFetch**: Fetch web content
- **WebSearch**: Search the web
- **LSP**: Language server protocol operations
- **TodoWrite**: Task list management
- **ExitPlanMode**: Exit planning mode

### Never Auto-Approved (Always asks)

These require human input:

- **AskUserQuestion**: Claude needs clarification or input
  - This ensures Claude breaks and asks when uncertain
  - You maintain control over architectural decisions
  - Critical for the "break when unclear" behavior

- **EnterPlanMode**: Entering planning mode
  - You decide when to enter planning phase
  - Prevents unnecessary planning for simple tasks

## Usage

This config is automatically mounted to containers in `/agentbox/library/config/default/`.

To use it in a project, you would copy it to your container's `.claude/` directory:

```bash
# Inside container
cp /agentbox/library/config/default/config.json ~/.claude/config.json
```

## Security

All auto-approved operations are safe because:

1. Container is isolated from host system
2. File operations limited to workspace directory
3. Dotfiles and SSH keys mounted read-only
4. No access to host files outside workspace

The worst case is Claude makes mistakes in your project code, which can be reverted via git.

## Customization

To create a custom config:

1. Copy this directory to `config/your-preset/`
2. Modify `config.json` as needed
3. Update README.md to document your changes
4. Copy into your project `.agentbox/config.json` or container `~/.claude/config.json`
