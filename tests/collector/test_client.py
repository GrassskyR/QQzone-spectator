"""Tests for qqzone_spectator.collector.client."""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
import responses

from qqzone_spectator.collector.client import (
    MAX_PAGE_SIZE,
    QZONE_MSG_LIST_ENDPOINT,
    QzoneAPIError,
    QzoneClient,
    cookie_value,
    hash33,
)


# ---------------------------------------------------------------------------
# hash33
# ---------------------------------------------------------------------------

class TestHash33:
    def test_known_value(self):
        result = hash33("@abc")
        assert isinstance(result, int)
        assert result >= 0

    def test_empty_string(self):
        assert hash33("") == 5381

    def test_deterministic(self):
        assert hash33("test_skey") == hash33("test_skey")


# ---------------------------------------------------------------------------
# cookie_value
# ---------------------------------------------------------------------------

class TestCookieValue:
    def test_found(self):
        cookie = "uin=o123; p_skey=ABCDEF; skey=xyz;"
        assert cookie_value(cookie, "p_skey") == "ABCDEF"

    def test_not_found(self):
        cookie = "uin=o123; skey=xyz;"
        assert cookie_value(cookie, "p_skey") == ""

    def test_edge_trailing_semicolon(self):
        cookie = "p_skey=value123;"
        assert cookie_value(cookie, "p_skey") == "value123"

    def test_extra_spaces(self):
        cookie = "  p_skey = hello ; skey=world"
        assert cookie_value(cookie, "p_skey") == "hello"


# ---------------------------------------------------------------------------
# QzoneClient.__init__
# ---------------------------------------------------------------------------

class TestQzoneClientInit:
    def test_valid(self):
        client = QzoneClient("12345", "uin=o12345; p_skey=abc;")
        assert client.uin == "12345"
        assert isinstance(client.g_tk, int)

    def test_empty_uin(self):
        with pytest.raises(ValueError, match="QZONE_UIN"):
            QzoneClient("", "uin=o12345; p_skey=abc;")

    def test_empty_cookie(self):
        with pytest.raises(ValueError, match="QZONE_COOKIE"):
            QzoneClient("12345", "")

    def test_no_skey(self):
        with pytest.raises(ValueError, match="p_skey or skey"):
            QzoneClient("12345", "uin=o12345; other=value;")


# ---------------------------------------------------------------------------
# _decode_payload (static)
# ---------------------------------------------------------------------------

class TestDecodePayload:
    def test_pure_json(self):
        result = QzoneClient._decode_payload('{"code": 0, "msglist": []}')
        assert result == {"code": 0, "msglist": []}

    def test_jsonp(self):
        raw = '_preloadCallback({"code":0,"data":1})'
        result = QzoneClient._decode_payload(raw)
        assert result == {"code": 0, "data": 1}

    def test_no_json(self):
        with pytest.raises(ValueError, match="does not contain JSON"):
            QzoneClient._decode_payload("no json here")

    def test_non_dict(self):
        with pytest.raises(ValueError, match="does not contain JSON"):
            QzoneClient._decode_payload("[1, 2, 3]")


# ---------------------------------------------------------------------------
# _safe_int (static)
# ---------------------------------------------------------------------------

class TestSafeInt:
    def test_int(self):
        assert QzoneClient._safe_int(42) == 42

    def test_str(self):
        assert QzoneClient._safe_int("42") == 42

    def test_none(self):
        assert QzoneClient._safe_int(None) is None

    def test_non_numeric_str(self):
        assert QzoneClient._safe_int("abc") is None


# ---------------------------------------------------------------------------
# _dedupe_key (static)
# ---------------------------------------------------------------------------

class TestDedupeKey:
    def test_tid(self):
        assert QzoneClient._dedupe_key({"tid": "abc"}) == "abc"

    def test_empty(self):
        assert QzoneClient._dedupe_key({"foo": "bar"}) == ""

    def test_priority(self):
        # tid has higher priority than id
        assert QzoneClient._dedupe_key({"id": "x", "tid": "y"}) == "y"


# ---------------------------------------------------------------------------
# fetch_posts (integration with mocked HTTP)
# ---------------------------------------------------------------------------

class TestFetchPosts:
    @responses.activate
    def test_success(self):
        payload = {"code": 0, "msglist": [{"tid": "t1"}, {"tid": "t2"}], "total": 2}
        body = f"_preloadCallback({json.dumps(payload)})"
        responses.get(QZONE_MSG_LIST_ENDPOINT, body=body, status=200)

        client = QzoneClient("100", "uin=o100; p_skey=skey123;")
        posts = client.fetch_posts("200", num=2)

        assert len(posts) == 2
        assert posts[0]["tid"] == "t1"

    @responses.activate
    def test_api_error_retries(self):
        error_payload = {"code": -10000, "message": "server busy"}
        error_body = f"_preloadCallback({json.dumps(error_payload)})"

        ok_payload = {"code": 0, "msglist": [{"tid": "t1"}], "total": 1}
        ok_body = f"_preloadCallback({json.dumps(ok_payload)})"

        responses.get(QZONE_MSG_LIST_ENDPOINT, body=error_body, status=200)
        responses.get(QZONE_MSG_LIST_ENDPOINT, body=ok_body, status=200)

        client = QzoneClient("100", "uin=o100; p_skey=skey123;")
        with patch("qqzone_spectator.collector.client.time.sleep"):
            posts = client.fetch_posts("200", num=1)

        assert len(posts) == 1
