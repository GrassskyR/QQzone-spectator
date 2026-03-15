from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _parse_csv(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_csv_int(value: str) -> list[int]:
    result: list[int] = []
    for item in _parse_csv(value):
        try:
            result.append(int(item))
        except ValueError:
            continue
    return result


def _parse_bool(value: str, *, default: bool = False) -> bool:
    text = value.strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    db_path: Path
    media_dir: Path

    qzone_uin: str
    qzone_cookie: str
    target_qqs: list[str]

    fetch_limit: int
    poll_interval_seconds: int
    request_timeout: int

    onebot_base_url: str
    onebot_access_token: str
    push_enabled: bool
    push_private_users: list[int]
    push_groups: list[int]

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "AppConfig":
        if env_file and env_file.exists() and load_dotenv is not None:
            load_dotenv(env_file)
        elif load_dotenv is not None:
            load_dotenv()

        default_root = Path(__file__).resolve().parents[2]
        project_root = Path(os.getenv("PROJECT_ROOT", str(default_root))).resolve()

        db_path = Path(os.getenv("DB_PATH", str(project_root / "data" / "qqzone.db")))
        media_dir = Path(os.getenv("MEDIA_DIR", str(project_root / "data" / "media")))

        return cls(
            project_root=project_root,
            db_path=db_path,
            media_dir=media_dir,
            qzone_uin=os.getenv("QZONE_UIN", "").strip(),
            qzone_cookie=os.getenv("QZONE_COOKIE", "").strip(),
            target_qqs=_parse_csv(os.getenv("TARGET_QQS", "")),
            fetch_limit=max(1, int(os.getenv("FETCH_LIMIT", "20"))),
            poll_interval_seconds=max(30, int(os.getenv("POLL_INTERVAL_SECONDS", "300"))),
            request_timeout=max(5, int(os.getenv("REQUEST_TIMEOUT", "20"))),
            onebot_base_url=os.getenv("ONEBOT_BASE_URL", "").strip().rstrip("/"),
            onebot_access_token=os.getenv("ONEBOT_ACCESS_TOKEN", "").strip(),
            push_enabled=_parse_bool(os.getenv("PUSH_ENABLED", "false"), default=False),
            push_private_users=_parse_csv_int(os.getenv("PUSH_PRIVATE_USERS", "")),
            push_groups=_parse_csv_int(os.getenv("PUSH_GROUPS", "")),
        )

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
