# Docker MCP Server

Provides MCP access to the host Docker engine.

## How it works

Agentbox mounts `/var/run/docker.sock` only when the Docker MCP is enabled.

## Usage

```bash
abox mcp add docker
```

If a container is already running, rebuild it so the socket mount is applied.
