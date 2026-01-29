# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT
# See LICENSE file in the project root for full license information.

"""Fast streaming I/O for tmux sessions using pipe-pane."""

import asyncio
import os
import tempfile
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Optional

from boxctl.paths import BinPaths


class TmuxStreamSession:
    """Manages streaming I/O for a tmux session via pipe-pane."""

    def __init__(self, session_name: str):
        self.session_name = session_name
        self.fifo_dir = Path(tempfile.mkdtemp(prefix=f"tmux-stream-{session_name}-"))
        self.output_fifo = self.fifo_dir / "output"
        self.input_fifo = self.fifo_dir / "input"
        self.output_pipe = None
        self.input_pipe = None
        self._pipe_pane_proc = None
        self._cleanup_done = False

    async def start(self):
        """Start streaming pipes."""
        # Create FIFOs
        os.mkfifo(self.output_fifo)
        os.mkfifo(self.input_fifo)

        # Start tmux pipe-pane to capture output
        # -O: pipe output to file/fifo
        # -o: only capture new output (don't replay history)
        subprocess.run(
            [
                BinPaths.TMUX,
                "pipe-pane",
                "-O",
                "-o",
                "-t",
                self.session_name,
                f"cat > {self.output_fifo}",
            ],
            check=False,
        )

        # Open FIFOs for async reading/writing
        # Open output FIFO for reading (non-blocking)
        loop = asyncio.get_event_loop()
        self.output_pipe = await loop.run_in_executor(
            None, lambda: open(self.output_fifo, "rb", buffering=0)
        )

        # Open input FIFO for writing (non-blocking)
        self.input_pipe = await loop.run_in_executor(
            None, lambda: open(self.input_fifo, "wb", buffering=0)
        )

        # Start background process to pipe input FIFO to tmux
        # This continuously reads from input_fifo and sends to tmux
        self._pipe_pane_proc = subprocess.Popen(
            [
                "sh",
                "-c",
                f"tail -f {self.input_fifo} | BinPaths.TMUX load-buffer -b stream-input - && BinPaths.TMUX paste-buffer -b stream-input -t {self.session_name}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def send_keys(self, data: bytes):
        """Send keystrokes to tmux session (fast - just writes to FIFO)."""
        if self.input_pipe and not self.input_pipe.closed:
            try:
                # Direct write to FIFO - tmux will receive instantly
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.input_pipe.write, data)
                await loop.run_in_executor(None, self.input_pipe.flush)
            except Exception:
                pass

    async def read_output(self, timeout: float = 0.1) -> Optional[bytes]:
        """Read output from tmux session (non-blocking)."""
        if not self.output_pipe or self.output_pipe.closed:
            return None

        try:
            loop = asyncio.get_event_loop()
            # Non-blocking read with timeout
            data = await asyncio.wait_for(
                loop.run_in_executor(None, self.output_pipe.read, 4096), timeout=timeout
            )
            return data if data else None
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    async def cleanup(self):
        """Clean up FIFOs and stop pipe-pane."""
        if self._cleanup_done:
            return
        self._cleanup_done = True

        # Stop tmux pipe-pane
        subprocess.run(
            [BinPaths.TMUX, "pipe-pane", "-t", self.session_name], check=False, capture_output=True
        )

        # Kill background process
        if self._pipe_pane_proc:
            with suppress(OSError, subprocess.TimeoutExpired):
                self._pipe_pane_proc.terminate()
                self._pipe_pane_proc.wait(timeout=1)
            with suppress(OSError):
                self._pipe_pane_proc.kill()

        # Close pipes
        if self.output_pipe:
            with suppress(OSError, IOError):
                self.output_pipe.close()

        if self.input_pipe:
            with suppress(OSError, IOError):
                self.input_pipe.close()

        # Remove FIFOs
        with suppress(OSError, FileNotFoundError):
            self.output_fifo.unlink(missing_ok=True)
            self.input_fifo.unlink(missing_ok=True)
            self.fifo_dir.rmdir()

    def __del__(self):
        """Ensure cleanup on deletion."""
        if not self._cleanup_done:
            # Sync cleanup in destructor
            import subprocess

            subprocess.run(
                [BinPaths.TMUX, "pipe-pane", "-t", self.session_name],
                check=False,
                capture_output=True,
            )
