# Notifications

How autonomous agents send desktop notifications to ask for help.

## The Problem

You start an autonomous agent with `abox superclaude`, give it a task, and detach. It works in the background.

Eventually it hits a decision point: "Should I delete these old migration files?" It needs your input, but you're not watching the terminal.

Desktop notifications solve this. The agent sends a notification to your desktop, you see it, you reattach and answer.

## How It Works

```
Agent in container → notify MCP → Unix socket → Proxy on host → notify-send → Your desktop
```

The agent uses the notify MCP server to send messages. Those go through a Unix socket to a proxy running on your host. The proxy calls `notify-send` and you see a desktop notification.

## Setup

Install the notification proxy as a systemd user service:

```bash
agentbox proxy install --enable
```

This creates `~/.config/systemd/user/agentbox-notify.service` and starts it.

Check if it's running:

```bash
systemctl --user status agentbox-notify
```

That's it. New projects get the notify MCP by default.

## Using It

From inside a container, agents can call the notify MCP:

```bash
agentbox shell
/usr/local/bin/notify "Title" "Message here" "normal"
```

You should see a desktop notification appear.

Urgency levels: `low`, `normal`, `high`, `critical`

Critical notifications play an audio alert.

## The Flow

When you run `agentbox init`, the notify MCP is enabled by default in `.agentbox/config.json`.

The notify MCP server lives at `library/mcp/notify/server.py`. It connects to a Unix socket at `/home/abox/.agentbox/notify.sock` inside the container.

That socket is a symlink pointing to `/run/user/<your-uid>/agentbox-notify.sock` on the host, which is mounted read-only into the container.

The proxy daemon listens on that socket. When it receives a message, it calls `notify-send` on the host with the title, message, and urgency level.

Your desktop notification daemon (dunst, mako, or whatever you use) shows the notification.

## Why This Design?

**Unix socket instead of HTTP**: Faster, simpler, more secure. File permissions control access, no network exposure.

**Systemd user service**: Runs as your user (not root), starts on login, auto-restarts on failure, integrates with journalctl for logs.

**Read-only mount**: The container mounts `/run/user/<uid>` read-only. It can connect to the socket but can't modify or delete it.

**Hard-coded paths**: We control the container build, so paths are known and stable. No environment variables, no configuration files, just works.

**Symlink for stability**: The socket is created by the proxy on the host. Inside the container, a symlink points to it. If the proxy restarts, the symlink still works.

## Troubleshooting

**No notifications appear**

Check if the proxy is running:
```bash
systemctl --user status agentbox-notify
```

If not, start it:
```bash
systemctl --user start agentbox-notify
```

Check if the socket exists:
```bash
ls -la /run/user/$(id -u)/agentbox-notify.sock
```

Test from inside a container:
```bash
agentbox shell
/usr/local/bin/notify "Test" "Hello" "normal"
```

**Proxy won't start**

Check logs:
```bash
journalctl --user -u agentbox-notify -n 50
```

Common issues:
- `DISPLAY` not set (needed for notify-send)
- D-Bus session not available
- notify-send not installed

**Notifications delayed**

The proxy processes messages sequentially. If you send many at once, they queue up. This is normal.

**No audio alert on critical**

Critical notifications try to play `/usr/share/sounds/freedesktop/stereo/bell.oga` via `paplay`.

If that doesn't work, falls back to TTY bell (`\a`).

Install `pulseaudio-utils` if you want audio alerts:
```bash
sudo apt install pulseaudio-utils
```

## Managing the Service

View logs in real-time:
```bash
journalctl --user -u agentbox-notify -f
```

Restart:
```bash
systemctl --user restart agentbox-notify
```

Stop:
```bash
systemctl --user stop agentbox-notify
```

Disable and uninstall:
```bash
agentbox proxy uninstall
```

## Security

The socket has `0o600` permissions (user-only read/write). Only you can connect.

The container mounts `/run/user/<uid>` read-only, so it can't modify the socket or interfere with other processes.

There's no rate limiting. A container can spam notifications. If that happens, stop the container or the proxy service.

No authentication. Any process inside the container can send notifications. But the container is isolated - you control what runs inside.

## Disabling Notifications

Stop the proxy service:
```bash
systemctl --user stop agentbox-notify
systemctl --user disable agentbox-notify
```

Or remove the notify MCP from your project:
```bash
agentbox mcp remove notify
```

Without the proxy running, agents can still try to send notifications, but they'll fail silently.
