from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    web_host: str
    web_port: int


def load_settings() -> Settings:
    web_host = os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    web_port = int(os.getenv("WEB_PORT", "8080").strip() or "8080")
    return Settings(
        web_host=web_host,
        web_port=web_port,
    )
