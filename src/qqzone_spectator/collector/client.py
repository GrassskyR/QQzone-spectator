from __future__ import annotations

import json
import re
from typing import Any

import requests

QZONE_MSG_LIST_ENDPOINT = (
    "https://h5.qzone.qq.com/proxy/domain/taotao.qq.com/cgi-bin/emotion_cgi_msglist_v6"
)


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
            "uin": self.uin,
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
            raise RuntimeError(f"QZone API error code={code}: {message}")

        msglist = payload.get("msglist") or []
        if not isinstance(msglist, list):
            return []
        return msglist

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
