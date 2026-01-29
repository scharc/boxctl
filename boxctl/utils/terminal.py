# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Terminal utilities for cleanup and reset operations."""

import os
import sys

# Escape sequences to disable all mouse tracking modes
# These must be sent when exiting tmux sessions to prevent
# mouse escape sequences from leaking into the terminal
MOUSE_RESET_SEQUENCES = (
    "\033[?1006l"  # Disable SGR extended mouse mode (the [<...M format)
    "\033[?1003l"  # Disable any-event mouse tracking
    "\033[?1002l"  # Disable button-event mouse tracking
    "\033[?1000l"  # Disable basic mouse tracking
    "\033[?25h"  # Show cursor
    "\033[0m"  # Reset all attributes (colors, bold, etc.)
)


def reset_terminal() -> None:
    """Reset terminal to disable all mouse tracking modes.

    This should be called after exiting tmux sessions or when
    containers are destroyed to prevent mouse escape sequences
    from leaking into the host terminal.

    Safe to call even if terminal is already in normal mode.
    """
    try:
        # Write escape sequences to disable mouse mode
        sys.stdout.write(MOUSE_RESET_SEQUENCES)
        sys.stdout.flush()
    except (IOError, OSError):
        # Ignore errors if stdout is not a terminal
        pass

    # Reset terminal settings with stty
    # This handles any other terminal corruption
    os.system("stty sane 2>/dev/null")
