"""Tests for qqzone_spectator.push.onebot."""
from __future__ import annotations

from pathlib import Path

import pytest
import responses

from qqzone_spectator.models import MediaItem, QzonePost
from qqzone_spectator.push.onebot import OneBotClient, build_post_message


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
    def _make_post(self, content: str = "Hello World") -> QzonePost:
        return QzonePost(
            target_qq="123", author_qq="123", post_id="tid1",
            content=content, created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
        )

    def test_text_only(self):
        msg = build_post_message(self._make_post(), [])
        assert "[QQZone] target=123" in msg
        assert "post=tid1" in msg
        assert "Hello World" in msg
        assert "[CQ:image" not in msg

    def test_with_images(self, tmp_path: Path):
        img_file = tmp_path / "img.jpg"
        img_file.write_bytes(b"fake")
        msg = build_post_message(self._make_post(), [str(img_file)])
        assert "[CQ:image,file=" in msg
        assert "file:///" in msg

    def test_empty_content(self):
        msg = build_post_message(self._make_post(content=""), [])
        assert "(no text content)" in msg
