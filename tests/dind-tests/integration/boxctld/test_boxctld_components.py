# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Integration tests for proxy daemon components."""

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from helpers.cli import run_abox
from helpers.docker import exec_in_container


@pytest.mark.integration
class TestProxyImports:
    """Test that proxy modules can be imported."""

    def test_proxy_module_imports(self, running_container, test_project):
        """Test that proxy module imports successfully."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name, "python3 -c 'from boxctl.boxctld import boxctld; print(\"OK\")'"
        )

        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_proxy_default_socket_path(self, running_container, test_project):
        """Test that default socket path is resolved."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "python3 -c 'from boxctl.boxctld import _default_socket_path; "
            'path = _default_socket_path(); print(f"PATH:{path}")\'',
        )

        assert result.returncode == 0
        assert "PATH:" in result.stdout
        assert ".sock" in result.stdout

    def test_proxy_config_integration(self, running_container, test_project):
        """Test that proxy uses host config."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))
config = proxy.config

print(f"CONFIG_OK:{config is not None}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "CONFIG_OK:True" in result.stdout


@pytest.mark.integration
class TestProxyHandlers:
    """Test proxy handler registration."""

    def test_handlers_registered(self, running_container, test_project):
        """Test that handlers are registered correctly."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Check handlers exist
notify_key = "notify"
clipboard_key = "clipboard"
print(f"NOTIFY:{(notify_key in proxy.handlers)}")
print(f"CLIPBOARD:{(clipboard_key in proxy.handlers)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "NOTIFY:True" in result.stdout
        assert "CLIPBOARD:True" in result.stdout

    def test_handler_callable(self, running_container, test_project):
        """Test that handlers are callable."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Check handlers are callable
notify_handler = proxy.handlers.get("notify")
print(f"CALLABLE:{callable(notify_handler)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "CALLABLE:True" in result.stdout


@pytest.mark.integration
class TestProxyBufferManagement:
    """Test proxy buffer management (thread-safe)."""

    def test_session_buffer_initialization(self, running_container, test_project):
        """Test session buffer data structure."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Check buffer structure
print(f"BUFFERS_TYPE:{type(proxy.session_buffers).__name__}")
print(f"BUFFERS_EMPTY:{len(proxy.session_buffers) == 0}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "BUFFERS_TYPE:dict" in result.stdout
        assert "BUFFERS_EMPTY:True" in result.stdout

    def test_get_session_buffer_empty(self, running_container, test_project):
        """Test getting buffer for non-existent session."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Get buffer for non-existent session
buffer = proxy.get_session_buffer("container-1", "session-1")
print(f"BUFFER:{buffer}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "BUFFER:None" in result.stdout

    def test_stream_lock_exists(self, running_container, test_project):
        """Test that stream lock is initialized."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path
import threading

proxy = boxctld(Path("/tmp/test.sock"))

# Check lock exists and is correct type
lock_type = type(proxy.stream_lock).__name__
expected_type = type(threading.Lock()).__name__
print(f"LOCK_TYPE:{lock_type}")
print(f"IS_LOCK:{lock_type == expected_type}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        # Lock type can be 'lock' or '_thread.lock' depending on Python version
        assert "LOCK_TYPE:lock" in result.stdout or "LOCK_TYPE:_thread.lock" in result.stdout
        assert "IS_LOCK:True" in result.stdout


@pytest.mark.integration
class TestProxyRequestHandling:
    """Test proxy request parsing and handling."""

    def test_handle_request_valid_json(self, running_container, test_project):
        """Test handling valid JSON request."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path
import json

proxy = boxctld(Path("/tmp/test.sock"))

# Create a notify request (will fail but test parsing)
payload = {"action": "notify", "title": "Test", "message": "Message"}
raw = json.dumps(payload).encode("utf-8")

result = proxy._handle_request(raw)
ok_key = "ok"
print(f"RESULT_TYPE:{type(result).__name__}")
print(f"HAS_OK:{(ok_key in result)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "RESULT_TYPE:dict" in result.stdout
        assert "HAS_OK:True" in result.stdout

    def test_handle_request_invalid_json(self, running_container, test_project):
        """Test handling invalid JSON."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Send invalid JSON
result = proxy._handle_request(b"invalid json{{{")
ok_key = "ok"
error_key = "error"
print(f"OK:{result.get(ok_key)}")
print(f"ERROR:{result.get(error_key)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "OK:False" in result.stdout
        assert "ERROR:invalid_json" in result.stdout

    def test_handle_request_unknown_action(self, running_container, test_project):
        """Test handling unknown action."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path
import json

proxy = boxctld(Path("/tmp/test.sock"))

# Send unknown action
payload = {"action": "unknown_action"}
raw = json.dumps(payload).encode("utf-8")

result = proxy._handle_request(raw)
ok_key = "ok"
error_key = "error"
print(f"OK:{result.get(ok_key)}")
print(f"ERROR:{result.get(error_key)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "OK:False" in result.stdout
        assert "ERROR:unknown_action" in result.stdout


@pytest.mark.integration
class TestProxyStreamMessages:
    """Test proxy stream message handling."""

    def test_stream_register_message(self, running_container, test_project):
        """Test stream register message handling."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Simulate stream register - call SSH handler directly
container = "boxctl-test"
payload = {
    "session": "test-session"
}

proxy._ssh_handle_stream_register(container, payload)

# Check container was registered
print(f"REGISTERED:{(container in proxy.session_buffers)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "REGISTERED:True" in result.stdout

    def test_stream_data_message(self, running_container, test_project):
        """Test stream data message handling."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

container = "boxctl-test"

# Register first - call SSH handler directly
proxy._ssh_handle_stream_register(container, {
    "session": "test-session"
})

# Send data - call SSH handler directly
proxy._ssh_handle_stream_data(container, {
    "session": "test-session",
    "data": "test buffer content",
    "cursor_x": 10,
    "cursor_y": 5
})

# Retrieve buffer
buffer = proxy.get_session_buffer(container, "test-session")
print(f"BUFFER:{buffer}")

# Get cursor
cursor = proxy.get_session_cursor(container, "test-session")
print(f"CURSOR_X:{cursor[0]}")
print(f"CURSOR_Y:{cursor[1]}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "BUFFER:test buffer content" in result.stdout
        assert "CURSOR_X:10" in result.stdout
        assert "CURSOR_Y:5" in result.stdout

    def test_stream_unregister_message(self, running_container, test_project):
        """Test stream unregister message handling."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

container = "boxctl-test"

# Register - call SSH handler directly
proxy._ssh_handle_stream_register(container, {
    "session": "test-session"
})

# Add data - call SSH handler directly
proxy._ssh_handle_stream_data(container, {
    "session": "test-session",
    "data": "test data"
})

# Unregister - call SSH handler directly
proxy._ssh_handle_stream_unregister(container, {
    "session": "test-session"
})

# Buffer should be gone
buffer = proxy.get_session_buffer(container, "test-session")
print(f"BUFFER_AFTER_UNREGISTER:{buffer}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "BUFFER_AFTER_UNREGISTER:None" in result.stdout


@pytest.mark.integration
class TestProxySubscribers:
    """Test proxy stream subscriber mechanism."""

    def test_subscribe_to_stream(self, running_container, test_project):
        """Test subscribing to stream updates."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Create callback
callback_called = []
def callback(data):
    callback_called.append(data)

# Subscribe
proxy.subscribe_to_stream("boxctl-test", "test-session", callback)

# Check subscriber was added
key = ("boxctl-test", "test-session")
has_subscriber = key in proxy.stream_subscribers
num_subscribers = len(proxy.stream_subscribers.get(key, []))

print(f"HAS_SUBSCRIBER:{has_subscriber}")
print(f"NUM_SUBSCRIBERS:{num_subscribers}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "HAS_SUBSCRIBER:True" in result.stdout
        assert "NUM_SUBSCRIBERS:1" in result.stdout

    def test_unsubscribe_from_stream(self, running_container, test_project):
        """Test unsubscribing from stream updates."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Create and subscribe callback
def callback(data):
    pass

proxy.subscribe_to_stream("boxctl-test", "test-session", callback)

# Unsubscribe
proxy.unsubscribe_from_stream("boxctl-test", "test-session", callback)

# Check subscriber was removed
key = ("boxctl-test", "test-session")
has_subscriber = key in proxy.stream_subscribers

print(f"HAS_SUBSCRIBER_AFTER_UNSUB:{has_subscriber}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "HAS_SUBSCRIBER_AFTER_UNSUB:False" in result.stdout


@pytest.mark.integration
class TestProxyStallDetection:
    """Test proxy stall detection components."""

    def test_session_activity_initialization(self, running_container, test_project):
        """Test session activity tracking structure."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Check activity tracking structure
print(f"ACTIVITY_TYPE:{type(proxy.session_activity).__name__}")
print(f"ACTIVITY_EMPTY:{len(proxy.session_activity) == 0}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "ACTIVITY_TYPE:dict" in result.stdout
        assert "ACTIVITY_EMPTY:True" in result.stdout

    def test_stall_monitor_thread_state(self, running_container, test_project):
        """Test stall monitor thread initialization."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Check thread state
print(f"MONITOR_RUNNING:{proxy.stall_monitor_running}")
print(f"MONITOR_THREAD:{proxy.stall_monitor_thread}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "MONITOR_RUNNING:False" in result.stdout
        assert "MONITOR_THREAD:None" in result.stdout


@pytest.mark.integration
class TestProxyDaemonConnections:
    """Test proxy daemon connection management."""

    def test_daemon_connections_initialization(self, running_container, test_project):
        """Test daemon connections structure."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Check daemon connections structure
print(f"CONNECTIONS_TYPE:{type(proxy.daemon_connections).__name__}")
print(f"CONNECTIONS_EMPTY:{len(proxy.daemon_connections) == 0}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "CONNECTIONS_TYPE:dict" in result.stdout
        assert "CONNECTIONS_EMPTY:True" in result.stdout

    def test_daemon_lock_exists(self, running_container, test_project):
        """Test that daemon lock is initialized."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path
import threading

proxy = boxctld(Path("/tmp/test.sock"))

# Check lock
lock_type = type(proxy.daemon_lock).__name__
expected_type = type(threading.Lock()).__name__
print(f"LOCK_TYPE:{lock_type}")
print(f"IS_LOCK:{lock_type == expected_type}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        # Lock type can be 'lock' or '_thread.lock' depending on Python version
        assert "LOCK_TYPE:lock" in result.stdout or "LOCK_TYPE:_thread.lock" in result.stdout
        assert "IS_LOCK:True" in result.stdout


@pytest.mark.integration
class TestProxyGlobalFunctions:
    """Test proxy global accessor functions."""

    def test_get_cached_buffer_no_instance(self, running_container, test_project):
        """Test get_cached_buffer when no proxy instance."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "python3 -c 'from boxctl.boxctld import get_cached_buffer; "
            'result = get_cached_buffer("test", "test"); print(f"RESULT:{result}")\'',
        )

        assert result.returncode == 0
        assert "RESULT:None" in result.stdout

    def test_get_cached_cursor_no_instance(self, running_container, test_project):
        """Test get_cached_cursor when no proxy instance."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "python3 -c 'from boxctl.boxctld import get_cached_cursor; "
            'result = get_cached_cursor("test", "test"); print(f"RESULT:{result}")\'',
        )

        assert result.returncode == 0
        assert "RESULT:(0, 0, 0, 0)" in result.stdout

    def test_send_input_no_instance(self, running_container, test_project):
        """Test send_input when no proxy instance."""
        container_name = f"boxctl-{test_project.name}"

        result = exec_in_container(
            container_name,
            "python3 -c 'from boxctl.boxctld import send_input; "
            'result = send_input("test", "test", "keys"); print(f"RESULT:{result}")\'',
        )

        assert result.returncode == 0
        assert "RESULT:False" in result.stdout


@pytest.mark.integration
@pytest.mark.skip(reason="Method _load_task_agent_config does not exist in boxctld")
class TestProxyConfiguration:
    """Test proxy configuration loading."""

    def test_load_task_agent_config_defaults(self, running_container, test_project):
        """Test loading default task agent config."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Try to load config (will use defaults since .boxctl.yml doesn't exist)
config = proxy._load_task_agent_config("boxctl-test")

enabled_key = "enabled"
agent_key = "agent"
timeout_key = "timeout"
print(f"HAS_ENABLED:{(enabled_key in config)}")
print(f"HAS_AGENT:{(agent_key in config)}")
print(f"HAS_TIMEOUT:{(timeout_key in config)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "HAS_ENABLED:True" in result.stdout
        assert "HAS_AGENT:True" in result.stdout
        assert "HAS_TIMEOUT:True" in result.stdout


@pytest.mark.integration
class TestProxyIntegration:
    """Integration tests for proxy components."""

    def test_complete_stream_workflow(self, running_container, test_project):
        """Test complete stream registration and data workflow."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

container = "boxctl-test"

# 1. Register stream - call SSH handler directly
proxy._ssh_handle_stream_register(container, {
    "session": "integration-session"
})

# 2. Send multiple data updates - call SSH handler directly
for i in range(3):
    proxy._ssh_handle_stream_data(container, {
        "session": "integration-session",
        "data": f"update {i}",
        "cursor_x": i * 10,
        "cursor_y": i
    })

# 3. Get final buffer
buffer = proxy.get_session_buffer(container, "integration-session")
cursor = proxy.get_session_cursor(container, "integration-session")

print(f"FINAL_BUFFER:{buffer}")
print(f"FINAL_CURSOR_X:{cursor[0]}")

# 4. Unregister - call SSH handler directly
proxy._ssh_handle_stream_unregister(container, {
    "session": "integration-session"
})

# 5. Verify cleanup
buffer_after = proxy.get_session_buffer(container, "integration-session")
print(f"AFTER_CLEANUP:{buffer_after}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "FINAL_BUFFER:update 2" in result.stdout
        assert "FINAL_CURSOR_X:20" in result.stdout
        assert "AFTER_CLEANUP:None" in result.stdout

    def test_thread_safe_buffer_access(self, running_container, test_project):
        """Test thread-safe buffer access."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path
import threading

proxy = boxctld(Path("/tmp/test.sock"))

container = "boxctl-test"

# Register stream - call SSH handler directly
proxy._ssh_handle_stream_register(container, {
    "session": "threaded-session"
})

# Multiple threads updating buffer - call SSH handler directly
def update_buffer(idx):
    for i in range(5):
        proxy._ssh_handle_stream_data(container, {
            "session": "threaded-session",
            "data": f"thread-{idx}-update-{i}"
        })

threads = []
for i in range(3):
    t = threading.Thread(target=update_buffer, args=(i,))
    t.start()
    threads.append(t)

for t in threads:
    t.join()

# Verify no crashes and buffer exists
buffer = proxy.get_session_buffer(container, "threaded-session")
print(f"THREAD_SAFE_OK:{buffer is not None}")
print(f"BUFFER_HAS_CONTENT:{len(buffer) > 0 if buffer else False}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0
        assert "THREAD_SAFE_OK:True" in result.stdout
        assert "BUFFER_HAS_CONTENT:True" in result.stdout


@pytest.mark.integration
class TestProxyCompletions:
    """Test proxy completion handler for CLI tab-completion."""

    def test_completions_handler_registered(self, running_container, test_project):
        """Test that get_completions handler is registered."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Check handler exists
handler_key = "get_completions"
print(f"HAS_COMPLETIONS:{(handler_key in proxy.handlers)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "HAS_COMPLETIONS:True" in result.stdout
        ), f"Expected get_completions handler to be registered. Output: {result.stdout}"

    def test_completions_projects_empty(self, running_container, test_project):
        """Test projects completion with no connected containers."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Request projects completion (fresh proxy has no connections)
result = proxy._handle_get_completions({"type": "projects"})
ok_key = "ok"
projects_key = "projects"
print(f"OK:{result.get(ok_key)}")
print(f"PROJECTS:{result.get(projects_key)}")
print(f"IS_LIST:{isinstance(result.get(projects_key), list)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert (
            "IS_LIST:True" in result.stdout
        ), f"Expected projects to be a list. Output: {result.stdout}"

    def test_completions_projects_with_simulated_connections(self, running_container, test_project):
        """Test projects completion with simulated connected containers.

        Note: This test simulates state within a single script execution
        to avoid issues with state persistence across exec calls.
        """
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Simulate connected containers (isolated within this script)
proxy.daemon_connections["boxctl-project1"] = None
proxy.daemon_connections["boxctl-project2"] = None

try:
    result = proxy._handle_get_completions({"type": "projects"})
    ok_key = "ok"
    projects_key = "projects"
    print(f"OK:{result.get(ok_key)}")
    projects = result.get(projects_key, [])
    print(f"COUNT:{len(projects)}")
    proj1 = "project1"
    proj2 = "project2"
    print(f"HAS_PROJECT1:{proj1 in projects}")
    print(f"HAS_PROJECT2:{proj2 in projects}")
finally:
    # Cleanup within the same execution context
    proxy.daemon_connections.clear()
    print(f"CLEANUP_OK:{len(proxy.daemon_connections) == 0}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert "COUNT:2" in result.stdout, f"Expected 2 projects. Output: {result.stdout}"
        assert (
            "HAS_PROJECT1:True" in result.stdout
        ), f"Expected project1 in results. Output: {result.stdout}"
        assert (
            "HAS_PROJECT2:True" in result.stdout
        ), f"Expected project2 in results. Output: {result.stdout}"
        assert (
            "CLEANUP_OK:True" in result.stdout
        ), f"Cleanup verification failed. Output: {result.stdout}"

    def test_completions_sessions_empty(self, running_container, test_project):
        """Test sessions completion with no sessions."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

result = proxy._handle_get_completions({"type": "sessions"})
ok_key = "ok"
sessions_key = "sessions"
print(f"OK:{result.get(ok_key)}")
print(f"IS_LIST:{isinstance(result.get(sessions_key), list)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert (
            "IS_LIST:True" in result.stdout
        ), f"Expected sessions to be a list. Output: {result.stdout}"

    def test_completions_sessions_with_simulated_data(self, running_container, test_project):
        """Test sessions completion with simulated session data."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Simulate session buffers (isolated within this script)
proxy.session_buffers["boxctl-myproject"] = {
    "session1": {"buffer": "data"},
    "session2": {"buffer": "data"}
}

try:
    # Request all sessions
    ok_key = "ok"
    sessions_key = "sessions"
    result = proxy._handle_get_completions({"type": "sessions"})
    print(f"OK:{result.get(ok_key)}")
    sessions = result.get(sessions_key, [])
    print(f"COUNT:{len(sessions)}")

    # Request sessions for specific project
    result2 = proxy._handle_get_completions({"type": "sessions", "project": "myproject"})
    sessions2 = result2.get(sessions_key, [])
    print(f"PROJECT_COUNT:{len(sessions2)}")
    sess1 = "session1"
    print(f"HAS_SESSION1:{sess1 in sessions2}")
finally:
    # Cleanup
    proxy.session_buffers.clear()
    print(f"CLEANUP_OK:{len(proxy.session_buffers) == 0}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert "COUNT:2" in result.stdout, f"Expected 2 sessions total. Output: {result.stdout}"
        assert (
            "PROJECT_COUNT:2" in result.stdout
        ), f"Expected 2 sessions for project. Output: {result.stdout}"
        assert (
            "CLEANUP_OK:True" in result.stdout
        ), f"Cleanup verification failed. Output: {result.stdout}"

    def test_completions_worktrees_empty(self, running_container, test_project):
        """Test worktrees completion with no worktrees."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

result = proxy._handle_get_completions({"type": "worktrees"})
ok_key = "ok"
worktrees_key = "worktrees"
print(f"OK:{result.get(ok_key)}")
print(f"IS_LIST:{isinstance(result.get(worktrees_key), list)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert (
            "IS_LIST:True" in result.stdout
        ), f"Expected worktrees to be a list. Output: {result.stdout}"

    def test_completions_worktrees_with_simulated_data(self, running_container, test_project):
        """Test worktrees completion with simulated worktree data."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

# Simulate container state with worktrees (isolated within this script)
proxy.container_state["boxctl-myproject"] = {
    "worktrees": ["feature-1", "bugfix-2"]
}

try:
    ok_key = "ok"
    worktrees_key = "worktrees"
    feature_name = "feature-1"
    result = proxy._handle_get_completions({"type": "worktrees"})
    print(f"OK:{result.get(ok_key)}")
    worktrees = result.get(worktrees_key, [])
    print(f"COUNT:{len(worktrees)}")
    print(f"HAS_FEATURE:{feature_name in worktrees}")

    # Request for specific project
    result2 = proxy._handle_get_completions({"type": "worktrees", "project": "myproject"})
    worktrees2 = result2.get(worktrees_key, [])
    print(f"PROJECT_COUNT:{len(worktrees2)}")
finally:
    # Cleanup
    proxy.container_state.clear()
    print(f"CLEANUP_OK:{len(proxy.container_state) == 0}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert "COUNT:2" in result.stdout, f"Expected 2 worktrees. Output: {result.stdout}"
        assert (
            "HAS_FEATURE:True" in result.stdout
        ), f"Expected feature-1 in worktrees. Output: {result.stdout}"
        assert (
            "CLEANUP_OK:True" in result.stdout
        ), f"Cleanup verification failed. Output: {result.stdout}"

    def test_completions_mcp_servers(self, running_container, test_project):
        """Test MCP servers completion returns list from library."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

result = proxy._handle_get_completions({"type": "mcp"})
mcp_key = "mcp_servers"
fetch_name = "fetch"
ok_key = "ok"
print(f"OK:{result.get(ok_key)}")
print(f"HAS_MCP_SERVERS:{mcp_key in result}")
print(f"IS_LIST:{isinstance(result.get(mcp_key), list)}")
# MCP servers come from the library, verify we got some common ones
mcp_servers = result.get(mcp_key, [])
print(f"HAS_FETCH:{fetch_name in mcp_servers}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert (
            "HAS_MCP_SERVERS:True" in result.stdout
        ), f"Expected mcp_servers key in result. Output: {result.stdout}"
        assert (
            "IS_LIST:True" in result.stdout
        ), f"Expected mcp_servers to be a list. Output: {result.stdout}"
        # Verify at least one well-known MCP server is available
        assert (
            "HAS_FETCH:True" in result.stdout
        ), f"Expected 'fetch' MCP server to be in library. Output: {result.stdout}"

    def test_completions_skills(self, running_container, test_project):
        """Test skills completion returns list from library."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

result = proxy._handle_get_completions({"type": "skills"})
ok_key = "ok"
skills_key = "skills"
print(f"OK:{result.get(ok_key)}")
print(f"HAS_SKILLS:{skills_key in result}")
print(f"IS_LIST:{isinstance(result.get(skills_key), list)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert (
            "HAS_SKILLS:True" in result.stdout
        ), f"Expected skills key in result. Output: {result.stdout}"
        assert (
            "IS_LIST:True" in result.stdout
        ), f"Expected skills to be a list. Output: {result.stdout}"

    def test_completions_docker_containers_returns_real_containers(
        self, running_container, test_project
    ):
        """Test docker containers completion returns actual running containers."""
        container_name = f"boxctl-{test_project.name}"

        script = f"""
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

dc_key = "docker_containers"
ok_key = "ok"
target_container = "{container_name}"

result = proxy._handle_get_completions({{"type": dc_key}})
print(f"OK:{{result.get(ok_key)}}")
print(f"HAS_CONTAINERS:{{dc_key in result}}")
print(f"IS_LIST:{{isinstance(result.get(dc_key), list)}}")

# Verify our own container is in the list
containers = result.get(dc_key, [])
# The current container should be running
print(f"HAS_CURRENT_CONTAINER:{{target_container in containers}}")
print(f"CONTAINER_COUNT:{{len(containers)}}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected completions to succeed. Output: {result.stdout}"
        assert (
            "IS_LIST:True" in result.stdout
        ), f"Expected docker_containers to be a list. Output: {result.stdout}"
        # We should see at least ourselves
        assert (
            "HAS_CURRENT_CONTAINER:True" in result.stdout
        ), f"Expected current container {container_name} to be in list. Output: {result.stdout}"

    def test_completions_unknown_type(self, running_container, test_project):
        """Test completion request with unknown type returns error."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

result = proxy._handle_get_completions({"type": "unknown_type_xyz"})
ok_key = "ok"
error_key = "error"
print(f"OK:{result.get(ok_key)}")
print(f"HAS_ERROR:{error_key in result}")
print(f"ERROR:{result.get(error_key, "")}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:False" in result.stdout
        ), f"Expected completion to fail for unknown type. Output: {result.stdout}"
        assert (
            "HAS_ERROR:True" in result.stdout
        ), f"Expected error in result. Output: {result.stdout}"
        assert (
            "unknown" in result.stdout.lower()
        ), f"Expected 'unknown' in error message. Output: {result.stdout}"

    def test_completions_missing_type(self, running_container, test_project):
        """Test completion request with missing type returns error."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

result = proxy._handle_get_completions({})
ok_key = "ok"
error_key = "error"
print(f"OK:{result.get(ok_key)}")
print(f"HAS_ERROR:{error_key in result}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:False" in result.stdout
        ), f"Expected completion to fail when type is missing. Output: {result.stdout}"
        assert (
            "HAS_ERROR:True" in result.stdout
        ), f"Expected error in result. Output: {result.stdout}"


@pytest.mark.integration
class TestProxyCompletionsIntegration:
    """Integration tests for completion workflows."""

    def test_completions_via_request_handler(self, running_container, test_project):
        """Test completions through the main request handler."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path
import json

proxy = boxctld(Path("/tmp/test.sock"))

# Build raw request like the socket would receive
payload = {"action": "get_completions", "type": "projects"}
raw = json.dumps(payload).encode("utf-8")

result = proxy._handle_request(raw)
ok_key = "ok"
projects_key = "projects"
print(f"OK:{result.get(ok_key)}")
print(f"HAS_PROJECTS:{projects_key in result}")
print(f"IS_LIST:{isinstance(result.get(projects_key), list)}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "OK:True" in result.stdout, f"Expected request to succeed. Output: {result.stdout}"
        assert (
            "HAS_PROJECTS:True" in result.stdout
        ), f"Expected projects key in result. Output: {result.stdout}"
        assert (
            "IS_LIST:True" in result.stdout
        ), f"Expected projects to be a list. Output: {result.stdout}"

    def test_completions_thread_safety(self, running_container, test_project):
        """Test that completion requests are thread-safe."""
        container_name = f"boxctl-{test_project.name}"

        script = """
from boxctl.boxctld import boxctld
from pathlib import Path
import threading

proxy = boxctld(Path("/tmp/test.sock"))

# Add some test data (isolated in this script)
proxy.daemon_connections["boxctl-test1"] = None
proxy.daemon_connections["boxctl-test2"] = None

results = []
errors = []
lock = threading.Lock()

def request_completions(comp_type):
    try:
        result = proxy._handle_get_completions({"type": comp_type})
        with lock:
            results.append(result.get('ok', False))
    except Exception as e:
        with lock:
            errors.append(str(e))

# Run multiple completion requests in parallel
threads = []
for _ in range(5):
    for comp_type in ["projects", "sessions", "worktrees"]:
        t = threading.Thread(target=request_completions, args=(comp_type,))
        t.start()
        threads.append(t)

for t in threads:
    t.join()

# Cleanup
proxy.daemon_connections.clear()

print(f"TOTAL_REQUESTS:{len(results)}")
print(f"ALL_OK:{all(results)}")
print(f"NO_ERRORS:{len(errors) == 0}")
if errors:
    print(f"ERRORS:{errors}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "TOTAL_REQUESTS:15" in result.stdout
        ), f"Expected 15 total requests (5 iterations * 3 types). Output: {result.stdout}"
        assert (
            "ALL_OK:True" in result.stdout
        ), f"Expected all requests to succeed. Output: {result.stdout}"
        assert (
            "NO_ERRORS:True" in result.stdout
        ), f"Expected no errors during concurrent access. Output: {result.stdout}"

    def test_completions_docker_containers_real_world(self, running_container, test_project):
        """Test docker_containers completion in a real scenario."""
        container_name = f"boxctl-{test_project.name}"

        script = f"""
from boxctl.boxctld import boxctld
from pathlib import Path

proxy = boxctld(Path("/tmp/test.sock"))

dc_key = "docker_containers"
ok_key = "ok"
error_key = "error"
target_container = "{container_name}"
prefix = "boxctl-"

# This should return actual Docker containers
result = proxy._handle_get_completions({{"type": dc_key}})

if result.get(ok_key):
    containers = result.get(dc_key, [])
    # In DinD environment, we should have at least our test container
    print(f"OK:True")
    print(f"CONTAINER_COUNT:{{len(containers)}}")
    # Check if our container name pattern is present
    agentbox_containers = [c for c in containers if c.startswith(prefix)]
    print(f"BOXCTL_CONTAINERS:{{len(agentbox_containers)}}")
    print(f"CURRENT_CONTAINER_FOUND:{{target_container in containers}}")
else:
    print(f"OK:False")
    print(f"ERROR:{{result.get(error_key)}}")
"""

        result = exec_in_container(container_name, f"python3 -c '{script}'")

        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert (
            "OK:True" in result.stdout
        ), f"Expected docker_containers completion to succeed. Output: {result.stdout}"
        # In DinD we should see at least the current container
        assert (
            "CURRENT_CONTAINER_FOUND:True" in result.stdout
        ), f"Expected to find current container in list. Output: {result.stdout}"
