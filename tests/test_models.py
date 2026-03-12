"""Tests for qqzone_spectator.models."""
from __future__ import annotations

from qqzone_spectator.models import MediaItem, QzonePost


class TestMediaItem:
    def test_defaults(self):
        item = MediaItem(url="https://example.com/img.jpg")
        assert item.url == "https://example.com/img.jpg"
        assert item.media_type == "image"
        assert item.local_path is None

    def test_custom_fields(self):
        item = MediaItem(url="https://x.com/a.png", media_type="video", local_path="/tmp/a.png")
        assert item.url == "https://x.com/a.png"
        assert item.media_type == "video"
        assert item.local_path == "/tmp/a.png"


class TestQzonePost:
    def test_defaults(self):
        post = QzonePost(
            target_qq="123",
            author_qq="123",
            post_id="tid_1",
            content="hello",
            created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
        )
        assert post.media == []
        assert post.target_qq == "123"
        assert post.content == "hello"

    def test_media_list_independent(self):
        """Two QzonePost instances should not share the same media list."""
        post_a = QzonePost(
            target_qq="1", author_qq="1", post_id="a",
            content="", created_at="", source_payload="{}",
        )
        post_b = QzonePost(
            target_qq="2", author_qq="2", post_id="b",
            content="", created_at="", source_payload="{}",
        )
        post_a.media.append(MediaItem(url="https://example.com/1.jpg"))
        assert len(post_b.media) == 0
