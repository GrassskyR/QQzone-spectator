"""Tests for qqzone_spectator.collector.parser."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from qqzone_spectator.collector.parser import (
    _extract_content,
    _extract_created_at,
    _extract_media,
    _extract_media_url,
    _extract_post_id,
    _normalize_time,
    extract_author_qq,
    parse_posts,
)
from qqzone_spectator.models import QzonePost


# ---------------------------------------------------------------------------
# parse_posts
# ---------------------------------------------------------------------------

class TestParsePosts:
    def test_basic(self, sample_raw_post):
        posts = parse_posts("123456", [sample_raw_post])
        assert len(posts) == 1
        assert isinstance(posts[0], QzonePost)
        assert posts[0].target_qq == "123456"
        assert posts[0].post_id == "tid_001"
        assert posts[0].author_name == ""
        assert posts[0].content == "Hello QZone"

    def test_sorted_by_time(self):
        raw_early = {"tid": "a", "created_time": 1000000000, "content": "early"}
        raw_late = {"tid": "b", "created_time": 1700000000, "content": "late"}
        posts = parse_posts("1", [raw_late, raw_early])
        assert posts[0].post_id == "a"
        assert posts[1].post_id == "b"

    def test_empty_list(self):
        assert parse_posts("1", []) == []


# ---------------------------------------------------------------------------
# extract_author_qq
# ---------------------------------------------------------------------------

class TestExtractAuthorQQ:
    def test_uin(self):
        assert extract_author_qq({"uin": "12345"}) == "12345"

    def test_opuin(self):
        assert extract_author_qq({"opuin": 12345}) == "12345"

    def test_from_userinfo_dict(self):
        raw = {"userinfo": {"uin": 99999}}
        assert extract_author_qq(raw) == "99999"

    def test_from_userinfo_list(self):
        raw = {"userInfo": [{"uin": 88888}]}
        assert extract_author_qq(raw) == "88888"

    def test_fallback_default(self):
        assert extract_author_qq({}, default_target_qq="77777") == "77777"
# ---------------------------------------------------------------------------
# _normalize_qq (tested via extract_author_qq)
# ---------------------------------------------------------------------------

class TestNormalizeQQ:
    """Test _normalize_qq indirectly through extract_author_qq."""

    def test_int_value(self):
        assert extract_author_qq({"uin": 12345}) == "12345"

    def test_float_value(self):
        assert extract_author_qq({"uin": 12345.0}) == "12345"

    def test_negative(self):
        assert extract_author_qq({"uin": -1}, default_target_qq="fallback") == "fallback"

    def test_string_digits(self):
        assert extract_author_qq({"uin": "12345"}) == "12345"

    def test_string_mixed(self):
        assert extract_author_qq({"uin": "qq12345abc"}) == "12345"

    def test_none(self):
        assert extract_author_qq({"uin": None}, default_target_qq="fb") == "fb"


# ---------------------------------------------------------------------------
# _extract_post_id
# ---------------------------------------------------------------------------

class TestExtractPostId:
    def test_tid(self):
        assert _extract_post_id({"tid": "abc"}) == "abc"

    def test_fallback_sha1(self):
        raw = {"some_key": "some_value"}
        expected_digest = hashlib.sha1(
            json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:20]
        assert _extract_post_id(raw) == expected_digest


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------

class TestExtractContent:
    def test_string(self):
        assert _extract_content({"content": "hello"}) == "hello"

    def test_summary_string(self):
        assert _extract_content({"summary": "world"}) == "world"

    def test_summary_dict(self):
        assert _extract_content({"summary": {"content": "nested"}}) == "nested"

    def test_empty(self):
        assert _extract_content({}) == ""


# ---------------------------------------------------------------------------
# _extract_created_at
# ---------------------------------------------------------------------------

class TestExtractCreatedAt:
    def test_timestamp(self):
        result = _extract_created_at({"created_time": 1704067200})
        expected = datetime.fromtimestamp(1704067200, tz=timezone.utc).isoformat()
        assert result == expected

    def test_iso_string(self):
        raw = {"created_time": "2024-01-01T00:00:00Z"}
        result = _extract_created_at(raw)
        assert "2024-01-01" in result


# ---------------------------------------------------------------------------
# _extract_media / _extract_media_url
# ---------------------------------------------------------------------------

class TestExtractMedia:
    def test_from_pics(self):
        raw = {"pic": [{"url1": "https://example.com/1.jpg"}]}
        items = _extract_media(raw)
        assert len(items) == 1
        assert items[0].url == "https://example.com/1.jpg"

    def test_dedup(self):
        raw = {
            "pic": [
                {"url1": "https://example.com/1.jpg"},
                {"url1": "https://example.com/1.jpg"},
            ]
        }
        items = _extract_media(raw)
        assert len(items) == 1

    def test_multiple_sources(self):
        raw = {
            "pic": [{"url1": "https://a.com/1.jpg"}],
            "photos": [{"url2": "https://b.com/2.jpg"}],
        }
        items = _extract_media(raw)
        assert len(items) == 2

    def test_string_item(self):
        """If a list item is a plain string URL."""
        raw = {"pic": ["https://example.com/3.jpg"]}
        items = _extract_media(raw)
        assert len(items) == 1

    def test_media_url_empty(self):
        assert _extract_media_url({}) == ""
        assert _extract_media_url("") == ""
