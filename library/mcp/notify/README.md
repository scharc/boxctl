# Agentbox Notify MCP Server

Send host notifications from inside the container using the Agentbox notify socket.

## What it does

- Exposes a single tool: `notify`
- Sends notifications via `/home/abox/.agentbox/notify.sock`

## Usage

Add to your project:

```bash
abox mcp add notify
```

Then call the tool:

```
notify({ "title": "Agentbox", "message": "Hello", "urgency": "normal" })
```

### Parameters

- `title` (string, optional) - Notification title
- `message` (string, required) - Notification body
- `urgency` (string, optional) - `low`, `normal`, `high`, or `critical`
