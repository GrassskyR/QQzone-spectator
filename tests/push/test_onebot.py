"""Tests for qqzone_spectator.push.onebot."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import responses

from qqzone_spectator.models import QzonePost
from qqzone_spectator.push.onebot import OneBotClient, build_post_message, format_post_created_at


# ---------------------------------------------------------------------------
# OneBotClient init
# ---------------------------------------------------------------------------
class TestOneBotClientInit:
    def test_valid(self):
        client = OneBotClient("http://127.0.0.1:5700")
        assert client.base_url == "http://127.0.0.1:5700"

    def test_empty_url(self):
        with pytest.raises(ValueError, match="ONEBOT_BASE_URL"):
            OneBotClient("")

    def test_strips_trailing_slash(self):
        client = OneBotClient("http://127.0.0.1:5700/")
        assert client.base_url == "http://127.0.0.1:5700"


# ---------------------------------------------------------------------------
# OneBotClient requests
# ---------------------------------------------------------------------------
class TestOneBotClientRequests:
    @responses.activate
    def test_send_private_msg_success(self):
        responses.post(
            "http://127.0.0.1:5700/send_private_msg",
            json={"status": "ok", "retcode": 0, "data": {"message_id": 1}},
            status=200,
        )
        client = OneBotClient("http://127.0.0.1:5700")
        result = client.send_private_msg(12345, "hello")
        assert result["status"] == "ok"

    @responses.activate
    def test_send_group_msg_success(self):
        responses.post(
            "http://127.0.0.1:5700/send_group_msg",
            json={"status": "ok", "retcode": 0, "data": {"message_id": 2}},
            status=200,
        )
        client = OneBotClient("http://127.0.0.1:5700")
        result = client.send_group_msg(67890, "hello group")
        assert result["status"] == "ok"

    @responses.activate
    def test_request_with_access_token(self):
        responses.post(
            "http://127.0.0.1:5700/send_private_msg",
            json={"status": "ok", "retcode": 0, "data": {}},
            status=200,
        )
        client = OneBotClient("http://127.0.0.1:5700", access_token="my_token")
        client.send_private_msg(1, "msg")
        assert responses.calls[0].request.headers["Authorization"] == "Bearer my_token"

    @responses.activate
    def test_request_failed_status(self):
        responses.post(
            "http://127.0.0.1:5700/send_private_msg",
            json={"status": "failed", "retcode": 100, "data": {}},
            status=200,
        )
        client = OneBotClient("http://127.0.0.1:5700")
        with pytest.raises(RuntimeError, match="OneBot action failed"):
            client.send_private_msg(1, "msg")

    @responses.activate
    def test_request_non_zero_retcode(self):
        responses.post(
            "http://127.0.0.1:5700/send_private_msg",
            json={"status": "ok", "retcode": 1, "data": {}},
            status=200,
        )
        client = OneBotClient("http://127.0.0.1:5700")
        with pytest.raises(RuntimeError, match="OneBot action failed"):
            client.send_private_msg(1, "msg")


# ---------------------------------------------------------------------------
# build_post_message
# ---------------------------------------------------------------------------
class TestBuildPostMessage:
    def _make_post(self, content: str = "Hello World", author_name: str = "Tester") -> QzonePost:
        return QzonePost(
            target_qq="123", author_qq="123", post_id="tid1",
            content=content, created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
            author_name=author_name,
        )

    def test_text_only(self):
        msg = build_post_message(self._make_post(), [])
        assert msg.splitlines() == [
            "123",
            "Tester",
            format_post_created_at("2025-01-01T00:00:00+00:00"),
            "Hello World",
        ]
        assert "[CQ:image" not in msg

    def test_keeps_blank_name_line_when_missing(self):
        msg = build_post_message(self._make_post(author_name=""), [])
        assert msg.splitlines() == [
            "123",
            "",
            format_post_created_at("2025-01-01T00:00:00+00:00"),
            "Hello World",
        ]

    def test_with_images(self, tmp_path: Path):
        img_file = tmp_path / "img.jpg"
        img_file.write_bytes(b"fake")
        msg = build_post_message(self._make_post(), [str(img_file)])
        lines = msg.splitlines()
        assert lines[:4] == [
            "123",
            "Tester",
            format_post_created_at("2025-01-01T00:00:00+00:00"),
            "Hello World",
        ]
        assert lines[4].startswith("[CQ:image,file=file:///")

    def test_empty_content(self):
        msg = build_post_message(self._make_post(content=""), [])
        assert msg.splitlines()[-1] == "(no text content)"


class TestFormatPostCreatedAt:
    def test_formats_local_timezone_timestamp(self):
        expected = datetime.fromisoformat("2025-01-01T00:00:00+00:00").astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        assert format_post_created_at("2025-01-01T00:00:00+00:00") == expected

    def test_invalid_timestamp_falls_back_to_original_text(self):
        assert format_post_created_at("not-a-time") == "not-a-time"
