# Home Assistant MCP Server

Provides Claude with access to Home Assistant for smart home control.

## What it does

- Control lights, switches, climate
- Query sensor states
- Trigger automations
- Create/modify entities
- Read history

## Connection to Host Services

Home Assistant runs on your host machine (or local network). The container can access it!

### Method 1: Host Docker Internal (Recommended)

If Home Assistant runs on your host:

```json
{
  "mcpServers": {
    "homeassistant": {
      "command": "npx",
      "args": ["-y", "@homeassistant/mcp"],
      "env": {
        "HA_URL": "http://host.docker.internal:8123",
        "HA_TOKEN": "your-long-lived-access-token"
      }
    }
  }
}
```

**`host.docker.internal`** is Docker's special hostname that points to your host machine!

### Method 2: Local Network IP

If Home Assistant is on your LAN:

```json
{
  "env": {
    "HA_URL": "http://192.168.1.100:8123",
    "HA_TOKEN": "your-token"
  }
}
```

### Method 3: Hostname

If you have local DNS or `/etc/hosts` entry:

```json
{
  "env": {
    "HA_URL": "http://homeassistant.local:8123",
    "HA_TOKEN": "your-token"
  }
}
```

## Get Access Token

1. Go to Home Assistant → Profile
2. Scroll to "Long-Lived Access Tokens"
3. Click "Create Token"
4. Copy the token

## Network Access from Container

The container can reach your host services via:
- `host.docker.internal` → Your host machine
- `192.168.x.x` → Devices on your LAN
- Container IPs → Other Docker containers

## Security

**⚠️ Important:** Access tokens grant full control!

Best practice:
1. Create `.agentbox/.env` (gitignored):
   ```bash
   HA_URL=http://host.docker.internal:8123
   HA_TOKEN=your-token-here
   ```

2. Reference in config:
   ```json
   {
     "env": {
       "HA_URL": "${HA_URL}",
       "HA_TOKEN": "${HA_TOKEN}"
     }
   }
   ```

## Example Usage

```bash
abox mcp add homeassistant
# Configure in .agentbox/config.json
# Claude can now control your smart home!
```

## Troubleshooting

**Can't connect?**
- Check Home Assistant is running: `curl http://host.docker.internal:8123`
- Verify token is valid
- Check firewall allows Docker → host connections
