# Copyright (c) 2025 Marc Schütze <scharc@gmail.com>
# SPDX-License-Identifier: MIT

"""Tests for remote Q&A manager."""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from boxctl.core.input_detection import InputType
from boxctl.remote_qa import (
    PendingQuestion,
    RemoteQAConfig,
    RemoteQAManager,
)


@pytest.fixture
def mock_get_buffer():
    """Mock function for getting session buffer."""
    return MagicMock(return_value=None)


@pytest.fixture
def mock_send_input():
    """Mock function for sending input."""
    return MagicMock(return_value=True)


@pytest.fixture
def config():
    """Default test configuration."""
    return RemoteQAConfig(
        enabled=True,
        check_interval_seconds=0.1,
        idle_threshold_seconds=0.1,
        question_ttl_seconds=60.0,
        dedup_window_seconds=5.0,
    )


@pytest.fixture
def manager(config, mock_get_buffer, mock_send_input):
    """Create a test manager."""
    return RemoteQAManager(
        config=config,
        get_session_buffer=mock_get_buffer,
        send_input=mock_send_input,
    )


class TestRemoteQAConfig:
    """Tests for RemoteQAConfig."""

    def test_from_dict_minimal(self):
        """Create config with minimal data."""
        config = RemoteQAConfig.from_dict({"enabled": True})
        assert config.enabled
        assert config.check_interval_seconds == 2.0
        assert config.telegram_bot_token is None

    def test_from_dict_full(self):
        """Create config with all fields."""
        config = RemoteQAConfig.from_dict(
            {
                "enabled": True,
                "check_interval_seconds": 5.0,
                "idle_threshold_seconds": 10.0,
                "telegram_bot_token": "test-token",
                "telegram_chat_id": "12345",
                "webhook_url": "https://example.com/webhook",
                "auto_answer": {
                    "enabled": True,
                    "confirmations": True,
                    "default_yes": False,
                },
            }
        )
        assert config.enabled
        assert config.check_interval_seconds == 5.0
        assert config.telegram_bot_token == "test-token"
        assert config.telegram_chat_id == "12345"
        assert config.auto_answer_enabled
        assert not config.auto_answer_default_yes

    def test_from_dict_env_fallback(self):
        """Config falls back to environment variables."""
        with patch.dict(
            "os.environ",
            {
                "TELEGRAM_BOT_TOKEN": "env-token",
                "TELEGRAM_CHAT_ID": "env-chat",
            },
        ):
            config = RemoteQAConfig.from_dict({"enabled": True})
            assert config.telegram_bot_token == "env-token"
            assert config.telegram_chat_id == "env-chat"


class TestRemoteQAManager:
    """Tests for RemoteQAManager."""

    def test_register_unregister_session(self, manager):
        """Register and unregister sessions."""
        manager.register_session("container1", "session1")
        assert ("container1", "session1") in manager.session_last_check

        manager.unregister_session("container1", "session1")
        assert ("container1", "session1") not in manager.session_last_check

    def test_start_stop(self, manager):
        """Start and stop monitor thread."""
        manager.start()
        assert manager._running
        assert manager._monitor_thread is not None
        assert manager._monitor_thread.is_alive()

        manager.stop()
        assert not manager._running

    def test_detect_question(self, manager, mock_get_buffer):
        """Detect a question in session buffer."""
        mock_get_buffer.return_value = "Continue? [Y/n]"

        manager.register_session("test-container", "test-session")

        # First call - buffer changed, reset idle timer
        manager._check_session("test-container", "test-session")
        assert len(manager.get_pending_questions()) == 0

        # Second call - buffer same, idle threshold met
        time.sleep(0.2)
        manager._check_session("test-container", "test-session")

        questions = manager.get_pending_questions()
        assert len(questions) == 1
        assert questions[0].input_type == InputType.CONFIRMATION

    def test_answer_question(self, manager, mock_send_input):
        """Answer a pending question."""
        # Create a pending question directly
        question = PendingQuestion(
            id="test-123",
            container="test-container",
            session="test-session",
            question="Continue?",
            summary="Continue? [Y/n]",
            input_type=InputType.CONFIRMATION,
            options=None,
            context="",
            detected_at=datetime.now(),
        )

        manager.pending_questions["test-container/test-session"] = question

        result = manager.answer_question("test-123", "y")
        assert result
        assert question.answered_at is not None
        assert question.answer == "y"
        mock_send_input.assert_called_once_with("test-container", "test-session", "y\n", True)

    def test_answer_nonexistent_question(self, manager):
        """Answering nonexistent question returns False."""
        result = manager.answer_question("nonexistent", "y")
        assert not result

    def test_answer_already_answered(self, manager):
        """Cannot answer an already answered question."""
        question = PendingQuestion(
            id="test-123",
            container="test-container",
            session="test-session",
            question="Continue?",
            summary="Continue? [Y/n]",
            input_type=InputType.CONFIRMATION,
            options=None,
            context="",
            detected_at=datetime.now(),
            answered_at=datetime.now(),  # Already answered
            answer="y",
        )

        manager.pending_questions["test-container/test-session"] = question

        result = manager.answer_question("test-123", "n")
        assert not result

    def test_auto_answer_confirmation(self, config, mock_get_buffer, mock_send_input):
        """Auto-answer confirmation prompts."""
        config.auto_answer_enabled = True
        config.auto_answer_confirmations = True
        config.auto_answer_default_yes = True

        manager = RemoteQAManager(
            config=config,
            get_session_buffer=mock_get_buffer,
            send_input=mock_send_input,
        )

        mock_get_buffer.return_value = "Continue? [Y/n]"
        manager.register_session("test-container", "test-session")

        # First check - reset idle
        manager._check_session("test-container", "test-session")

        # Second check - should auto-answer
        time.sleep(0.2)
        manager._check_session("test-container", "test-session")

        # Should have sent "y" automatically
        mock_send_input.assert_called_with("test-container", "test-session", "y\n", True)

    def test_no_auto_answer_when_disabled(self, config, mock_get_buffer, mock_send_input):
        """Don't auto-answer when disabled."""
        config.auto_answer_enabled = False

        manager = RemoteQAManager(
            config=config,
            get_session_buffer=mock_get_buffer,
            send_input=mock_send_input,
        )

        mock_get_buffer.return_value = "Continue? [Y/n]"
        manager.register_session("test-container", "test-session")

        manager._check_session("test-container", "test-session")
        time.sleep(0.2)
        manager._check_session("test-container", "test-session")

        # Should not have called send_input for auto-answer
        mock_send_input.assert_not_called()

    def test_notification_callback(self, manager, mock_get_buffer):
        """Notification callbacks are called."""
        callback = MagicMock()
        manager.add_notification_callback(callback)

        mock_get_buffer.return_value = "Continue? [Y/n]"
        manager.register_session("test-container", "test-session")

        manager._check_session("test-container", "test-session")
        time.sleep(0.2)
        manager._check_session("test-container", "test-session")

        callback.assert_called_once()
        question = callback.call_args[0][0]
        assert question.container == "test-container"

    def test_deduplication(self, manager, mock_get_buffer):
        """Don't re-notify same question within dedup window."""
        callback = MagicMock()
        manager.add_notification_callback(callback)

        mock_get_buffer.return_value = "Continue? [Y/n]"
        manager.register_session("test-container", "test-session")

        # First detection
        manager._check_session("test-container", "test-session")
        time.sleep(0.2)
        manager._check_session("test-container", "test-session")

        # Second detection - should not notify again
        time.sleep(0.2)
        manager._check_session("test-container", "test-session")

        assert callback.call_count == 1

    def test_cleanup_expired(self, manager):
        """Expired questions are cleaned up."""
        question = PendingQuestion(
            id="test-123",
            container="test-container",
            session="test-session",
            question="Continue?",
            summary="Continue? [Y/n]",
            input_type=InputType.CONFIRMATION,
            options=None,
            context="",
            detected_at=datetime.now(),
            expires_at=datetime.now() - timedelta(seconds=1),  # Already expired
        )

        manager.pending_questions["test-container/test-session"] = question

        manager._cleanup_expired()

        assert len(manager.pending_questions) == 0

    def test_busy_buffer_not_detected(self, manager, mock_get_buffer):
        """Busy patterns are not detected as waiting."""
        mock_get_buffer.return_value = "Processing... 45%"
        manager.register_session("test-container", "test-session")

        manager._check_session("test-container", "test-session")
        time.sleep(0.2)
        manager._check_session("test-container", "test-session")

        assert len(manager.get_pending_questions()) == 0

    def test_get_question_by_id(self, manager):
        """Get question by ID."""
        question = PendingQuestion(
            id="test-123",
            container="test-container",
            session="test-session",
            question="Continue?",
            summary="Continue? [Y/n]",
            input_type=InputType.CONFIRMATION,
            options=None,
            context="",
            detected_at=datetime.now(),
        )

        manager.pending_questions["test-container/test-session"] = question

        found = manager.get_question("test-123")
        assert found is not None
        assert found.id == "test-123"

        not_found = manager.get_question("nonexistent")
        assert not_found is None
