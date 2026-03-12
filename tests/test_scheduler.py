"""Tests for qqzone_spectator.scheduler."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qqzone_spectator.config import AppConfig
from qqzone_spectator.collector.downloader import MediaDownloader
from qqzone_spectator.collector.client import QzoneClient
from qqzone_spectator.db import Database
from qqzone_spectator.models import MediaItem, QzonePost
from qqzone_spectator.push.onebot import OneBotClient
from qqzone_spectator.scheduler import SchedulerService, build_content_preview


# ---------------------------------------------------------------------------
# build_content_preview
# ---------------------------------------------------------------------------
class TestBuildContentPreview:
    def test_short(self):
        assert build_content_preview("hello world") == "hello world"

    def test_long(self):
        long_text = "a" * 100
        result = build_content_preview(long_text, max_length=60)
        assert len(result) == 60
        assert result.endswith("...")

    def test_empty(self):
        assert build_content_preview("") == "(no text content)"

    def test_whitespace_normalized(self):
        assert build_content_preview("  hello   world  ") == "hello world"

    def test_custom_max_length(self):
        result = build_content_preview("abcdefgh", max_length=5)
        assert result == "ab..."


# ---------------------------------------------------------------------------
# SchedulerService helpers
# ---------------------------------------------------------------------------
def _make_service(
    tmp_path: Path,
    *,
    targets: list[str] | None = None,
    onebot: OneBotClient | None = None,
) -> tuple[SchedulerService, Database, MagicMock, MagicMock]:
    """Create a SchedulerService with mocked QzoneClient and MediaDownloader."""
    db = Database(tmp_path / "test.db")
    db.init_schema()
    if targets:
        db.upsert_targets(targets)

    mock_qzone = MagicMock(spec=QzoneClient)
    mock_downloader = MagicMock(spec=MediaDownloader)

    config = AppConfig(
        project_root=tmp_path,
        db_path=tmp_path / "test.db",
        media_dir=tmp_path / "media",
        qzone_uin="100", qzone_cookie="p_skey=abc;",
        target_qqs=targets or [],
        fetch_limit=20, poll_interval_seconds=300, request_timeout=10,
        onebot_base_url="http://127.0.0.1:5700" if onebot else "",
        onebot_access_token="",
        push_private_users=[111] if onebot else [],
        push_groups=[222] if onebot else [],
    )

    svc = SchedulerService(
        config=config, db=db,
        qzone_client=mock_qzone, downloader=mock_downloader,
        onebot_client=onebot,
    )
    return svc, db, mock_qzone, mock_downloader


def _make_raw_post(post_id: str, target_qq: str = "123") -> dict:
    return {
        "tid": post_id,
        "uin": int(target_qq),
        "content": f"Post {post_id}",
        "created_time": 1704067200,
    }


# ---------------------------------------------------------------------------
# crawl_once
# ---------------------------------------------------------------------------
class TestCrawlOnce:
    def test_no_targets(self, tmp_path: Path):
        svc, db, _, _ = _make_service(tmp_path, targets=[])
        with pytest.raises(RuntimeError, match="No target QQ"):
            svc.crawl_once()

    def test_new_posts(self, tmp_path: Path):
        svc, db, mock_qzone, mock_dl = _make_service(tmp_path, targets=["123"])
        mock_qzone.fetch_posts.return_value = [
            _make_raw_post("t1"), _make_raw_post("t2"),
        ]
        mock_dl.download_image.return_value = None

        result = svc.crawl_once(push_enabled=False)
        assert result["fetched"] == 2
        assert result["inserted"] == 2

    def test_duplicate_posts(self, tmp_path: Path):
        svc, db, mock_qzone, mock_dl = _make_service(tmp_path, targets=["123"])
        raw = [_make_raw_post("t1")]
        mock_qzone.fetch_posts.return_value = raw
        mock_dl.download_image.return_value = None

        svc.crawl_once(push_enabled=False)
        # Second crawl returns same post
        mock_qzone.fetch_posts.return_value = raw
        result = svc.crawl_once(push_enabled=False)
        assert result["inserted"] == 0

    def test_owner_mismatch_skip(self, tmp_path: Path):
        svc, db, mock_qzone, _ = _make_service(tmp_path, targets=["123"])
        raw = {"tid": "t1", "uin": 999, "content": "other's post", "created_time": 1704067200}
        mock_qzone.fetch_posts.return_value = [raw]

        result = svc.crawl_once(push_enabled=False)
        assert result["skipped_owner_mismatch"] == 1
        assert result["inserted"] == 0

    def test_exception_records_failure(self, tmp_path: Path):
        svc, db, mock_qzone, _ = _make_service(tmp_path, targets=["123"])
        mock_qzone.fetch_posts.side_effect = RuntimeError("network error")

        with pytest.raises(RuntimeError, match="network error"):
            svc.crawl_once()

        row = db.conn.execute("SELECT * FROM crawl_runs").fetchone()
        assert row["status"] == "failed"
        assert "network error" in row["error_message"]


# ---------------------------------------------------------------------------
# _download_post_media
# ---------------------------------------------------------------------------
class TestDownloadPostMedia:
    def test_downloads_and_updates_db(self, tmp_path: Path):
        svc, db, _, mock_dl = _make_service(tmp_path, targets=["123"])
        post = QzonePost(
            target_qq="123", author_qq="123", post_id="t1",
            content="x", created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}", media=[MediaItem(url="https://img.com/a.jpg")],
        )
        db.save_post(post)
        mock_dl.download_image.return_value = "/tmp/a.jpg"

        paths = svc._download_post_media(post)
        assert paths == ["/tmp/a.jpg"]

        row = db.conn.execute(
            "SELECT local_path FROM media WHERE media_url = ?",
            ("https://img.com/a.jpg",),
        ).fetchone()
        assert row["local_path"] == "/tmp/a.jpg"


# ---------------------------------------------------------------------------
# _push_post
# ---------------------------------------------------------------------------
class TestPushPost:
    def test_push_private_and_group(self, tmp_path: Path):
        mock_onebot = MagicMock(spec=OneBotClient)
        svc, db, _, _ = _make_service(tmp_path, targets=["123"], onebot=mock_onebot)

        post = QzonePost(
            target_qq="123", author_qq="123", post_id="t1",
            content="push me", created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
        )
        svc._push_post(post, [])

        mock_onebot.send_private_msg.assert_called_once()
        mock_onebot.send_group_msg.assert_called_once()

    def test_skip_already_pushed(self, tmp_path: Path):
        mock_onebot = MagicMock(spec=OneBotClient)
        svc, db, _, _ = _make_service(tmp_path, targets=["123"], onebot=mock_onebot)

        # Record existing success
        db.record_push_result(
            target_qq="123", post_id="t1", push_target_type="private",
            push_target_id="111", status="success", error_message=None,
        )
        db.record_push_result(
            target_qq="123", post_id="t1", push_target_type="group",
            push_target_id="222", status="success", error_message=None,
        )

        post = QzonePost(
            target_qq="123", author_qq="123", post_id="t1",
            content="skip me", created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
        )
        svc._push_post(post, [])

        mock_onebot.send_private_msg.assert_not_called()
        mock_onebot.send_group_msg.assert_not_called()
