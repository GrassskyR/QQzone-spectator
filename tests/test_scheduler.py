"""Tests for qqzone_spectator.scheduler."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qqzone_spectator.config import AppConfig
from qqzone_spectator.collector.downloader import MediaDownloader
from qqzone_spectator.collector.client import QzoneAuthError, QzoneClient
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
    push_enabled: bool = False,
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
        push_enabled=push_enabled,
        push_private_users=[111] if onebot else [],
        push_groups=[222] if onebot else [],
    )

    svc = SchedulerService(
        config=config, db=db,
        qzone_client=mock_qzone, downloader=mock_downloader,
        onebot_client=onebot,
    )
    return svc, db, mock_qzone, mock_downloader


def _make_raw_post(
    post_id: str,
    target_qq: str = "123",
    *,
    created_time: int = 1704067200,
    name: str = "Tester",
) -> dict:
    return {
        "tid": post_id,
        "uin": int(target_qq),
        "name": name,
        "content": f"Post {post_id}",
        "created_time": created_time,
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

    def test_run_mode_skips_posts_published_before_session_start(self, tmp_path: Path):
        svc, db, mock_qzone, mock_dl = _make_service(tmp_path, targets=["123"])
        cutoff = int(datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        mock_qzone.fetch_posts.return_value = [
            _make_raw_post("old", created_time=cutoff - 30),
            _make_raw_post("new", created_time=cutoff + 30),
        ]
        mock_dl.download_image.return_value = None

        result = svc.crawl_once(push_enabled=False, published_after=cutoff)

        assert result["fetched"] == 2
        assert result["inserted"] == 1
        assert result["skipped_before_start"] == 1
        rows = db.conn.execute("SELECT post_id FROM posts ORDER BY id").fetchall()
        assert [row["post_id"] for row in rows] == ["new"]

    def test_run_mode_accepts_posts_published_in_same_second(self, tmp_path: Path):
        svc, db, mock_qzone, mock_dl = _make_service(tmp_path, targets=["123"])
        cutoff = int(datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        mock_qzone.fetch_posts.return_value = [
            _make_raw_post("same-second", created_time=cutoff),
            _make_raw_post("older", created_time=cutoff - 1),
        ]
        mock_dl.download_image.return_value = None

        result = svc.crawl_once(push_enabled=False, published_after=cutoff)

        assert result["inserted"] == 1
        assert result["skipped_before_start"] == 1
        rows = db.conn.execute("SELECT post_id FROM posts ORDER BY id").fetchall()
        assert [row["post_id"] for row in rows] == ["same-second"]


class TestFromConfig:
    def test_creates_onebot_client_when_push_targets_exist(self, tmp_path: Path):
        db = Database(tmp_path / "test.db")
        db.init_schema()
        config = AppConfig(
            project_root=tmp_path,
            db_path=tmp_path / "test.db",
            media_dir=tmp_path / "media",
            qzone_uin="100",
            qzone_cookie="p_skey=abc;",
            target_qqs=["123"],
            fetch_limit=20,
            poll_interval_seconds=300,
            request_timeout=10,
            onebot_base_url="http://127.0.0.1:5700",
            onebot_access_token="token",
            push_enabled=True,
            push_private_users=[111],
            push_groups=[],
        )

        with (
            patch("qqzone_spectator.scheduler.QzoneClient") as mock_qzone_cls,
            patch("qqzone_spectator.scheduler.MediaDownloader") as mock_downloader_cls,
            patch("qqzone_spectator.scheduler.OneBotClient") as mock_onebot_cls,
        ):
            svc = SchedulerService.from_config(config, db)

        mock_qzone_cls.assert_called_once_with("100", "p_skey=abc;", timeout=10)
        mock_downloader_cls.assert_called_once_with(tmp_path / "media")
        mock_onebot_cls.assert_called_once_with(
            "http://127.0.0.1:5700",
            access_token="token",
            timeout=10,
        )
        assert svc.onebot_client is mock_onebot_cls.return_value

    def test_skips_onebot_client_when_push_is_disabled(self, tmp_path: Path):
        db = Database(tmp_path / "test.db")
        db.init_schema()
        config = AppConfig(
            project_root=tmp_path,
            db_path=tmp_path / "test.db",
            media_dir=tmp_path / "media",
            qzone_uin="100",
            qzone_cookie="p_skey=abc;",
            target_qqs=["123"],
            fetch_limit=20,
            poll_interval_seconds=300,
            request_timeout=10,
            onebot_base_url="http://127.0.0.1:5700",
            onebot_access_token="token",
            push_enabled=False,
            push_private_users=[111],
            push_groups=[],
        )

        with (
            patch("qqzone_spectator.scheduler.QzoneClient"),
            patch("qqzone_spectator.scheduler.MediaDownloader"),
            patch("qqzone_spectator.scheduler.OneBotClient") as mock_onebot_cls,
        ):
            svc = SchedulerService.from_config(config, db)

        mock_onebot_cls.assert_not_called()
        assert svc.onebot_client is None

    def test_skips_onebot_client_without_push_targets(self, tmp_path: Path):
        db = Database(tmp_path / "test.db")
        db.init_schema()
        config = AppConfig(
            project_root=tmp_path,
            db_path=tmp_path / "test.db",
            media_dir=tmp_path / "media",
            qzone_uin="100",
            qzone_cookie="p_skey=abc;",
            target_qqs=["123"],
            fetch_limit=20,
            poll_interval_seconds=300,
            request_timeout=10,
            onebot_base_url="http://127.0.0.1:5700",
            onebot_access_token="token",
            push_enabled=False,
            push_private_users=[],
            push_groups=[],
        )

        with (
            patch("qqzone_spectator.scheduler.QzoneClient"),
            patch("qqzone_spectator.scheduler.MediaDownloader"),
            patch("qqzone_spectator.scheduler.OneBotClient") as mock_onebot_cls,
        ):
            svc = SchedulerService.from_config(config, db)

        mock_onebot_cls.assert_not_called()
        assert svc.onebot_client is None


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

    def test_continues_after_download_failure(self, tmp_path: Path):
        svc, db, _, mock_dl = _make_service(tmp_path, targets=["123"])
        post = QzonePost(
            target_qq="123",
            author_qq="123",
            post_id="t1",
            content="x",
            created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
            media=[
                MediaItem(url="https://img.com/a.jpg"),
                MediaItem(url="https://img.com/b.jpg"),
            ],
        )
        db.save_post(post)
        mock_dl.download_image.side_effect = [RuntimeError("boom"), "/tmp/b.jpg"]

        paths = svc._download_post_media(post)

        assert paths == ["/tmp/b.jpg"]
        assert mock_dl.download_image.call_count == 2
        row = db.conn.execute(
            "SELECT local_path FROM media WHERE media_url = ?",
            ("https://img.com/b.jpg",),
        ).fetchone()
        assert row["local_path"] == "/tmp/b.jpg"


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

    def test_returns_immediately_when_onebot_is_missing(self, tmp_path: Path):
        svc, _, _, _ = _make_service(tmp_path, targets=["123"], onebot=None)
        post = QzonePost(
            target_qq="123",
            author_qq="123",
            post_id="t1",
            content="skip push",
            created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
        )

        svc._push_post(post, [])

        rows = svc.db.conn.execute("SELECT COUNT(*) AS c FROM push_records").fetchone()
        assert rows["c"] == 0

    def test_records_private_push_failures(self, tmp_path: Path):
        mock_onebot = MagicMock(spec=OneBotClient)
        mock_onebot.send_private_msg.side_effect = RuntimeError("private failed")
        svc, db, _, _ = _make_service(tmp_path, targets=["123"], onebot=mock_onebot)
        svc.config.push_groups = []
        post = QzonePost(
            target_qq="123",
            author_qq="123",
            post_id="t1",
            content="push me",
            created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
        )

        svc._push_post(post, [])

        row = db.conn.execute(
            "SELECT status, error_message FROM push_records WHERE push_target_type = 'private'"
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] == "private failed"

    def test_records_group_push_failures(self, tmp_path: Path):
        mock_onebot = MagicMock(spec=OneBotClient)
        mock_onebot.send_group_msg.side_effect = RuntimeError("group failed")
        svc, db, _, _ = _make_service(tmp_path, targets=["123"], onebot=mock_onebot)
        svc.config.push_private_users = []
        post = QzonePost(
            target_qq="123",
            author_qq="123",
            post_id="t1",
            content="push me",
            created_at="2025-01-01T00:00:00+00:00",
            source_payload="{}",
        )

        svc._push_post(post, [])

        row = db.conn.execute(
            "SELECT status, error_message FROM push_records WHERE push_target_type = 'group'"
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] == "group failed"


class TestRunLoop:
    def test_runs_successful_cycle_then_stops(self, tmp_path: Path):
        svc, _, _, _ = _make_service(tmp_path, targets=["123"])
        svc.crawl_once = MagicMock(
            side_effect=[
                {"fetched": 1, "inserted": 1, "skipped_owner_mismatch": 0},
                KeyboardInterrupt(),
            ]
        )

        with (
            patch("qqzone_spectator.scheduler.time.sleep") as mock_sleep,
            pytest.raises(KeyboardInterrupt),
        ):
            svc.run_loop(5)

        mock_sleep.assert_called_once_with(5)

    def test_reuses_fixed_startup_second_for_each_cycle(self, tmp_path: Path):
        svc, _, _, _ = _make_service(tmp_path, targets=["123"])
        svc.crawl_once = MagicMock(
            side_effect=[
                {"fetched": 1, "inserted": 1, "skipped_before_start": 0, "skipped_owner_mismatch": 0},
                KeyboardInterrupt(),
            ]
        )
        started_at = datetime(2026, 3, 15, 17, 10, 26, 987654, tzinfo=timezone.utc)

        with (
            patch("qqzone_spectator.scheduler.datetime") as mock_datetime,
            patch("qqzone_spectator.scheduler.time.sleep") as mock_sleep,
            pytest.raises(KeyboardInterrupt),
        ):
            mock_datetime.now.return_value = started_at
            svc.run_loop(5)

        expected_cutoff = int(started_at.timestamp())
        assert svc.crawl_once.call_args_list[0].kwargs["published_after"] == expected_cutoff
        assert svc.crawl_once.call_args_list[1].kwargs["published_after"] == expected_cutoff
        mock_sleep.assert_called_once_with(5)

    def test_continues_after_cycle_failure(self, tmp_path: Path):
        svc, _, _, _ = _make_service(tmp_path, targets=["123"])
        svc.crawl_once = MagicMock(side_effect=[RuntimeError("boom"), KeyboardInterrupt()])

        with (
            patch("qqzone_spectator.scheduler.time.sleep") as mock_sleep,
            pytest.raises(KeyboardInterrupt),
        ):
            svc.run_loop(9)

        mock_sleep.assert_called_once_with(9)

    def test_stops_when_cookie_is_expired(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        svc, _, _, _ = _make_service(tmp_path, targets=["123"])
        svc.crawl_once = MagicMock(side_effect=QzoneAuthError(-3000, "请先登录空间"))

        with patch("qqzone_spectator.scheduler.time.sleep") as mock_sleep:
            svc.run_loop(15)

        mock_sleep.assert_not_called()
        assert "QZONE_COOKIE may be expired" in caplog.text
