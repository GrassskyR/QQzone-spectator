"""Shared test fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qqzone_spectator.config import AppConfig
from qqzone_spectator.db import Database
from qqzone_spectator.models import MediaItem, QzonePost


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Database:
    """Return a Database backed by a temporary SQLite file with schema initialised."""
    db = Database(tmp_path / "test.db")
    db.init_schema()
    return db


@pytest.fixture()
def sample_post() -> QzonePost:
    """Return a minimal QzonePost instance for testing."""
    return QzonePost(
        target_qq="123456",
        author_qq="123456",
        post_id="tid_001",
        content="Hello QZone",
        created_at="2025-01-01T00:00:00+00:00",
        source_payload=json.dumps({"tid": "tid_001", "uin": 123456, "content": "Hello QZone"}),
        author_name="Tester",
        media=[
            MediaItem(url="https://example.com/img1.jpg"),
            MediaItem(url="https://example.com/img2.png"),
        ],
    )


@pytest.fixture()
def sample_raw_post() -> dict:
    """Return a raw dict mimicking a QZone API response post."""
    return {
        "tid": "tid_001",
        "uin": 123456,
        "name": "Tester",
        "content": "Hello QZone",
        "created_time": 1704067200,  # 2024-01-01T00:00:00Z
        "pic": [
            {"url1": "https://example.com/img1.jpg"},
            {"url2": "https://example.com/img2.png"},
        ],
    }


@pytest.fixture()
def mock_config(tmp_path: Path) -> AppConfig:
    """Return an AppConfig with all fields set to test values."""
    return AppConfig(
        project_root=tmp_path,
        db_path=tmp_path / "data" / "test.db",
        media_dir=tmp_path / "data" / "media",
        qzone_uin="100000",
        qzone_cookie="uin=o100000; p_skey=test_skey_value;",
        target_qqs=["123456", "654321"],
        fetch_limit=20,
        poll_interval_seconds=300,
        request_timeout=10,
        onebot_base_url="http://127.0.0.1:5700",
        onebot_access_token="test_token",
        push_private_users=[111111],
        push_groups=[222222],
    )
