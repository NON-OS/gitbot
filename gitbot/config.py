"""Environment configuration, validated at start so a bad deployment fails
immediately instead of at the first webhook."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ConfigError(SystemExit):
    def __init__(self, message: str):
        super().__init__(f"config: {message}")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _secret(name: str, required: bool) -> str:
    """Reads a secret from, in order: NAME_FILE, the systemd credentials
    directory, then NAME itself. Files win so tokens never sit in the
    environment of a long-lived process."""
    file_hint = os.environ.get(f"{name}_FILE", "").strip()
    creds_dir = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    for candidate in (file_hint, os.path.join(creds_dir, name) if creds_dir else ""):
        if candidate and Path(candidate).is_file():
            value = Path(candidate).read_text(encoding="utf-8").strip()
            if value:
                return value
    value = os.environ.get(name, "").strip()
    if not value and required:
        raise ConfigError(f"{name} is required (set {name}, {name}_FILE, or a systemd credential)")
    return value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}")
    return value


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None
    if not lo <= value <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}")
    return value


@dataclass
class Config:
    bot_token: str
    webhook_secret: str
    chat_id: int
    listen_host: str = "127.0.0.1"
    listen_port: int = 3191  # 3190 is the sync receiver
    webhook_path: str = "/forgejo"
    message_thread_id: int = 0
    forge_base: str = "https://git.nonos.software"
    org: str = "NON-OS"
    state_file: Path = ROOT / "state.json"
    media_dir: Path = ROOT / "media"
    max_commits: int = 5
    summary_chars: int = 90
    skip_drafts: bool = True
    batch_seconds: float = 60.0
    admin_chat_id: int = 0
    pr_poll_seconds: float = 90.0
    release_poll_seconds: float = 300.0
    commands_enabled: bool = True
    reviews_enabled: bool = True
    digest_enabled: bool = True
    digest_dow: int = 6  # Monday=0 .. Sunday=6
    digest_hour: int = 16  # UTC
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Config:
        _load_dotenv(ROOT / ".env")
        chat = _env("CHAT_ID")
        if not chat.lstrip("-").isdigit():
            raise ConfigError("CHAT_ID must be the numeric group id (supergroups start with -100)")
        level = _env("LOG_LEVEL", "INFO").upper()
        if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ConfigError("LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
        base = _env("FORGE_BASE", "https://git.nonos.software").rstrip("/")
        if not base.lower().startswith(("https://", "http://")):
            raise ConfigError("FORGE_BASE must be an http(s) URL")
        path = _env("WEBHOOK_PATH", "/forgejo")
        if not path.startswith("/"):
            raise ConfigError("WEBHOOK_PATH must start with /")
        return cls(
            bot_token=_secret("BOT_TOKEN", required=True),
            webhook_secret=_secret("WEBHOOK_SECRET", required=True),
            chat_id=int(chat),
            listen_host=_env("LISTEN_HOST", "127.0.0.1"),
            listen_port=_env_int("LISTEN_PORT", 3191, 1, 65535),
            webhook_path=path,
            message_thread_id=_env_int("MESSAGE_THREAD_ID", 0, 0, 2**31 - 1),
            forge_base=base,
            org=_env("ORG", "NON-OS"),
            state_file=Path(_env("STATE_FILE", str(ROOT / "state.json"))),
            media_dir=Path(_env("MEDIA_DIR", str(ROOT / "media"))),
            max_commits=_env_int("MAX_COMMITS", 5, 1, 50),
            summary_chars=_env_int("SUMMARY_CHARS", 90, 40, 400),
            skip_drafts=_env("SKIP_DRAFTS", "1") not in ("0", "false", "no"),
            batch_seconds=_env_float("BATCH_SECONDS", 60.0, 0.0, 600.0),
            admin_chat_id=_env_int("ADMIN_CHAT_ID", 0, -(2**63), 2**63 - 1),
            pr_poll_seconds=_env_float("PR_POLL_SECONDS", 90.0, 0.0, 3600.0),
            release_poll_seconds=_env_float("RELEASE_POLL_SECONDS", 300.0, 0.0, 86400.0),
            commands_enabled=_env("COMMANDS_ENABLED", "1") not in ("0", "false", "no"),
            reviews_enabled=_env("REVIEWS_ENABLED", "1") not in ("0", "false", "no"),
            digest_enabled=_env("DIGEST_ENABLED", "1") not in ("0", "false", "no"),
            digest_dow=_env_int("DIGEST_DOW", 6, 0, 6),
            digest_hour=_env_int("DIGEST_HOUR", 16, 0, 23),
            log_level=level,
        )
