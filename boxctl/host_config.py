"""Centralized host-side configuration for boxctl."""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, List, Optional

import yaml
from pydantic import ValidationError

from boxctl.models.host_config import HostConfigModel
from boxctl.paths import HostPaths

logger = logging.getLogger(__name__)


def get_tailscale_ip() -> Optional[str]:
    """Get the Tailscale IPv4 address, if available.

    Returns:
        The Tailscale IPv4 address or None if Tailscale is not running/installed.
    """
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if result.returncode == 0:
            ip = result.stdout.strip().split("\n")[0]
            if ip:
                return ip
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


class HostConfig:
    """Manages host-side configuration from ~/.config/boxctl/config.yml."""

    def __init__(self):
        self.config_path = HostPaths.config_file()
        self._model: Optional[HostConfigModel] = None
        self._config = self._load()

    def _load(self) -> dict:
        """Load configuration from file."""
        if not self.config_path.exists():
            # Use model defaults
            self._model = HostConfigModel()
            return self._model.model_dump()

        try:
            with open(self.config_path) as f:
                raw_config = yaml.safe_load(f) or {}

            # Parse with Pydantic - it handles merging with defaults automatically
            try:
                self._model = HostConfigModel.model_validate(raw_config)
                return self._model.model_dump()
            except ValidationError as e:
                logger.warning(f"Config validation errors: {e}")
                # Fall back to defaults merged with raw config
                self._model = HostConfigModel()
                defaults = self._model.model_dump()
                return self._deep_merge(defaults, raw_config)

        except Exception as e:
            logger.warning(f"Failed to load config from {self.config_path}: {e}")
            self._model = HostConfigModel()
            return self._model.model_dump()

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Deep merge override into base."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @property
    def boxctl_dir(self) -> Path:
        """Get boxctl installation directory (auto-detected).

        Priority:
        1. BOXCTL_DIR environment variable
        2. Package installation location
        3. ~/.local/share/boxctl (fallback)
        """
        # Check config override
        if self._model:
            config_dir = self._model.paths.boxctl_dir
            if config_dir:
                return Path(config_dir)
        else:
            config_dir = self._config.get("paths", {}).get("boxctl_dir")
            if config_dir:
                return Path(config_dir)

        # 1. Environment variable (highest priority)
        env_dir = os.getenv("BOXCTL_DIR")
        if env_dir:
            return Path(env_dir)

        # 2. Package installation location
        try:
            import boxctl

            pkg_path = Path(boxctl.__file__).parent.parent
            if (pkg_path / "library").exists():
                return pkg_path
        except Exception:
            pass

        # 3. Fallback to standard location
        return HostPaths.data_dir()

    @property
    def socket_dir(self) -> Path:
        """Get boxctld socket directory (platform-aware: macOS vs Linux)."""
        return HostPaths.boxctld_dir()

    @property
    def socket_path(self) -> Path:
        """Get boxctld socket path."""
        return self.socket_dir / "boxctld.sock"

    @property
    def web_server_url(self) -> str:
        """Get web server URL."""
        if self._model:
            return f"http://{self._model.web_server.host}:{self._model.web_server.port}"
        cfg = self._config["web_server"]
        return f"http://{cfg['host']}:{cfg['port']}"

    def get_web_server_hosts(self) -> List[str]:
        """Get resolved list of hosts to bind the web server to.

        Resolves special values like "tailscale" to actual IPs.
        Falls back to single 'host' config if 'hosts' array not set.
        """
        if self._model:
            hosts = self._model.web_server.hosts
            if not hosts:
                return [self._model.web_server.host]
        else:
            cfg = self._config.get("web_server", {})
            hosts = cfg.get("hosts")
            if not hosts:
                return [cfg.get("host", "127.0.0.1")]

        resolved = []
        for host in hosts:
            if host.lower() == "tailscale":
                tailscale_ip = get_tailscale_ip()
                if tailscale_ip:
                    resolved.append(tailscale_ip)
                else:
                    logger.warning("'tailscale' specified but Tailscale IP not available")
            else:
                resolved.append(host)

        return resolved if resolved else ["127.0.0.1"]

    def has_tailscale_in_hosts(self) -> bool:
        """Check if 'tailscale' is configured in the hosts list."""
        if self._model:
            hosts = self._model.web_server.hosts
        else:
            cfg = self._config.get("web_server", {})
            hosts = cfg.get("hosts", [])
        return "tailscale" in [h.lower() for h in hosts]

    def has_tailscale_in_bind_addresses(self) -> bool:
        """Check if 'tailscale' is configured in the network bind_addresses."""
        if self._model:
            addresses = self._model.network.bind_addresses
        else:
            cfg = self._config.get("network", {})
            addresses = cfg.get("bind_addresses", ["127.0.0.1", "tailscale"])
        return "tailscale" in [a.lower() for a in addresses]

    def uses_tailscale(self) -> bool:
        """Check if 'tailscale' is configured anywhere (hosts or bind_addresses)."""
        return self.has_tailscale_in_hosts() or self.has_tailscale_in_bind_addresses()

    def get_port_bind_addresses(self) -> List[str]:
        """Get resolved list of addresses to bind port listeners to.

        Resolves special values like "tailscale" to actual IPs.
        Used for expose/forward port commands.
        """
        if self._model:
            addresses = self._model.network.bind_addresses
        else:
            cfg = self._config.get("network", {})
            addresses = cfg.get("bind_addresses", ["127.0.0.1", "tailscale"])

        resolved = []
        for addr in addresses:
            if addr.lower() == "tailscale":
                tailscale_ip = get_tailscale_ip()
                if tailscale_ip:
                    resolved.append(tailscale_ip)
                # Skip if not available (don't log warning - monitor will handle)
            else:
                resolved.append(addr)

        return resolved if resolved else ["127.0.0.1"]

    def get(self, *keys, default=None) -> Any:
        """Get nested config value.

        Example: config.get("timeouts", "container_wait")
        """
        # Try model first
        if self._model:
            value = self._model
            for key in keys:
                if hasattr(value, key):
                    value = getattr(value, key)
                elif isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return default
            # Convert Pydantic models to their values
            if hasattr(value, "model_dump"):
                return value.model_dump()
            return value

        # Fall back to dict access
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value


# Singleton instance
_config: Optional[HostConfig] = None


def get_config() -> HostConfig:
    """Get the global host configuration."""
    global _config
    if _config is None:
        _config = HostConfig()
    return _config
