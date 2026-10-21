from __future__ import annotations

import os
import re
import tomllib
import json
import tempfile
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlackConfig(StrictModel):
    token: SecretStr = SecretStr("")
    joined_public: bool = True
    private_channels: bool = True
    direct_messages: bool = False
    group_messages: bool = False
    unjoined_public: bool = False
    initial_lookback_hours: int = Field(24, ge=1, le=87600)
    thread_tracking_days: int = Field(30, ge=1, le=3650)
    timeout_seconds: int = Field(30, ge=1, le=300)
    retries: int = Field(3, ge=0, le=8)
    max_retry_after_seconds: int = Field(120, ge=1, le=600)


class AIConfig(StrictModel):
    provider: Literal["ollama", "claude_code"] = "ollama"
    chunk_characters: int = Field(24000, ge=2000, le=200000)
    timeout_seconds: int = Field(180, ge=1, le=1800)
    retries: int = Field(1, ge=0, le=3)
    top_items: int = Field(5, ge=1, le=50)


class OllamaConfig(StrictModel):
    base_url: str = "http://127.0.0.1:11434"
    model: str = ""

    @field_validator("base_url")
    @classmethod
    def local_url(cls, value: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(value)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Ollama must use a local http URL without credentials")
        return value.rstrip("/")


class ClaudeConfig(StrictModel):
    executable: str = "claude"
    model: str = "sonnet"


class StorageConfig(StrictModel):
    database: Path = Path("data/rundown.sqlite3")
    summaries_dir: Path = Path("summaries")
    timezone: str = "America/Edmonton"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown IANA timezone") from None
        return value


DEFAULT_KEYWORDS = {"urgent": 5, "blocker": 5, "incident": 5, "outage": 5,
                    "action required": 4, "deadline": 4, "security": 4,
                    "customer": 3, "decision": 3, "review": 2, "help": 2, "todo": 2}


class Config(StrictModel):
    slack: SlackConfig = Field(default_factory=SlackConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    claude_code: ClaudeConfig = Field(default_factory=ClaudeConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    keywords: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_KEYWORDS))

    @field_validator("keywords")
    @classmethod
    def valid_keywords(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not k.strip() or not 0 <= v <= 100 for k, v in value.items()):
            raise ValueError("Keywords must be nonempty with weights between 0 and 100")
        return {k.strip().casefold(): v for k, v in value.items()}


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser().resolve()
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    token = raw.get("slack", {}).get("token", "")
    if isinstance(token, str) and token.startswith("env:"):
        raw["slack"]["token"] = os.environ.get(token[4:], "")
    return resolve_paths(Config.model_validate(raw), path)


def resolve_paths(config: Config, path: str | Path) -> Config:
    path = Path(path).expanduser().resolve()
    for field in ("database", "summaries_dir"):
        value = getattr(config.storage, field).expanduser()
        setattr(config.storage, field, value if value.is_absolute() else path.parent / value)
    return config


def needs_setup(config: Config) -> bool:
    if not config.slack.token.get_secret_value().startswith("xoxp-"):
        return True
    if config.ai.provider == "ollama":
        return not config.ollama.model.strip()
    return not config.claude_code.executable.strip() or not config.claude_code.model.strip()


def token_setting(path: Path, config: Config) -> str:
    """Retain an environment reference when a password field is left blank."""
    if path.exists():
        with path.open("rb") as stream:
            return tomllib.load(stream).get("slack", {}).get("token", "")
    return config.slack.token.get_secret_value()


def save_config(path: Path, config: Config, token: str):
    """Write validated config atomically with owner-only permissions."""
    data = config.model_dump(mode="json")
    data["slack"]["token"] = token
    lines = ["# Managed by Rundown settings. Keep this file private.", ""]
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, value in values.items():
            # JSON string escaping is also valid TOML basic-string escaping.
            lines.append(f"{json.dumps(key, ensure_ascii=False)} = {json.dumps(value, ensure_ascii=False)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".rundown-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def redact(text: str, config: Config | None = None) -> str:
    if config:
        token = config.slack.token.get_secret_value()
        if token:
            text = text.replace(token, "[redacted]")
    return re.sub(r"xox[a-z]-[A-Za-z0-9-]+", "[redacted]", text)
