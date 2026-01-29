# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""LLM-powered output parsing for agent rate limit detection.

Uses oneshot-llm (haiku/gpt-4o-mini) to parse agent output instead of brittle regex.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Path to oneshot-llm script
ONESHOT_LLM = Path("/workspace/bin/oneshot-llm")

# Prompt for parsing agent output
PARSE_PROMPT = """Extract from this agent output:
- is_limited: boolean (true if rate limit, usage limit, or quota exceeded)
- resets_in_seconds: integer or null (seconds until limit resets)
- error_type: string or null (e.g., "rate_limit", "usage_limit_reached", "quota_exceeded")
- tokens_used: integer or null
- cost_usd: float or null

Return ONLY valid JSON, no markdown code blocks."""


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()

    # Try to extract from markdown code block
    if "```json" in text:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
    elif "```" in text:
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)

    return json.loads(text)


def _parse_with_llm(output: str, provider: str = "claude", model: str = "fast") -> dict:
    """Parse agent output using oneshot-llm.

    Args:
        output: Agent output to parse
        provider: LLM provider to use
        model: Model alias (fast, balanced, powerful)

    Returns:
        Dict with parsed fields (is_limited, resets_in_seconds, error_type, etc.)
    """
    if not ONESHOT_LLM.exists():
        raise FileNotFoundError(f"oneshot-llm not found at {ONESHOT_LLM}")

    prompt = f"{PARSE_PROMPT}\n\nAgent output:\n{output}"

    try:
        result = subprocess.run(
            [str(ONESHOT_LLM), "--provider", provider, "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "BOXCTL_INVOCATION_DEPTH": "2"},
        )

        if result.returncode != 0:
            # LLM failed, fall back to simple parsing
            return _simple_parse(output)

        return _extract_json(result.stdout)

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        # Fall back to simple parsing
        return _simple_parse(output)


def _simple_parse(output: str) -> dict:
    """Simple regex-based parsing as fallback.

    Used when LLM parsing fails or is unavailable.
    """
    output_lower = output.lower()

    is_limited = any(
        phrase in output_lower
        for phrase in [
            "rate limit",
            "usage limit",
            "quota exceeded",
            "too many requests",
            "usage_limit_reached",
        ]
    )

    # Try to extract resets_in_seconds from codex-style JSON error
    resets_in_seconds = None
    resets_match = re.search(r'"resets_in_seconds"\s*:\s*(\d+)', output)
    if resets_match:
        resets_in_seconds = int(resets_match.group(1))

    # Try to extract error type
    error_type = None
    if "usage_limit_reached" in output_lower:
        error_type = "usage_limit_reached"
    elif "rate limit" in output_lower:
        error_type = "rate_limit"
    elif "quota exceeded" in output_lower:
        error_type = "quota_exceeded"

    return {
        "is_limited": is_limited,
        "resets_in_seconds": resets_in_seconds,
        "error_type": error_type,
        "tokens_used": None,
        "cost_usd": None,
    }


def parse_agent_output(output: str, use_llm: bool = True) -> dict:
    """Parse agent output to detect rate limits.

    Args:
        output: Agent stdout/stderr output
        use_llm: Whether to use LLM for parsing (falls back to regex if False)

    Returns:
        Dict with:
            is_limited: bool - Whether agent is rate-limited
            resets_in_seconds: int | None - Seconds until limit resets
            error_type: str | None - Type of error
            tokens_used: int | None - Tokens used (if reported)
            cost_usd: float | None - Cost in USD (if reported)
    """
    if use_llm and ONESHOT_LLM.exists():
        return _parse_with_llm(output)
    return _simple_parse(output)


def probe_agent(agent: str, timeout: int = 30) -> dict:
    """Probe an agent to check if it's rate-limited.

    Sends a minimal test prompt and parses the response.

    Args:
        agent: Agent command (claude, codex, gemini)
        timeout: Timeout in seconds

    Returns:
        Dict with parsed result including is_limited and resets_in_seconds
    """
    # Map agent names to base commands
    base_command = agent.replace("super", "")

    # Build probe command
    cmd = [base_command, "-p"]  # -p for print mode (non-interactive)

    try:
        result = subprocess.run(
            cmd,
            input="ping",
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "BOXCTL_INVOCATION_DEPTH": "1"},
        )

        # Combine stdout and stderr for parsing
        output = f"{result.stdout}\n{result.stderr}"
        parsed = parse_agent_output(output)

        # Calculate resets_at if we have resets_in_seconds
        if parsed.get("resets_in_seconds"):
            resets_at = datetime.now(timezone.utc) + timedelta(seconds=parsed["resets_in_seconds"])
            parsed["resets_at"] = resets_at

        return parsed

    except subprocess.TimeoutExpired:
        return {
            "is_limited": False,
            "error_type": "timeout",
            "resets_in_seconds": None,
            "tokens_used": None,
            "cost_usd": None,
        }
    except FileNotFoundError:
        return {
            "is_limited": False,
            "error_type": "not_installed",
            "resets_in_seconds": None,
            "tokens_used": None,
            "cost_usd": None,
        }
