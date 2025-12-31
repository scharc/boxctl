#!/usr/bin/env python3
# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Agentbox notify MCP server."""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
from typing import Any, Dict, Optional, Tuple


SOCKET_PATH = "/home/abox/.agentbox/notify.sock"
SERVER_NAME = "agentbox-notify"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"


class MessageIO:
    def __init__(self) -> None:
        self._use_content_length: Optional[bool] = None

    def read(self) -> Optional[Dict[str, Any]]:
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None

            if line.startswith(b"Content-Length:"):
                self._use_content_length = True
                try:
                    length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    return None

                while True:
                    header = sys.stdin.buffer.readline()
                    if not header or header in (b"\r\n", b"\n"):
                        break

                body = sys.stdin.buffer.read(length)
                if not body:
                    return None
                return self._parse_json(body)

            stripped = line.strip()
            if not stripped:
                continue

            if self._use_content_length is None:
                self._use_content_length = False
            return self._parse_json(stripped)

    def write(self, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if self._use_content_length:
            header = f"Content-Length: {len(raw)}\r\n\r\n".encode("utf-8")
            sys.stdout.buffer.write(header + raw)
        else:
            sys.stdout.buffer.write(raw + b"\n")
        sys.stdout.buffer.flush()

    @staticmethod
    def _parse_json(raw: bytes) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        if isinstance(data, dict):
            return data
        return None


def _notify_socket_available(path: str) -> Tuple[bool, Optional[str]]:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False, "notify_socket_missing"
    except Exception:
        return False, "notify_socket_unavailable"
    if not stat.S_ISSOCK(st.st_mode):
        return False, "notify_socket_invalid"
    return True, None


def _send_notification(title: str, message: str, urgency: str) -> Tuple[bool, Optional[str]]:
    available, error = _notify_socket_available(SOCKET_PATH)
    if not available:
        return False, error

    payload = json.dumps(
        {
            "action": "notify",
            "title": title,
            "message": message,
            "urgency": urgency,
        }
    ).encode("utf-8")

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(SOCKET_PATH)
            sock.sendall(payload + b"\n")
            sock.shutdown(socket.SHUT_WR)
            response = sock.recv(4096).decode("utf-8")
    except Exception:
        return False, "notify_send_failed"

    try:
        response_data = json.loads(response.strip().splitlines()[-1])
    except Exception:
        response_data = None

    if isinstance(response_data, dict) and response_data.get("ok") is True:
        return True, None

    if isinstance(response_data, dict) and response_data.get("error"):
        return False, str(response_data.get("error"))
    return False, "notify_failed"


def _tool_spec() -> Dict[str, Any]:
    return {
        "name": "notify",
        "description": "Send a host notification via the Agentbox notify socket.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "message": {"type": "string"},
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "critical"],
                },
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    }


def _success_response(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    protocol = params.get("protocolVersion") if isinstance(params, dict) else None
    return {
        "protocolVersion": protocol or DEFAULT_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def _handle_tools_list() -> Dict[str, Any]:
    return {"tools": [_tool_spec()]}


def _handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(params, dict):
        return {"content": [{"type": "text", "text": "Invalid parameters"}], "isError": True}

    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name != "notify":
        return {"content": [{"type": "text", "text": "Unknown tool"}], "isError": True}

    if not isinstance(arguments, dict):
        return {"content": [{"type": "text", "text": "Invalid tool arguments"}], "isError": True}

    title = str(arguments.get("title", "Agentbox"))
    message = arguments.get("message")
    urgency = str(arguments.get("urgency", "normal"))
    if urgency == "high":
        urgency = "critical"

    if not message:
        return {"content": [{"type": "text", "text": "Missing message"}], "isError": True}

    ok, error = _send_notification(title, str(message), urgency)
    if not ok:
        text = f"Notification failed: {error or 'unknown_error'}"
        return {"content": [{"type": "text", "text": text}], "isError": True}

    return {"content": [{"type": "text", "text": "Notification sent"}]}


def main() -> None:
    io = MessageIO()

    while True:
        request = io.read()
        if request is None:
            break

        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params")

        if method == "initialize":
            result = _handle_initialize(params if isinstance(params, dict) else {})
            io.write(_success_response(request_id, result))
            continue

        if method == "tools/list":
            io.write(_success_response(request_id, _handle_tools_list()))
            continue

        if method == "tools/call":
            io.write(_success_response(request_id, _handle_tools_call(params)))
            continue

        if request_id is None:
            continue

        io.write(_error_response(request_id, -32601, "Method not found"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass