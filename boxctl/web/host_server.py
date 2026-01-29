# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""FastAPI server for boxctl web UI - HOST-SIDE VERSION.

This version runs on the host machine and uses docker exec to communicate
with tmux sessions inside containers. It provides a unified view of all
boxctl containers and their sessions.
"""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from boxctl.web.tmux_manager import (
    get_all_sessions,
    capture_session_output,
    send_keys_to_session,
    resize_session,
    get_session_dimensions,
    get_cursor_position,
)
from boxctl.web.pty_manager import get_pty_manager
from boxctl.core.sessions import create_agent_session as create_session
from boxctl.boxctld import (
    get_cached_buffer,
    send_input,
    get_tunnel_stats,
    get_connected_containers,
    get_session_metadata,
    get_usage_status,
)
from boxctl.host_config import get_config
from boxctl.container import ContainerManager
from boxctl.paths import ContainerDefaults

# Get workspace root from this file's location (boxctl/web/host_server.py)
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent

# Cache-busting timestamp - set once at server startup
CACHE_BUST_VERSION = str(int(time.time()))

# Map ANSI escape sequences to tmux key names
ANSI_TO_TMUX = {
    "\x1B": "Escape",
    "\t": "Tab",
    "\r": "Enter",
    "\n": "Enter",
    "\x1B[A": "Up",
    "\x1B[B": "Down",
    "\x1B[D": "Left",
    "\x1B[C": "Right",
    "\x7F": "BSpace",
    "\x1B[3~": "DC",  # Delete
    "\x1B[H": "Home",
    "\x1B[F": "End",
    "\x1B[5~": "PPage",  # Page Up
    "\x1B[6~": "NPage",  # Page Down
}


# Ctrl key mappings (Ctrl+A = \x01, etc.)
def parse_ctrl_key(char):
    """Convert Ctrl+key character to tmux format."""
    code = ord(char)
    if 1 <= code <= 26:
        # Ctrl+A through Ctrl+Z
        key_char = chr(code + 64)
        return f"C-{key_char.lower()}"
    return None


# Request models
class CreateSessionRequest(BaseModel):
    container: str
    agent_type: str
    identifier: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    pty_manager = get_pty_manager()
    await pty_manager.start_cleanup_task()
    logger.info("PTY session cleanup task started")
    yield
    # Shutdown
    await pty_manager.stop_cleanup_task()
    logger.info("PTY session cleanup task stopped")


# Create FastAPI app
app = FastAPI(title="boxctl Web UI (Host)", version="0.2.0", lifespan=lifespan)

# Add CORS middleware to allow API calls from same origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get static files directory
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def index():
    """Serve the session list page with cache-busting timestamp."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse(
            "<h1>boxctl Web UI</h1>"
            "<p>Session list page not yet implemented.</p>"
            '<p>API available at <a href="/api/sessions">/api/sessions</a></p>'
        )

    # Read HTML and inject cache-busting timestamp
    html_content = index_file.read_text()
    html_content = html_content.replace("CACHE_BUST", CACHE_BUST_VERSION)

    return HTMLResponse(content=html_content)


@app.get("/decisions")
async def decisions():
    """Serve the decisions/checklist page with cache-busting timestamp."""
    decisions_file = STATIC_DIR / "decisions.html"
    if not decisions_file.exists():
        return HTMLResponse("<h1>Decisions page not found</h1>")

    # Read HTML and inject cache-busting timestamp
    html_content = decisions_file.read_text()
    html_content = html_content.replace("CACHE_BUST", CACHE_BUST_VERSION)

    return HTMLResponse(content=html_content)


@app.get("/api/sessions")
async def get_sessions() -> Dict[str, List[Dict]]:
    """Get all tmux sessions across containers.

    Performance optimized: Uses asyncio to parallelize preview capture
    across all sessions (reduces N sequential docker exec calls to parallel).

    Returns:
        JSON with sessions list including previews
    """
    import concurrent.futures

    sessions = get_all_sessions()

    if not sessions:
        return {"sessions": []}

    # Capture previews in parallel using thread pool
    def capture_preview(session: Dict) -> tuple[Dict, str]:
        """Capture preview for a single session (runs in thread pool)."""
        container_name = session.get("container", "")
        session_name = session.get("name", "")
        try:
            preview_output = capture_session_output(container_name, session_name)
            if preview_output:
                lines = preview_output.strip().split("\n")
                preview_lines = lines[-5:] if len(lines) > 5 else lines
                return (session, "\n".join(preview_lines))
        except Exception:
            pass
        return (session, "")

    # Run all preview captures in parallel
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sessions), 10)) as executor:
        futures = [loop.run_in_executor(executor, capture_preview, s) for s in sessions]
        results = await asyncio.gather(*futures)

    # Apply previews to sessions
    for session, preview in results:
        session["preview"] = preview

    return {"sessions": sessions}


@app.get("/api/sessions/metadata")
async def get_sessions_metadata() -> Dict:
    """Get all sessions with full metadata from daemon cache.

    This is a fast endpoint that returns cached session metadata pushed
    by containers, avoiding docker exec calls. Use this for CLI tools.

    Returns:
        JSON with sessions list and source indicator
    """
    from boxctl import container_naming

    metadata = get_session_metadata(max_age=30.0)

    if metadata is None:
        return {"sessions": [], "source": "daemon", "stale": True}

    # Enrich with project info from container names
    sessions = []
    try:
        manager = ContainerManager()
        containers = {c["name"]: c for c in manager.list_containers(all_containers=False)}
    except Exception:
        containers = {}

    for container_name, sess_list in metadata.items():
        # Get project info
        container_info = containers.get(container_name, {})
        project = (
            container_info.get("project")
            or container_naming.extract_project_name(container_name)
            or ""
        )
        project_path = container_info.get("project_path", "")

        for sess in sess_list:
            sessions.append(
                {
                    "container_name": container_name,
                    "project": project,
                    "project_path": project_path,
                    "session_name": sess.get("name", ""),
                    "windows": sess.get("windows", 1),
                    "attached": sess.get("attached", False),
                    "agent_type": sess.get("agent_type"),
                    "identifier": sess.get("identifier"),
                }
            )

    return {"sessions": sessions, "source": "daemon"}


@app.post("/api/sessions", status_code=201)
async def create_new_session(request: CreateSessionRequest):
    """Create a new tmux session in a container.

    Args:
        request: CreateSessionRequest with container, agent_type, and optional identifier

    Returns:
        JSON with success status and session details
    """
    result = create_session(
        container_name=request.container,
        agent_type=request.agent_type,
        identifier=request.identifier,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


@app.get("/session/{container}/{session_name}")
async def terminal_page(container: str, session_name: str):
    """Serve the terminal page with cache-busting timestamp."""
    terminal_file = STATIC_DIR / "terminal.html"
    if not terminal_file.exists():
        return HTMLResponse(
            f"<h1>Terminal: {container} / {session_name}</h1>"
            "<p>Terminal page not yet implemented.</p>"
        )

    # Read HTML and inject cache-busting timestamp
    html_content = terminal_file.read_text()
    html_content = html_content.replace("CACHE_BUST", CACHE_BUST_VERSION)

    return HTMLResponse(content=html_content)


@app.websocket("/ws/{container}/{session_name}")
async def websocket_endpoint(websocket: WebSocket, container: str, session_name: str):
    """WebSocket endpoint for terminal I/O using direct PTY streaming.

    Uses tmux attach with full duplex socket for real-time streaming.
    Filters terminal capability responses to prevent feedback loops.
    Each connection gets a unique client_id for heartbeat tracking.
    """
    # Generate unique client ID for this connection
    client_id = str(uuid.uuid4())

    await websocket.accept()
    logger.info(f"WebSocket connected [{client_id}]: {container}/{session_name}")

    # Get PTY session with unique client_id
    pty_manager = get_pty_manager()
    pty_session = await pty_manager.get_or_create_session(container, session_name, client_id)
    if not pty_session:
        logger.warning(f"Failed to create PTY session for {client_id}: {container}/{session_name}")
        await websocket.close(code=1011, reason="Failed to create PTY session")
        return

    # Get and send tmux session dimensions
    width, height = get_session_dimensions(container, session_name)
    logger.debug(f"Session dimensions: {width}x{height}")
    await websocket.send_text(f"__INIT__{width}x{height}")

    # Callback to forward PTY output to WebSocket with filtering
    async def on_pty_output(data: bytes):
        try:
            text = data.decode("utf-8", errors="replace")
            # Filter terminal capability query responses to prevent feedback
            # Skip: CSI responses, OSC color queries
            if "\x1b[>" in text or "\x1b]10" in text or "\x1b]11" in text:
                return
            await websocket.send_text(text)
        except Exception as e:
            logger.error(f"Error sending to WebSocket: {e}")

    # DON'T register reader yet - wait for __READY__ to avoid duplicate output
    reader_registered = False

    try:
        while True:
            data = await websocket.receive_text()

            if data.startswith("__PING__"):
                # Heartbeat from client - update last activity time
                await pty_manager.update_heartbeat(client_id)

            elif data.startswith("__READY__"):
                logger.debug(f"Client ready [{client_id}]: {container}/{session_name}")

                # Wait for tmux to fully stabilize and reformat after resize
                # This ensures captured history is at the CORRECT dimensions
                await asyncio.sleep(0.5)

                # Capture pane history AFTER resize - content is now properly formatted
                # at the new dimensions. Write it to xterm.js so it flows into scrollback.
                initial_scrollback = capture_session_output(container, session_name)
                if initial_scrollback:
                    # Write history to xterm.js - it will naturally flow into scrollback
                    # as it scrolls off the visible screen
                    await websocket.send_text(initial_scrollback)
                    logger.debug(
                        f"Sent {len(initial_scrollback)} bytes of reformatted history [{client_id}]"
                    )

                # Register PTY reader for live streaming
                if not reader_registered:
                    pty_session.add_reader(on_pty_output)
                    reader_registered = True
                    logger.debug(f"PTY streaming started [{client_id}]: {container}/{session_name}")

            elif data.startswith("__RESIZE__"):
                try:
                    dims = data[10:]
                    w, h = dims.split("x")
                    logger.debug(
                        f"Resizing PTY [{client_id}] {container}/{session_name} to {w}x{h}"
                    )
                    await pty_session.resize(int(w), int(h))
                except (ValueError, IndexError) as e:
                    logger.warning(f"Resize error: {e}")
            else:
                # Write directly to PTY socket
                await pty_session.write(data)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected [{client_id}]: {container}/{session_name}")
    except Exception as e:
        logger.exception(f"WebSocket error [{client_id}]: {e}")
    finally:
        pty_session.remove_reader(on_pty_output)
        await pty_manager.remove_session(client_id)
        logger.debug(f"Cleaned up [{client_id}]: {container}/{session_name}")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# Debug logging for mobile keyboard troubleshooting
class DebugLog(BaseModel):
    message: str
    timestamp: str
    data: Optional[dict] = None


@app.post("/api/debug/mobile")
async def log_mobile_debug(log: DebugLog):
    """Receive debug logs from mobile browser."""
    logger.debug("[MOBILE DEBUG ENDPOINT HIT] Received log request")

    # Write to workspace .boxctl directory (shared with container)
    debug_file = WORKSPACE_ROOT / ".boxctl" / "mobile-debug.log"

    # Ensure directory exists
    debug_file.parent.mkdir(exist_ok=True, parents=True)

    log_entry = f"[{log.timestamp}] {log.message}"
    if log.data:
        log_entry += f" | Data: {log.data}"
    log_entry += "\n"

    # Append to debug file (keep last 100 lines)
    try:
        existing = ""
        if debug_file.exists():
            lines = debug_file.read_text().splitlines()
            existing = "\n".join(lines[-99:]) + "\n" if lines else ""

        debug_file.write_text(existing + log_entry)
        logger.debug(f"[MOBILE DEBUG] Wrote to {debug_file}: {log_entry.strip()}")
    except Exception as e:
        logger.exception(f"[MOBILE DEBUG ERROR] Failed to write: {e}")

    # Also log to logger
    logger.debug(f"[MOBILE DEBUG] {log_entry.strip()}")

    return {"status": "ok", "written": str(debug_file)}


@app.get("/api/debug/logs")
async def get_debug_logs():
    """Get recent debug logs via API (so agent can read them)."""
    debug_file = WORKSPACE_ROOT / ".boxctl" / "mobile-debug.log"
    try:
        if debug_file.exists():
            content = debug_file.read_text()
            lines = content.splitlines()[-50:]  # Last 50 lines
            return {"status": "ok", "logs": lines, "file": str(debug_file)}
        else:
            return {"status": "no_logs", "file": str(debug_file), "exists": False}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============================================================================
# Status Page and API
# ============================================================================


@app.get("/status")
async def status_page():
    """Serve the status/info page with cache-busting timestamp."""
    status_file = STATIC_DIR / "status.html"
    if not status_file.exists():
        return HTMLResponse("<h1>Status page not found</h1>")

    html_content = status_file.read_text()
    html_content = html_content.replace("CACHE_BUST", CACHE_BUST_VERSION)

    return HTMLResponse(content=html_content)


@app.get("/api/status")
async def get_status() -> Dict:
    """Get comprehensive system status.

    Returns status of:
    - Service (boxctld daemon)
    - Tunnels (both directions)
    - Containers
    """
    # Get tunnel stats
    tunnel_stats = get_tunnel_stats()

    # Get connected containers via SSH tunnel
    connected_containers = get_connected_containers()

    # Get containers
    try:
        manager = ContainerManager()
        containers = manager.list_containers(all_containers=True)
        # Add SSH tunnel connection status to each container
        for container in containers:
            container["tunnel_connected"] = container["name"] in connected_containers
    except Exception as e:
        logger.error(f"Failed to list containers: {e}")
        containers = []

    # Determine service status
    # If we can get tunnel stats, the service is running (we're part of it)
    service_status = "running"

    return {
        "service": {
            "status": service_status,
            "connected_containers": connected_containers,
        },
        "tunnels": tunnel_stats,
        "containers": containers,
    }


@app.get("/api/usage")
async def get_usage() -> Dict:
    """Get agent rate limit status.

    Returns status of all agents including:
    - available: Whether the agent can be used
    - limited: Whether the agent is currently rate-limited
    - resets_at: ISO timestamp when limit resets
    - resets_in_seconds: Seconds until limit resets
    - error_type: Type of rate limit error
    """
    status = get_usage_status()
    if status is None:
        return {"agents": {}, "note": "daemon not running or no data"}
    return {"agents": status}


@app.post("/api/service/restart")
async def restart_service():
    """Restart the boxctld service via systemctl."""
    import subprocess

    try:
        # Use systemctl --user to restart the service
        result = subprocess.run(
            ["systemctl", "--user", "restart", "boxctld.service"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {
                "ok": False,
                "error": result.stderr.strip() or "Failed to restart service",
            }

        return {"ok": True, "message": "Service restart initiated"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Restart command timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/container/{container_name}/restart")
async def restart_container(container_name: str):
    """Restart a container."""
    try:
        manager = ContainerManager()
        container = manager.client.containers.get(container_name)
        container.restart(timeout=30)
        return {"ok": True, "message": f"Container {container_name} restarted"}
    except Exception as e:
        logger.error(f"Failed to restart container {container_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/container/{container_name}/stop")
async def stop_container(container_name: str):
    """Stop a container."""
    try:
        manager = ContainerManager()
        container = manager.client.containers.get(container_name)
        container.stop(timeout=30)
        return {"ok": True, "message": f"Container {container_name} stopped"}
    except Exception as e:
        logger.error(f"Failed to stop container {container_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/container/{container_name}/start")
async def start_container(container_name: str):
    """Start a stopped container."""
    try:
        manager = ContainerManager()
        container = manager.client.containers.get(container_name)
        container.start()
        return {"ok": True, "message": f"Container {container_name} started"}
    except Exception as e:
        logger.error(f"Failed to start container {container_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/container/{container_name}/rebase")
async def rebase_container(container_name: str):
    """Rebase a container to the latest base image.

    This recreates the container from scratch, preserving the workspace mount.
    Warning: Running sessions will be terminated.
    """
    import subprocess
    from pathlib import Path

    try:
        manager = ContainerManager()

        # Get container info to find project path
        container = manager.client.containers.get(container_name)

        # Extract project name and path from container
        project_name = ContainerDefaults.project_from_container(container_name)

        # Find project path from mounts
        project_path = None
        mounts = container.attrs.get("Mounts", [])
        for mount in mounts:
            if mount.get("Destination") == "/workspace":
                project_path = mount.get("Source")
                break

        if not project_path:
            return {"ok": False, "error": "Could not determine project path"}

        # Run rebase via CLI command (handles all the complex logic)
        # Run in the project directory so abox picks it up
        result = subprocess.run(
            ["boxctl", "project", "rebase", "--yes"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for rebase
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip() or "Rebase failed"
            logger.error(f"Rebase failed for {container_name}: {error_msg}")
            return {"ok": False, "error": error_msg}

        return {"ok": True, "message": f"Container {container_name} rebased successfully"}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Rebase timed out after 5 minutes"}
    except Exception as e:
        logger.error(f"Failed to rebase container {container_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Mount static files AFTER all routes are defined
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import asyncio
    import uvicorn
    from datetime import datetime

    # Get defaults from host_config
    config = get_config()
    hosts = config.get_web_server_hosts()
    default_port = config.get("web_server", "port", default=8080)
    port = int(os.getenv("BOXCTL_WEB_PORT", str(default_port)))

    # Environment variable can override hosts (comma-separated)
    env_hosts = os.getenv("BOXCTL_WEB_HOST")
    if env_hosts:
        hosts = [h.strip() for h in env_hosts.split(",")]

    # Write startup log to debug file
    try:
        debug_file = WORKSPACE_ROOT / ".boxctl" / "mobile-debug.log"
        debug_file.parent.mkdir(exist_ok=True, parents=True)
        startup_msg = f"[{datetime.now().isoformat()}] ===== WEB SERVER STARTED =====\nWorkspace: {WORKSPACE_ROOT}\nCWD: {Path.cwd()}\nLog file: {debug_file.resolve()}\nHosts: {hosts}\nPort: {port}\n\n"
        debug_file.write_text(startup_msg)
        logger.info(f"Wrote startup log to {debug_file.resolve()}")
    except Exception as e:
        logger.error(f"Failed to write startup log: {e}")

    async def serve_all():
        servers = []
        for host in hosts:
            logger.info(f"Starting boxctl Web UI (Host) on {host}:{port}")
            server_config = uvicorn.Config(app, host=host, port=port, log_level="info")
            server = uvicorn.Server(server_config)
            servers.append(server.serve())
        await asyncio.gather(*servers)

    asyncio.run(serve_all())
