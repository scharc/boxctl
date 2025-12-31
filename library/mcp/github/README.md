# GitHub MCP Server

Provides Claude with GitHub API access for repository operations.

## What it does

- Create/update issues and PRs
- Search repositories
- Manage branches
- Review code
- Update files via GitHub API

## Configuration

Requires a GitHub Personal Access Token.

### Get a Token

1. Go to https://github.com/settings/tokens
2. Generate new token (classic)
3. Select scopes: `repo`, `workflow`, `read:org`
4. Copy the token

### Add to Project

Edit `.agentbox/config.json`:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here"
      }
    }
  }
}
```

### Using Environment Variables

Better approach - reference from host:

1. Add to your `~/.bashrc` or `~/.zshrc`:
   ```bash
   export GITHUB_TOKEN="ghp_your_token_here"
   ```

2. In config use variable reference:
   ```json
   {
     "env": {
       "GITHUB_TOKEN": "${GITHUB_TOKEN}"
     }
   }
   ```

Container will inherit the token from host environment!

## Connection

- Connects to GitHub API via HTTPS
- Works from anywhere with internet
- No special network setup needed

## Example Usage

```bash
abox mcp add github
# Configure token in config.json
# Claude can now create PRs, issues, etc!
```
