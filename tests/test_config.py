"""Tests for qqzone_spectator.config."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qqzone_spectator.config import AppConfig, _parse_csv, _parse_csv_int


# ---------------------------------------------------------------------------
# _parse_csv
# ---------------------------------------------------------------------------

class TestParseCsv:
    def test_normal(self):
        assert _parse_csv("a, b, c") == ["a", "b", "c"]

    def test_empty(self):
        assert _parse_csv("") == []

    def test_strips_whitespace(self):
        assert _parse_csv("  x , y  ") == ["x", "y"]

    def test_skips_blank_items(self):
        assert _parse_csv("a,,b, ,c") == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# _parse_csv_int
# ---------------------------------------------------------------------------

class TestParseCsvInt:
    def test_normal(self):
        assert _parse_csv_int("1,2,3") == [1, 2, 3]

    def test_skips_non_numeric(self):
        assert _parse_csv_int("1,abc,3") == [1, 3]

    def test_empty(self):
        assert _parse_csv_int("") == []


# ---------------------------------------------------------------------------
# AppConfig.from_env
# ---------------------------------------------------------------------------

class TestAppConfig:
    def test_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("QZONE_UIN", "999")
        monkeypatch.setenv("QZONE_COOKIE", "uin=o999; p_skey=abc;")
        monkeypatch.setenv("TARGET_QQS", "111,222")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
        monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
        monkeypatch.setenv("FETCH_LIMIT", "50")
        monkeypatch.setenv("POLL_INTERVAL_SECONDS", "600")
        monkeypatch.setenv("REQUEST_TIMEOUT", "15")
        monkeypatch.setenv("ONEBOT_BASE_URL", "http://localhost:5700/")
        monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("PUSH_PRIVATE_USERS", "333")
        monkeypatch.setenv("PUSH_GROUPS", "444,555")

        cfg = AppConfig.from_env(env_file=None)

        assert cfg.qzone_uin == "999"
        assert cfg.qzone_cookie == "uin=o999; p_skey=abc;"
        assert cfg.target_qqs == ["111", "222"]
        assert cfg.fetch_limit == 50
        assert cfg.poll_interval_seconds == 600
        assert cfg.request_timeout == 15
        assert cfg.onebot_base_url == "http://localhost:5700"
        assert cfg.onebot_access_token == "tok"
        assert cfg.push_private_users == [333]
        assert cfg.push_groups == [444, 555]

    def test_fetch_limit_minimum(self, monkeypatch):
        monkeypatch.setenv("FETCH_LIMIT", "0")
        monkeypatch.setenv("QZONE_UIN", "1")
        monkeypatch.setenv("QZONE_COOKIE", "x")
        cfg = AppConfig.from_env(env_file=None)
        assert cfg.fetch_limit == 1

    def test_poll_interval_minimum(self, monkeypatch):
        monkeypatch.setenv("POLL_INTERVAL_SECONDS", "10")
        monkeypatch.setenv("QZONE_UIN", "1")
        monkeypatch.setenv("QZONE_COOKIE", "x")
        cfg = AppConfig.from_env(env_file=None)
        assert cfg.poll_interval_seconds == 30

    def test_request_timeout_minimum(self, monkeypatch):
        monkeypatch.setenv("REQUEST_TIMEOUT", "1")
        monkeypatch.setenv("QZONE_UIN", "1")
        monkeypatch.setenv("QZONE_COOKIE", "x")
        cfg = AppConfig.from_env(env_file=None)
        assert cfg.request_timeout == 5

    def test_ensure_directories(self, tmp_path):
        cfg = AppConfig(
            project_root=tmp_path,
            db_path=tmp_path / "sub" / "db.sqlite",
            media_dir=tmp_path / "m" / "imgs",
            qzone_uin="1", qzone_cookie="x", target_qqs=[],
            fetch_limit=20, poll_interval_seconds=300, request_timeout=20,
            onebot_base_url="", onebot_access_token="",
            push_private_users=[], push_groups=[],
        )
        cfg.ensure_directories()
        assert (tmp_path / "sub").is_dir()
        assert (tmp_path / "m" / "imgs").is_dir()
