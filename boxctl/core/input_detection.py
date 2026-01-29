# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Input detection for agent sessions.

Detects when an agent is waiting for user input by analyzing
the terminal buffer content and matching against known patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


class InputType(Enum):
    """Type of input the agent is waiting for."""

    QUESTION = "question"  # Yes/no, choice selection
    TEXT = "text"  # Free-form text input
    PASSWORD = "password"  # Sensitive input (password, token)
    CONFIRMATION = "confirmation"  # Press Enter to continue
    UNKNOWN = "unknown"


@dataclass
class DetectedInput:
    """Result of input detection."""

    waiting: bool
    input_type: InputType
    question: Optional[str]  # The question being asked
    options: Optional[List[str]]  # Available options if any
    context: Optional[str]  # Surrounding context for AI analysis
    pattern_matched: Optional[str]  # Which pattern triggered detection


# Patterns that indicate the agent is waiting for input
# Each tuple: (pattern, input_type, option_extractor or None)
INPUT_PATTERNS: List[Tuple[str, InputType, Optional[str]]] = [
    # Claude Code / AI agent patterns
    (r"^\s*\?\s+.+\?\s*$", InputType.QUESTION, None),
    (r"Select an option:", InputType.QUESTION, r"^\s*(\d+)\.\s+(.+)$"),
    (r"Choose.*:", InputType.QUESTION, None),
    (r"Which.*\?", InputType.QUESTION, None),
    # Yes/No confirmations
    (r"\[Y/n\]", InputType.CONFIRMATION, None),
    (r"\[y/N\]", InputType.CONFIRMATION, None),
    (r"\(y/n\)", InputType.CONFIRMATION, None),
    (r"\(yes/no\)", InputType.CONFIRMATION, None),
    (r"Continue\?", InputType.CONFIRMATION, None),
    (r"Proceed\?", InputType.CONFIRMATION, None),
    (r"Are you sure\?", InputType.CONFIRMATION, None),
    # Text input prompts
    (r"Enter .+:", InputType.TEXT, None),
    (r"Type .+:", InputType.TEXT, None),
    (r"Input .+:", InputType.TEXT, None),
    (r"Provide .+:", InputType.TEXT, None),
    (r"Please enter", InputType.TEXT, None),
    # Password/sensitive input
    (r"[Pp]assword:", InputType.PASSWORD, None),
    (r"[Pp]assphrase:", InputType.PASSWORD, None),
    (r"[Tt]oken:", InputType.PASSWORD, None),
    (r"[Ss]ecret:", InputType.PASSWORD, None),
    (r"API [Kk]ey:", InputType.PASSWORD, None),
    # Press Enter prompts
    (r"Press Enter", InputType.CONFIRMATION, None),
    (r"Press any key", InputType.CONFIRMATION, None),
    (r"Hit Enter", InputType.CONFIRMATION, None),
    # npm/yarn prompts
    (r"Is this OK\?", InputType.CONFIRMATION, None),
    (r"Ok to proceed\?", InputType.CONFIRMATION, None),
    # Git prompts
    (r"Overwrite.*\?", InputType.CONFIRMATION, None),
    (r"Delete.*\?", InputType.CONFIRMATION, None),
]

# Patterns that indicate the agent is actively working (not waiting)
BUSY_PATTERNS: List[str] = [
    r"^\s*\.\.\.\s*$",  # ... (processing)
    r"^\s*⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏",  # Spinner characters
    r"Compiling",
    r"Building",
    r"Installing",
    r"Downloading",
    r"Fetching",
    r"Running",
    r"Processing",
    r"Loading",
    r"Thinking",
    r"Analyzing",
    r"\d+%",  # Progress percentage
]


def detect_input_waiting(
    buffer: str,
    cursor_at_end: bool = True,
    idle_seconds: float = 0.0,
) -> DetectedInput:
    """Detect if the agent is waiting for user input.

    Args:
        buffer: Terminal buffer content
        cursor_at_end: Whether cursor is at the end of buffer
        idle_seconds: How long the session has been idle

    Returns:
        DetectedInput with detection results
    """
    if not buffer or not buffer.strip():
        return DetectedInput(
            waiting=False,
            input_type=InputType.UNKNOWN,
            question=None,
            options=None,
            context=None,
            pattern_matched=None,
        )

    lines = buffer.strip().split("\n")
    last_lines = lines[-10:]  # Focus on last 10 lines

    # Check for busy patterns first (agent is working, not waiting)
    for line in last_lines[-3:]:  # Only check very recent lines
        for pattern in BUSY_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                return DetectedInput(
                    waiting=False,
                    input_type=InputType.UNKNOWN,
                    question=None,
                    options=None,
                    context=None,
                    pattern_matched=None,
                )

    # Check for input patterns
    for line in reversed(last_lines):
        for pattern, input_type, option_pattern in INPUT_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Found a match - extract question and options
                question = _extract_question(lines, line)
                options = _extract_options(lines, option_pattern) if option_pattern else None

                # Get context (last N lines for AI analysis)
                context = "\n".join(last_lines)

                return DetectedInput(
                    waiting=True,
                    input_type=input_type,
                    question=question,
                    options=options,
                    context=context,
                    pattern_matched=pattern,
                )

    # No input pattern found
    return DetectedInput(
        waiting=False,
        input_type=InputType.UNKNOWN,
        question=None,
        options=None,
        context=None,
        pattern_matched=None,
    )


def _extract_question(lines: List[str], trigger_line: str) -> str:
    """Extract the full question from the buffer.

    Looks backwards from the trigger line to build the complete question.
    """
    # Start with the trigger line
    question_parts = [trigger_line.strip()]

    # Look at a few lines before for context
    trigger_idx = None
    for i, line in enumerate(lines):
        if line == trigger_line:
            trigger_idx = i
            break

    if trigger_idx is not None and trigger_idx > 0:
        # Include 1-2 lines before if they seem related
        for i in range(max(0, trigger_idx - 2), trigger_idx):
            prev_line = lines[i].strip()
            if prev_line and not _is_separator(prev_line):
                question_parts.insert(0, prev_line)

    return " ".join(question_parts)


def _extract_options(lines: List[str], option_pattern: str) -> Optional[List[str]]:
    """Extract numbered options from the buffer."""
    options = []
    pattern = re.compile(option_pattern)

    for line in lines:
        match = pattern.match(line.strip())
        if match:
            # Assuming pattern captures (number, text)
            groups = match.groups()
            if len(groups) >= 2:
                options.append(groups[1])
            elif len(groups) >= 1:
                options.append(groups[0])

    return options if options else None


def _is_separator(line: str) -> bool:
    """Check if a line is a visual separator."""
    stripped = line.strip()
    if not stripped:
        return True
    # Lines that are just dashes, equals, etc.
    if all(c in "-=_*#" for c in stripped):
        return True
    return False


def summarize_question(
    detected: DetectedInput,
    max_length: int = 100,
) -> str:
    """Create a short summary of the detected question.

    Args:
        detected: DetectedInput from detect_input_waiting
        max_length: Maximum length of summary

    Returns:
        Short summary string suitable for notifications
    """
    if not detected.waiting or not detected.question:
        return "Agent needs input"

    # Clean up the question
    question = detected.question.strip()

    # Remove ANSI escape codes
    question = re.sub(r"\x1b\[[0-9;]*m", "", question)

    # Truncate if too long
    if len(question) > max_length:
        question = question[: max_length - 3] + "..."

    # Add options hint if available
    if detected.options:
        opts = ", ".join(detected.options[:3])
        if len(detected.options) > 3:
            opts += f", +{len(detected.options) - 3} more"
        question = f"{question} [{opts}]"

    return question
