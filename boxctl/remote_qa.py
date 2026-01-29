# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Remote Q&A manager for agent sessions.

Monitors agent sessions for input-waiting states and enables
remote notification and response handling via Telegram, webhooks, etc.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from boxctl.core.input_detection import (
    DetectedInput,
    InputType,
    detect_input_waiting,
    summarize_question,
)
from boxctl.utils.logging import get_logger

if TYPE_CHECKING:
    from boxctl.channels import NotificationChannel

logger = get_logger(__name__)


@dataclass
class PendingQuestion:
    """A question waiting for remote response."""

    id: str
    container: str
    session: str
    question: str
    summary: str
    input_type: InputType
    options: Optional[List[str]]
    context: str
    detected_at: datetime
    notified_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None
    answer: Optional[str] = None
    auto_answered: bool = False
    expires_at: datetime = field(default_factory=lambda: datetime.now() + timedelta(hours=1))


@dataclass
class RemoteQAConfig:
    """Configuration for remote Q&A."""

    enabled: bool = False
    check_interval_seconds: float = 2.0
    idle_threshold_seconds: float = 5.0
    question_ttl_seconds: float = 3600.0  # 1 hour
    dedup_window_seconds: float = 30.0  # Don't re-notify same question within this window

    # Notification channels
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_headers: Dict[str, str] = field(default_factory=dict)

    # Auto-answer settings
    auto_answer_enabled: bool = False
    auto_answer_confirmations: bool = True  # Auto-answer [Y/n] type prompts
    auto_answer_default_yes: bool = True  # Default to Yes for confirmations

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemoteQAConfig":
        """Create config from dictionary."""
        return cls(
            enabled=data.get("enabled", False),
            check_interval_seconds=float(data.get("check_interval_seconds", 2.0)),
            idle_threshold_seconds=float(data.get("idle_threshold_seconds", 5.0)),
            question_ttl_seconds=float(data.get("question_ttl_seconds", 3600.0)),
            dedup_window_seconds=float(data.get("dedup_window_seconds", 30.0)),
            telegram_bot_token=data.get("telegram_bot_token")
            or os.environ.get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=data.get("telegram_chat_id") or os.environ.get("TELEGRAM_CHAT_ID"),
            webhook_url=data.get("webhook_url"),
            webhook_headers=data.get("webhook_headers", {}),
            auto_answer_enabled=data.get("auto_answer", {}).get("enabled", False),
            auto_answer_confirmations=data.get("auto_answer", {}).get("confirmations", True),
            auto_answer_default_yes=data.get("auto_answer", {}).get("default_yes", True),
        )


class RemoteQAManager:
    """Manages remote Q&A for agent sessions.

    Monitors session buffers, detects input-waiting states,
    sends notifications, and handles remote responses.
    """

    def __init__(
        self,
        config: RemoteQAConfig,
        get_session_buffer: Callable[[str, str], Optional[str]],
        send_input: Callable[[str, str, str, bool], bool],
    ):
        """Initialize the manager.

        Args:
            config: Remote Q&A configuration
            get_session_buffer: Function to get buffer for (container, session)
            send_input: Function to send input to (container, session, keys, literal)
        """
        self.config = config
        self._get_session_buffer = get_session_buffer
        self._send_input = send_input

        # Pending questions: key = "{container}/{session}"
        self.pending_questions: Dict[str, PendingQuestion] = {}
        self.questions_lock = threading.Lock()

        # Session tracking
        self.session_last_check: Dict[Tuple[str, str], float] = {}
        self.session_last_buffer: Dict[Tuple[str, str], str] = {}

        # Monitor thread
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None

        # Notification callbacks
        self._notification_callbacks: List[Callable[[PendingQuestion], None]] = []

        # Notification channels
        self._channels: List["NotificationChannel"] = []
        self._init_builtin_channels()

    def start(self) -> None:
        """Start the monitor thread."""
        if self._running:
            return

        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="remote-qa-monitor",
        )
        self._monitor_thread.start()
        logger.info("Remote Q&A monitor started")

    def stop(self) -> None:
        """Stop the monitor thread."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None
        logger.info("Remote Q&A monitor stopped")

    def register_session(self, container: str, session: str) -> None:
        """Register a session for monitoring."""
        key = (container, session)
        self.session_last_check[key] = time.time()
        self.session_last_buffer[key] = ""
        logger.debug(f"Registered session for monitoring: {container}/{session}")

    def unregister_session(self, container: str, session: str) -> None:
        """Unregister a session from monitoring."""
        key = (container, session)
        self.session_last_check.pop(key, None)
        self.session_last_buffer.pop(key, None)

        # Remove any pending questions for this session
        q_key = f"{container}/{session}"
        with self.questions_lock:
            self.pending_questions.pop(q_key, None)

        logger.debug(f"Unregistered session: {container}/{session}")

    def add_notification_callback(self, callback: Callable[[PendingQuestion], None]) -> None:
        """Add a callback to be called when a new question is detected."""
        self._notification_callbacks.append(callback)

    def _init_builtin_channels(self) -> None:
        """Initialize built-in notification channels from config."""
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            from boxctl.channels.telegram import TelegramChannel

            self._channels.append(
                TelegramChannel(
                    self.config.telegram_bot_token,
                    self.config.telegram_chat_id,
                )
            )
            logger.info("Telegram channel initialized")

    def register_channel(self, channel: "NotificationChannel") -> None:
        """Register a custom notification channel.

        Args:
            channel: A NotificationChannel implementation to add.

        Example:
            manager.register_channel(SlackChannel("https://hooks.slack.com/..."))
        """
        self._channels.append(channel)
        logger.info(f"Registered notification channel: {channel.name}")

    def get_pending_questions(self) -> List[PendingQuestion]:
        """Get all pending (unanswered) questions."""
        with self.questions_lock:
            now = datetime.now()
            return [
                q
                for q in self.pending_questions.values()
                if q.answered_at is None and q.expires_at > now
            ]

    def get_question(self, question_id: str) -> Optional[PendingQuestion]:
        """Get a specific question by ID."""
        with self.questions_lock:
            for q in self.pending_questions.values():
                if q.id == question_id:
                    return q
        return None

    def answer_question(self, question_id: str, answer: str) -> bool:
        """Answer a pending question.

        Args:
            question_id: The question ID
            answer: The answer to send

        Returns:
            True if successful
        """
        with self.questions_lock:
            question = None
            for q in self.pending_questions.values():
                if q.id == question_id:
                    question = q
                    break

            if not question:
                logger.warning(f"Question not found: {question_id}")
                return False

            if question.answered_at is not None:
                logger.warning(f"Question already answered: {question_id}")
                return False

        # Send the answer to the session
        success = self._send_input(
            question.container,
            question.session,
            answer + "\n",  # Add Enter key
            True,  # literal mode
        )

        if success:
            with self.questions_lock:
                question.answered_at = datetime.now()
                question.answer = answer
            logger.info(f"Answered question {question_id}: {answer}")
        else:
            logger.error(f"Failed to send answer for question {question_id}")

        return success

    def _monitor_loop(self) -> None:
        """Background loop that monitors sessions for input-waiting state."""
        while self._running:
            try:
                self._check_sessions()
                self._cleanup_expired()
                self._poll_channels()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

            time.sleep(self.config.check_interval_seconds)

    def _check_sessions(self) -> None:
        """Check all registered sessions for input-waiting state."""
        sessions = list(self.session_last_check.keys())

        for container, session in sessions:
            try:
                self._check_session(container, session)
            except Exception as e:
                logger.error(f"Error checking session {container}/{session}: {e}")

    def _check_session(self, container: str, session: str) -> None:
        """Check a single session for input-waiting state."""
        key = (container, session)
        q_key = f"{container}/{session}"

        # Get current buffer
        buffer = self._get_session_buffer(container, session)
        if not buffer:
            return

        # Check if buffer has changed
        last_buffer = self.session_last_buffer.get(key, "")
        if buffer == last_buffer:
            # Buffer unchanged - check idle time
            idle_time = time.time() - self.session_last_check.get(key, time.time())
            if idle_time < self.config.idle_threshold_seconds:
                return  # Not idle long enough
        else:
            # Buffer changed - update tracking
            self.session_last_buffer[key] = buffer
            self.session_last_check[key] = time.time()
            return  # Wait for idle period

        # Check for input-waiting patterns
        detected = detect_input_waiting(buffer)
        if not detected.waiting:
            # Not waiting - clear any pending question for this session
            with self.questions_lock:
                if q_key in self.pending_questions:
                    # Question was answered some other way (manually)
                    self.pending_questions.pop(q_key, None)
            return

        # Check if we already have a pending question for this session
        with self.questions_lock:
            existing = self.pending_questions.get(q_key)
            if existing and existing.answered_at is None:
                # Check if it's the same question (within dedup window)
                if existing.summary == summarize_question(detected):
                    time_since_notify = (
                        (datetime.now() - existing.notified_at).total_seconds()
                        if existing.notified_at
                        else float("inf")
                    )
                    if time_since_notify < self.config.dedup_window_seconds:
                        return  # Already notified recently

        # New question detected
        question = self._create_question(container, session, detected)

        # Check for auto-answer
        if self._should_auto_answer(question):
            if self._auto_answer(question):
                return  # Successfully auto-answered
            # Auto-answer failed, fall through to store and notify

        # Store and notify
        with self.questions_lock:
            self.pending_questions[q_key] = question

        self._notify_question(question)

    def _create_question(
        self,
        container: str,
        session: str,
        detected: DetectedInput,
    ) -> PendingQuestion:
        """Create a PendingQuestion from detected input."""
        now = datetime.now()
        question_id = f"{container}-{session}-{int(now.timestamp() * 1000)}"

        return PendingQuestion(
            id=question_id,
            container=container,
            session=session,
            question=detected.question or "Unknown question",
            summary=summarize_question(detected),
            input_type=detected.input_type,
            options=detected.options,
            context=detected.context or "",
            detected_at=now,
            expires_at=now + timedelta(seconds=self.config.question_ttl_seconds),
        )

    def _should_auto_answer(self, question: PendingQuestion) -> bool:
        """Check if a question should be auto-answered."""
        if not self.config.auto_answer_enabled:
            return False

        if question.input_type == InputType.CONFIRMATION:
            return self.config.auto_answer_confirmations

        return False

    def _auto_answer(self, question: PendingQuestion) -> bool:
        """Auto-answer a question.

        Returns:
            True if the question was successfully auto-answered, False otherwise.
        """
        if question.input_type == InputType.CONFIRMATION:
            answer = "y" if self.config.auto_answer_default_yes else "n"
        else:
            return False  # Don't auto-answer other types

        success = self._send_input(
            question.container,
            question.session,
            answer + "\n",
            True,
        )

        if success:
            question.answered_at = datetime.now()
            question.answer = answer
            question.auto_answered = True
            logger.info(
                f"Auto-answered question for {question.container}/{question.session}: {answer}"
            )
            return True
        else:
            logger.warning(
                f"Auto-answer failed for {question.container}/{question.session}, falling back to notification"
            )
            return False

    def _notify_question(self, question: PendingQuestion) -> None:
        """Send notifications for a new question."""
        question.notified_at = datetime.now()

        # Call registered callbacks
        for callback in self._notification_callbacks:
            try:
                callback(question)
            except Exception as e:
                logger.error(f"Notification callback error: {e}")

        # Send via all registered channels
        for channel in self._channels:
            try:
                if channel.send_question(question):
                    logger.info(f"Notification sent via {channel.name} for {question.id}")
            except Exception as e:
                logger.error(f"Channel {channel.name} notification error: {e}")

    def _poll_channels(self) -> None:
        """Poll all channels for answers."""
        for channel in self._channels:
            try:
                for question_id, answer in channel.poll_answers():
                    if self.answer_question(question_id, answer):
                        channel.send_reply(f"✓ Sent: {answer}")
                    else:
                        channel.send_reply(f"✗ Failed to send answer for {question_id}")
            except Exception as e:
                logger.error(f"Channel {channel.name} poll error: {e}")

    def _cleanup_expired(self) -> None:
        """Remove expired questions."""
        now = datetime.now()
        with self.questions_lock:
            expired = [key for key, q in self.pending_questions.items() if q.expires_at < now]
            for key in expired:
                self.pending_questions.pop(key, None)
                logger.debug(f"Cleaned up expired question: {key}")
