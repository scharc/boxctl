# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Telegram notification channel for Remote Q&A.

Sends questions via Telegram Bot API and polls for answers using getUpdates.
"""

from __future__ import annotations

import json
import re
from typing import List, Tuple, TYPE_CHECKING
from urllib.request import Request, urlopen
from urllib.error import URLError

from boxctl.channels import NotificationChannel
from boxctl.paths import ContainerDefaults
from boxctl.utils.logging import get_logger

if TYPE_CHECKING:
    from boxctl.remote_qa import PendingQuestion

logger = get_logger(__name__)


class TelegramChannel(NotificationChannel):
    """Telegram notification channel using Bot API.

    Sends question notifications and polls for /answer replies.
    """

    def __init__(self, bot_token: str, chat_id: str):
        """Initialize the Telegram channel.

        Args:
            bot_token: Telegram Bot API token
            chat_id: Chat ID to send messages to and receive answers from
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._last_update_id = 0

    @property
    def name(self) -> str:
        return "telegram"

    def send_question(self, question: "PendingQuestion") -> bool:
        """Send a question notification via Telegram."""
        try:
            # Extract project name from container
            project = ContainerDefaults.project_from_container(question.container)

            # Build message
            text = f"🤖 *{project}* needs input\n\n"
            text += f"_{question.summary}_\n\n"

            if question.options:
                text += "Options:\n"
                for i, opt in enumerate(question.options, 1):
                    text += f"  {i}. {opt}\n"
                text += "\n"

            text += f"Reply with: `/answer {question.id} <response>`"

            return self._send_message(text)

        except Exception as e:
            logger.error(f"Telegram send_question error: {e}")
            return False

    def poll_answers(self) -> List[Tuple[str, str]]:
        """Poll for /answer commands from Telegram.

        Returns:
            List of (question_id, answer) tuples.
        """
        answers = []

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            params = {
                "offset": self._last_update_id + 1,
                "timeout": 0,  # Non-blocking
                "allowed_updates": ["message"],
            }

            req = Request(
                f"{url}?{self._encode_params(params)}",
                headers={"Content-Type": "application/json"},
            )

            with urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    return answers

                data = json.loads(resp.read().decode("utf-8"))
                if not data.get("ok"):
                    return answers

                for update in data.get("result", []):
                    update_id = update.get("update_id", 0)
                    if update_id > self._last_update_id:
                        self._last_update_id = update_id

                    message = update.get("message", {})

                    # Verify the message is from the configured chat
                    msg_chat_id = str(message.get("chat", {}).get("id", ""))
                    if msg_chat_id != self.chat_id:
                        continue

                    text = message.get("text", "")
                    parsed = self._parse_answer_command(text)
                    if parsed:
                        answers.append(parsed)

        except URLError as e:
            logger.debug(f"Telegram poll error: {e}")
        except Exception as e:
            logger.error(f"Telegram poll_answers error: {e}")

        return answers

    def send_reply(self, text: str) -> None:
        """Send a confirmation message."""
        try:
            self._send_message(text)
        except Exception as e:
            logger.error(f"Telegram send_reply error: {e}")

    def _send_message(self, text: str) -> bool:
        """Send a message via Telegram Bot API."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }

            req = Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )

            with urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logger.debug("Telegram message sent")
                    return True
                else:
                    logger.warning(f"Telegram API returned {resp.status}")
                    return False

        except URLError as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def _parse_answer_command(self, text: str) -> Tuple[str, str] | None:
        """Parse an /answer command.

        Expected format: /answer <question_id> <response>

        Returns:
            Tuple of (question_id, answer) or None if not an answer command.
        """
        if not text:
            return None

        # Match /answer command with question ID and response
        match = re.match(r"^/answer\s+(\S+)\s+(.+)$", text, re.DOTALL)
        if match:
            question_id = match.group(1)
            answer = match.group(2).strip()
            return (question_id, answer)

        return None

    @staticmethod
    def _encode_params(params: dict) -> str:
        """URL encode parameters."""
        from urllib.parse import urlencode

        return urlencode(params)
