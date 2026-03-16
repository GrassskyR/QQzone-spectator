"""Tests for qqzone_spectator.collector.client."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import requests
import responses

from qqzone_spectator.collector.client import (
    MAX_PAGE_SIZE,
    QZONE_FEEDS_HTML_MODULE_ENDPOINT,
    QZONE_MSG_LIST_ENDPOINT,
    QzoneAPIError,
    QzoneAuthError,
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

    def test_request_exception_retries_then_succeeds(self):
        client = QzoneClient("100", "uin=o100; p_skey=skey123;")

        with (
            patch.object(
                client,
                "_fetch_page",
                side_effect=[
                    requests.RequestException("timeout"),
                    {"code": 0, "msglist": [{"tid": "t1"}], "total": 1},
                ],
            ) as mock_fetch,
            patch("qqzone_spectator.collector.client.time.sleep") as mock_sleep,
        ):
            posts = client.fetch_posts("200", num=1)

        assert posts == [{"tid": "t1"}]
        assert mock_fetch.call_count == 2
        mock_sleep.assert_called_once_with(0.8)

    def test_non_retryable_api_error_is_raised(self):
        client = QzoneClient("100", "uin=o100; p_skey=skey123;")

        with patch.object(
            client,
            "_fetch_page",
            side_effect=QzoneAPIError(-1, "bad request"),
        ):
            with pytest.raises(QzoneAPIError, match="bad request"):
                client.fetch_posts("200", num=1)

    def test_auth_error_is_not_retried(self):
        client = QzoneClient("100", "uin=o100; p_skey=skey123;")

        with (
            patch.object(
                client,
                "_fetch_page",
                side_effect=QzoneAuthError(-3000, "请先登录空间"),
            ) as mock_fetch,
            patch("qqzone_spectator.collector.client.time.sleep") as mock_sleep,
        ):
            with pytest.raises(QzoneAuthError, match="请先登录空间"):
                client.fetch_posts("200", num=1)

        mock_fetch.assert_called_once()
        mock_sleep.assert_not_called()

    def test_returns_partial_posts_after_later_page_keeps_failing(self):
        client = QzoneClient("100", "uin=o100; p_skey=skey123;")

        with (
            patch.object(
                client,
                "_fetch_page",
                side_effect=[
                    {"code": 0, "msglist": [{"tid": "t1"}], "total": 3},
                    QzoneAPIError(-10000, "server busy"),
                    QzoneAPIError(-10000, "server busy"),
                    QzoneAPIError(-10000, "server busy"),
                ],
            ),
            patch("qqzone_spectator.collector.client.time.sleep"),
        ):
            posts = client.fetch_posts("200", num=2)

        assert posts == [{"tid": "t1"}]

    def test_dedupes_posts_across_pages(self):
        client = QzoneClient("100", "uin=o100; p_skey=skey123;")

        with (
            patch.object(
                client,
                "_fetch_page",
                side_effect=[
                    {"code": 0, "msglist": [{"tid": "t1"}, {"tid": "t2"}], "total": 25},
                    {"code": 0, "msglist": [{"tid": "t2"}, {"tid": "t3"}], "total": 25},
                ],
            ),
            patch("qqzone_spectator.collector.client.time.sleep"),
        ):
            posts = client.fetch_posts("200", num=25)

        assert [post["tid"] for post in posts] == ["t1", "t2", "t3"]

    def test_stops_when_msglist_is_not_a_list(self):
        client = QzoneClient("100", "uin=o100; p_skey=skey123;")

        with patch.object(
            client,
            "_fetch_page",
            return_value={"code": 0, "msglist": {"tid": "t1"}, "total": 1},
        ):
            posts = client.fetch_posts("200", num=1)

        assert posts == []


class TestFetchTargetNickname:
    @responses.activate
    def test_success(self):
        body = """
        <html>
          <body>
            <a href="https://user.qzone.qq.com/other">Other</a>
            <a href="https://user.qzone.qq.com/1224944928">士不可以不弘毅</a>
          </body>
        </html>
        """
        responses.get(QZONE_FEEDS_HTML_MODULE_ENDPOINT, body=body, status=200)

        client = QzoneClient("100", "uin=o100; p_skey=skey123;")
        nickname = client.fetch_target_nickname("1224944928")

        assert nickname == "士不可以不弘毅"
        assert "i_login_uin=100" in responses.calls[0].request.url
        assert "i_uin=1224944928" in responses.calls[0].request.url
        assert responses.calls[0].request.headers["Referer"] == "https://user.qzone.qq.com/1224944928"

    @responses.activate
    def test_returns_empty_when_name_not_found(self):
        responses.get(
            QZONE_FEEDS_HTML_MODULE_ENDPOINT,
            body="<html><body><span>no nickname here</span></body></html>",
            status=200,
        )

        client = QzoneClient("100", "uin=o100; p_skey=skey123;")
        assert client.fetch_target_nickname("1224944928") == ""

    @responses.activate
    def test_auth_error_is_raised(self):
        responses.get(
            QZONE_FEEDS_HTML_MODULE_ENDPOINT,
            body='<script>window.__DATA__={"code":-4001,"message":"请先登录"}</script>',
            status=200,
        )

        client = QzoneClient("100", "uin=o100; p_skey=skey123;")
        with pytest.raises(QzoneAuthError, match="请先登录"):
            client.fetch_target_nickname("1224944928")

    @responses.activate
    def test_uses_nickname_cache(self):
        responses.get(
            QZONE_FEEDS_HTML_MODULE_ENDPOINT,
            body='<a href="https://user.qzone.qq.com/1224944928">士不可以不弘毅</a>',
            status=200,
        )

        client = QzoneClient("100", "uin=o100; p_skey=skey123;")
        first = client.fetch_target_nickname("1224944928")
        second = client.fetch_target_nickname("1224944928")

        assert first == "士不可以不弘毅"
        assert second == "士不可以不弘毅"
        assert len(responses.calls) == 1
