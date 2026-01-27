# Mobile Workflow

The whole point of Boxctl is to work from anywhere - including your phone in a coffee shop. The quick menu makes that practical.

## The Quick Menu

```bash
boxctl q                         # Or: boxctl quick
```

This opens a text UI designed for minimal typing:

```
AGENTBOX - myproject

SESSIONS
  a) superclaude-1        [active]
  b) superclaude-feature  [idle]
  c) shell-debug          [idle]

ACTIONS
  n) New session
  w) Worktrees
  m) MCPs
  s) Skills
  p) Ports

  0) Exit
```

Press a letter, things happen. No typing command names. No flags. No remembering syntax.

## Why This Matters

On a laptop with a full keyboard, commands are fine. But on a phone:

- Command history helps you find ONE command. Workflows need many.
- Typing `docker exec -it container-name bash` with autocorrect fighting you? Miserable.
- Flags like `--mount type=bind,source=...,target=...`? Forget it.

The quick menu reduces everything to single keypresses. Navigate with letters and numbers. Get things done without fighting your keyboard.

## The Phone Workflow

Here's what working from a phone actually looks like:

### Setup (Once)

1. Install [Tailscale](https://tailscale.com/) on your laptop and phone
2. Both devices join your Tailnet
3. Install a terminal app on your phone (Termux, iSH, Blink, etc.)

Now your phone can reach your laptop from anywhere.

### Daily Use

You're out getting coffee. You SSH into your laptop:

```bash
ssh mybox.tailscale.net
cd ~/myproject
boxctl q
```

The quick menu shows your running sessions. Press `a` to attach to the first one. See what the agent is doing.

Want to start something new? Press `n` for a new session, pick an agent type.

Done checking? Press `Ctrl+A`, then `D` to detach. The agent keeps working.

Later, you get a notification on your phone: "Task complete." You review from wherever you are.

### Multiple Projects

If you have agents running on different projects:

```bash
cd ~/project-one
boxctl q        # See project-one's sessions

cd ~/project-two
boxctl q        # See project-two's sessions
```

Each project has its own container, its own sessions, its own world.

## Notifications

When you're away, how do you know when something finishes?

Agents send notifications automatically:
- **Claude**: Hooks trigger on task completion and permission requests
- **Codex/Gemini/Qwen**: Stall detection notifies when agent appears idle

If you've set up `boxctld` (the daemon), these appear as desktop notifications. Even if you're SSH'd in from your phone, the notification fires on your laptop. Next time you're at your desk, you see it.

For truly mobile notifications, you can configure Telegram or a webhook to send to Slack, Discord, or a push notification service. The daemon supports custom notification channels.

## Stall Detection

Sometimes agents get stuck. They hit an error and stopped. They're waiting for something. The daemon can detect this.

When configured, if an agent shows no activity for a while (default: 30 seconds), you get a notification: "Agent appears stalled."

This is particularly useful when you're away. You don't want to come back hours later to find the agent stopped five minutes after you left.

## The Picture

```
┌─────────────────────┐
│ Your Phone          │
│                     │
│  SSH via Tailscale  │
│  ↓                  │
└─────────────────────┘
          ↓
┌─────────────────────┐
│ Your Laptop         │
│                     │
│  boxctl q         │
│  → Quick menu       │
│  → Sessions view    │
│  → Attach/detach    │
│                     │
│  boxctld          │
│  → Notifications    │
│  → Stall detection  │
└─────────────────────┘
          ↓
┌─────────────────────┐
│ Container           │
│                     │
│  Agent working      │
│  → Edits code       │
│  → Runs tests       │
│  → Notifies you     │
└─────────────────────┘
```

You control things from your phone. The agent works on your laptop. The daemon keeps you informed.

## Tips for Mobile

**Keep sessions named.** When you create sessions, give them meaningful names: `boxctl session new superclaude auth-refactor`. When you open the quick menu, you see `auth-refactor` instead of `superclaude-3`.

**Use the quick menu for navigation.** Even if you know the commands, the quick menu is faster on mobile. Less typing, fewer mistakes.

**Set up notifications.** If you're going to work remotely, configure `boxctld` first. Then you'll know when agents finish or get stuck.

**Detach, don't quit.** When checking on an agent, use `Ctrl+A, D` to detach. The session stays alive. If you accidentally close the terminal, the agent keeps working.

## What's Next

- **[Architecture](02-two-worlds.md)** - How the daemon enables notifications
- **[Configuration](08-configuration.md)** - Set up notification hooks
- **[CLI Reference](REF-A-cli.md)** - All quick menu options
