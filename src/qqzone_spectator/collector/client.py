from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

QZONE_MSG_LIST_ENDPOINT = (
    "https://h5.qzone.qq.com/proxy/domain/taotao.qq.com/cgi-bin/emotion_cgi_msglist_v6"
)

MAX_PAGE_SIZE = 20
MAX_PAGE_ROUNDS = 200
PAGE_RETRY_LIMIT = 3
PAGE_RETRY_BACKOFF_SECONDS = 0.8
PAGE_INTERVAL_SECONDS = 0.25

LOGGER = logging.getLogger(__name__)


class QzoneAPIError(RuntimeError):
    def __init__(self, code: int | None, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"QZone API error code={code}: {message}")


def hash33(token: str) -> int:
    value = 5381
    for ch in token:
        value += (value << 5) + ord(ch)
    return value & 0x7FFFFFFF


def cookie_value(cookie: str, key: str) -> str:
    for item in cookie.split(";"):
        part = item.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return ""


class QzoneClient:
    def __init__(self, uin: str, cookie: str, *, timeout: int = 20) -> None:
        self.uin = uin.strip()
        self.cookie = cookie.strip()
        self.timeout = timeout
        self.session = requests.Session()

        if not self.uin:
            raise ValueError("QZONE_UIN is required")
        if not self.cookie:
            raise ValueError("QZONE_COOKIE is required")

        skey = cookie_value(self.cookie, "p_skey") or cookie_value(self.cookie, "skey")
        if not skey:
            raise ValueError("QZONE_COOKIE must contain p_skey or skey")
        self.g_tk = hash33(skey)

    def fetch_posts(self, target_qq: str, *, pos: int = 0, num: int = 20) -> list[dict[str, Any]]:
        expected_total = max(1, int(num))
        current_pos = max(0, int(pos))
        posts: list[dict[str, Any]] = []
        seen: set[str] = set()

        for _ in range(MAX_PAGE_ROUNDS):
            if len(posts) >= expected_total:
                break

            request_num = min(MAX_PAGE_SIZE, expected_total - len(posts))
            payload: dict[str, Any] | None = None
            for attempt in range(1, PAGE_RETRY_LIMIT + 1):
                try:
                    payload = self._fetch_page(target_qq, pos=current_pos, num=request_num)
                    break
                except QzoneAPIError as exc:
                    is_retryable = exc.code in {-10000, -3000, -4000, -5000}
                    if not is_retryable:
                        raise

                    if attempt >= PAGE_RETRY_LIMIT:
                        if posts:
                            LOGGER.warning(
                                "QZONE_PAGE_STOP qq=%s pos=%s request_num=%s code=%s message=%s",
                                target_qq,
                                current_pos,
                                request_num,
                                exc.code,
                                exc.message,
                            )
                            return posts[:expected_total]
                        raise

                    wait_seconds = PAGE_RETRY_BACKOFF_SECONDS * attempt
                    LOGGER.warning(
                        "QZONE_PAGE_RETRY qq=%s pos=%s request_num=%s attempt=%s/%s code=%s wait=%.1fs",
                        target_qq,
                        current_pos,
                        request_num,
                        attempt,
                        PAGE_RETRY_LIMIT,
                        exc.code,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                except requests.RequestException as exc:
                    if attempt >= PAGE_RETRY_LIMIT:
                        if posts:
                            LOGGER.warning(
                                "QZONE_PAGE_STOP qq=%s pos=%s request_num=%s error=%s",
                                target_qq,
                                current_pos,
                                request_num,
                                exc,
                            )
                            return posts[:expected_total]
                        raise

                    wait_seconds = PAGE_RETRY_BACKOFF_SECONDS * attempt
                    LOGGER.warning(
                        "QZONE_HTTP_RETRY qq=%s pos=%s request_num=%s attempt=%s/%s wait=%.1fs",
                        target_qq,
                        current_pos,
                        request_num,
                        attempt,
                        PAGE_RETRY_LIMIT,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)

            if payload is None:
                break

            msglist = payload.get("msglist") or []
            total = self._safe_int(payload.get("total"))

            if not isinstance(msglist, list) or not msglist:
                break

            added = 0
            for item in msglist:
                if not isinstance(item, dict):
                    continue

                dedupe_key = self._dedupe_key(item)
                if dedupe_key and dedupe_key in seen:
                    continue

                if dedupe_key:
                    seen.add(dedupe_key)
                posts.append(item)
                added += 1

                if len(posts) >= expected_total:
                    break

            LOGGER.debug(
                "QZONE_PAGE_FETCH qq=%s pos=%s request_num=%s received=%s added=%s total=%s",
                target_qq,
                current_pos,
                request_num,
                len(msglist),
                added,
                total,
            )

            current_pos += request_num

            if total is not None and current_pos >= total:
                break

            if added == 0:
                break

            time.sleep(PAGE_INTERVAL_SECONDS)

        return posts[:expected_total]

    def _fetch_page(self, target_qq: str, *, pos: int, num: int) -> dict[str, Any]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://user.qzone.qq.com/{target_qq}",
            "Cookie": self.cookie,
        }

        params = {
            "uin": target_qq,
            "hostUin": target_qq,
            "ftype": 0,
            "sort": 0,
            "pos": pos,
            "num": num,
            "replynum": 100,
            "code_version": 1,
            "format": "jsonp",
            "need_private_comment": 1,
            "g_tk": self.g_tk,
            "callback": "_preloadCallback",
        }

        response = self.session.get(
            QZONE_MSG_LIST_ENDPOINT,
            params=params,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = self._decode_payload(response.text)
        code = payload.get("code", 0)
        if code not in (0, None):
            message = payload.get("message") or payload.get("msg") or "unknown error"
            raise QzoneAPIError(self._safe_int(code), str(message))

        return payload

    @staticmethod
    def _safe_int(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    @staticmethod
    def _dedupe_key(item: dict[str, Any]) -> str:
        for key in ("tid", "id", "unikey", "fwd_tid"):
            value = item.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _decode_payload(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("{"):
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded
            raise ValueError("QZone response is not a JSON object")

        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("QZone response does not contain JSON payload")

        loaded = json.loads(match.group(0))
        if isinstance(loaded, dict):
            return loaded
        raise ValueError("QZone response is not a JSON object")
