"""Tests for qqzone_spectator.db."""
from __future__ import annotations

import json

import pytest

from qqzone_spectator.db import (
    Database,
    _extract_author_from_user_info,
    _extract_author_qq_from_payload,
    _normalize_qq,
)
from qqzone_spectator.models import MediaItem, QzonePost


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_init_schema_creates_tables(self, tmp_db: Database):
        tables = tmp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {row["name"] for row in tables}
        assert "posts" in names
        assert "media" in names
        assert "targets" in names
        assert "crawl_runs" in names
        assert "push_records" in names


# ---------------------------------------------------------------------------
# upsert_targets / list_targets
# ---------------------------------------------------------------------------

class TestTargets:
    def test_upsert_insert(self, tmp_db: Database):
        tmp_db.upsert_targets(["111", "222"])
        assert tmp_db.list_targets() == ["111", "222"]

    def test_upsert_remove_old(self, tmp_db: Database):
        tmp_db.upsert_targets(["111", "222"])
        tmp_db.upsert_targets(["222", "333"])
        assert tmp_db.list_targets() == ["222", "333"]

    def test_upsert_empty(self, tmp_db: Database):
        tmp_db.upsert_targets(["111"])
        tmp_db.upsert_targets([])
        assert tmp_db.list_targets() == []

    def test_upsert_dedup_and_strip(self, tmp_db: Database):
        tmp_db.upsert_targets([" 123 ", "123", " 123"])
        assert tmp_db.list_targets() == ["123"]

    def test_list_targets_sorted(self, tmp_db: Database):
        tmp_db.upsert_targets(["333", "111", "222"])
        assert tmp_db.list_targets() == ["111", "222", "333"]


# ---------------------------------------------------------------------------
# crawl_runs
# ---------------------------------------------------------------------------

class TestCrawlRuns:
    def test_record_crawl_start(self, tmp_db: Database):
        run_id = tmp_db.record_crawl_start()
        assert isinstance(run_id, int)
        assert run_id > 0

    def test_record_crawl_finish_success(self, tmp_db: Database):
        run_id = tmp_db.record_crawl_start()
        tmp_db.record_crawl_finish(
            run_id, status="success", fetched_posts=10,
            inserted_posts=5, error_message=None,
        )
        row = tmp_db.conn.execute(
            "SELECT * FROM crawl_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["status"] == "success"
        assert row["fetched_posts"] == 10
        assert row["inserted_posts"] == 5
        assert row["finished_at"] is not None

    def test_record_crawl_finish_failed(self, tmp_db: Database):
        run_id = tmp_db.record_crawl_start()
        tmp_db.record_crawl_finish(
            run_id, status="failed", fetched_posts=3,
            inserted_posts=0, error_message="timeout",
        )
        row = tmp_db.conn.execute(
            "SELECT * FROM crawl_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] == "timeout"


# ---------------------------------------------------------------------------
# save_post
# ---------------------------------------------------------------------------

class TestSavePost:
    def _make_post(self, target_qq="123", post_id="tid_1", author_qq="123") -> QzonePost:
        return QzonePost(
            target_qq=target_qq,
            author_qq=author_qq,
            post_id=post_id,
            content="test",
            created_at="2025-01-01T00:00:00+00:00",
            source_payload=json.dumps({"tid": post_id, "uin": int(author_qq)}),
            media=[MediaItem(url="https://example.com/1.jpg")],
        )

    def test_save_post_new(self, tmp_db: Database):
        post = self._make_post()
        assert tmp_db.save_post(post) is True
        row = tmp_db.conn.execute("SELECT * FROM posts WHERE post_id = 'tid_1'").fetchone()
        assert row is not None
        assert row["content"] == "test"

    def test_save_post_duplicate(self, tmp_db: Database):
        post = self._make_post()
        assert tmp_db.save_post(post) is True
        assert tmp_db.save_post(post) is False

    def test_save_post_with_media(self, tmp_db: Database):
        post = self._make_post()
        tmp_db.save_post(post)
        rows = tmp_db.conn.execute("SELECT * FROM media").fetchall()
        assert len(rows) == 1
        assert rows[0]["media_url"] == "https://example.com/1.jpg"


# ---------------------------------------------------------------------------
# update_media_local_path
# ---------------------------------------------------------------------------

class TestUpdateMediaLocalPath:
    def test_update(self, tmp_db: Database):
        post = QzonePost(
            target_qq="123", author_qq="123", post_id="tid_1",
            content="", created_at="", source_payload="{}",
            media=[MediaItem(url="https://example.com/1.jpg")],
        )
        tmp_db.save_post(post)
        tmp_db.update_media_local_path("123", "tid_1", "https://example.com/1.jpg", "/tmp/1.jpg")
        row = tmp_db.conn.execute("SELECT local_path FROM media WHERE post_id = 'tid_1'").fetchone()
        assert row["local_path"] == "/tmp/1.jpg"


# ---------------------------------------------------------------------------
# push_records
# ---------------------------------------------------------------------------

class TestPushRecords:
    def test_has_success_push_record_true(self, tmp_db: Database):
        tmp_db.record_push_result(
            target_qq="123", post_id="tid_1",
            push_target_type="private", push_target_id="999",
            status="success", error_message=None,
        )
        assert tmp_db.has_success_push_record("123", "tid_1", "private", "999") is True

    def test_has_success_push_record_false(self, tmp_db: Database):
        assert tmp_db.has_success_push_record("123", "tid_1", "private", "999") is False

    def test_has_success_push_record_failed_status(self, tmp_db: Database):
        tmp_db.record_push_result(
            target_qq="123", post_id="tid_1",
            push_target_type="private", push_target_id="999",
            status="failed", error_message="err",
        )
        assert tmp_db.has_success_push_record("123", "tid_1", "private", "999") is False

    def test_record_push_result_insert(self, tmp_db: Database):
        tmp_db.record_push_result(
            target_qq="123", post_id="tid_1",
            push_target_type="group", push_target_id="888",
            status="success", error_message=None,
        )
        row = tmp_db.conn.execute("SELECT * FROM push_records").fetchone()
        assert row["status"] == "success"

    def test_record_push_result_upsert(self, tmp_db: Database):
        tmp_db.record_push_result(
            target_qq="123", post_id="tid_1",
            push_target_type="group", push_target_id="888",
            status="failed", error_message="err",
        )
        tmp_db.record_push_result(
            target_qq="123", post_id="tid_1",
            push_target_type="group", push_target_id="888",
            status="success", error_message=None,
        )
        rows = tmp_db.conn.execute("SELECT * FROM push_records").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "success"


# ---------------------------------------------------------------------------
# purge_owner_mismatch_posts
# ---------------------------------------------------------------------------

class TestPurgeOwnerMismatch:
    def test_purge(self, tmp_db: Database):
        # author != target => should be purged
        mismatch = QzonePost(
            target_qq="123", author_qq="999", post_id="tid_m",
            content="mismatch", created_at="", source_payload="{}",
        )
        ok = QzonePost(
            target_qq="123", author_qq="123", post_id="tid_ok",
            content="ok", created_at="", source_payload="{}",
        )
        tmp_db.save_post(mismatch)
        tmp_db.save_post(ok)
        total = tmp_db.purge_owner_mismatch_posts()
        assert total == 1
        rows = tmp_db.conn.execute("SELECT post_id FROM posts").fetchall()
        assert [row["post_id"] for row in rows] == ["tid_ok"]

    def test_purge_cascades_media_and_push(self, tmp_db: Database):
        mismatch = QzonePost(
            target_qq="123", author_qq="999", post_id="tid_m",
            content="m", created_at="", source_payload="{}",
            media=[MediaItem(url="https://example.com/x.jpg")],
        )
        tmp_db.save_post(mismatch)
        tmp_db.record_push_result(
            target_qq="123", post_id="tid_m",
            push_target_type="private", push_target_id="111",
            status="success", error_message=None,
        )
        tmp_db.purge_owner_mismatch_posts()
        assert tmp_db.conn.execute("SELECT COUNT(*) AS c FROM media").fetchone()["c"] == 0
        assert tmp_db.conn.execute("SELECT COUNT(*) AS c FROM push_records").fetchone()["c"] == 0


# ---------------------------------------------------------------------------
# Helper functions in db.py
# ---------------------------------------------------------------------------

class TestDbHelpers:
    def test_extract_author_qq_from_payload(self):
        payload = json.dumps({"uin": 12345})
        assert _extract_author_qq_from_payload(payload) == "12345"

    def test_extract_author_qq_from_payload_invalid_json(self):
        assert _extract_author_qq_from_payload("not json") == ""

    def test_extract_author_qq_from_payload_user_info(self):
        payload = json.dumps({"userinfo": {"uin": 99999}})
        assert _extract_author_qq_from_payload(payload) == "99999"

    def test_normalize_qq_int(self):
        assert _normalize_qq(12345) == "12345"

    def test_normalize_qq_negative(self):
        assert _normalize_qq(-1) == ""

    def test_normalize_qq_string(self):
        assert _normalize_qq("54321") == "54321"

    def test_normalize_qq_none(self):
        assert _normalize_qq(None) == ""

    def test_extract_author_from_user_info_dict(self):
        assert _extract_author_from_user_info({"uin": 111}) == "111"

    def test_extract_author_from_user_info_list(self):
        assert _extract_author_from_user_info([{"uin": 222}]) == "222"

    def test_extract_author_from_user_info_none(self):
        assert _extract_author_from_user_info(None) == ""
