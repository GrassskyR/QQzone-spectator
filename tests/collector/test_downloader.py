"""Tests for qqzone_spectator.collector.downloader."""
from __future__ import annotations

from pathlib import Path

import pytest
import responses

from qqzone_spectator.collector.downloader import MediaDownloader, sanitize


# ---------------------------------------------------------------------------
# sanitize
# ---------------------------------------------------------------------------

class TestSanitize:
    def test_normal(self):
        assert sanitize("hello.jpg") == "hello.jpg"

    def test_special_chars(self):
        result = sanitize("a/b:c*d")
        assert "/" not in result
        assert ":" not in result
        assert "*" not in result

    def test_long_string(self):
        long = "a" * 200
        assert len(sanitize(long)) == 96

    def test_empty(self):
        assert sanitize("") == "unknown"


# ---------------------------------------------------------------------------
# MediaDownloader
# ---------------------------------------------------------------------------

class TestMediaDownloader:
    def test_creates_media_dir(self, tmp_path):
        media_dir = tmp_path / "new_dir" / "media"
        MediaDownloader(media_dir)
        assert media_dir.is_dir()

    @responses.activate
    def test_download_image_success(self, tmp_path):
        url = "https://example.com/photo.jpg"
        responses.get(url, body=b"\xff\xd8\xff\xe0fake_jpeg", status=200)

        dl = MediaDownloader(tmp_path / "media")
        result = dl.download_image(
            media_url=url, target_qq="123", post_id="tid_1", index=1,
        )

        assert result is not None
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_download_image_skip_existing(self, tmp_path):
        dl = MediaDownloader(tmp_path / "media")
        target_dir = tmp_path / "media" / "123"
        target_dir.mkdir(parents=True)
        existing = target_dir / "tid_1_01.jpg"
        existing.write_bytes(b"existing_content")

        result = dl.download_image(
            media_url="https://example.com/photo.jpg",
            target_qq="123",
            post_id="tid_1",
            index=1,
        )

        assert result is not None
        assert Path(result).read_bytes() == b"existing_content"

    def test_download_image_empty_url(self, tmp_path):
        dl = MediaDownloader(tmp_path / "media")
        result = dl.download_image(
            media_url="", target_qq="123", post_id="tid_1", index=1,
        )
        assert result is None

    @responses.activate
    def test_download_image_unknown_ext(self, tmp_path):
        url = "https://example.com/photo.xyz"
        responses.get(url, body=b"data", status=200)

        dl = MediaDownloader(tmp_path / "media")
        result = dl.download_image(
            media_url=url, target_qq="123", post_id="tid_1", index=1,
        )

        assert result is not None
        assert result.endswith(".jpg")

    @responses.activate
    def test_download_image_http_error(self, tmp_path):
        url = "https://example.com/photo.jpg"
        responses.get(url, body="Not Found", status=404)

        dl = MediaDownloader(tmp_path / "media")
        with pytest.raises(Exception):
            dl.download_image(
                media_url=url, target_qq="123", post_id="tid_1", index=1,
            )
