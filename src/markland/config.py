"""Environment-based configuration for Markland."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    base_url: str
    data_dir: Path
    web_port: int
    admin_token: str
    sentry_dsn: str
    resend_api_key: str
    resend_from_email: str
    session_secret: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "markland.db"


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        data_dir_env = os.getenv("MARKLAND_DATA_DIR", "").strip()
        data_dir = Path(data_dir_env).expanduser() if data_dir_env else Path.home() / ".markland"
        data_dir.mkdir(parents=True, exist_ok=True)
        _config = Config(
            base_url=os.getenv("MARKLAND_BASE_URL", "http://localhost:8950").rstrip("/"),
            data_dir=data_dir,
            web_port=int(os.getenv("MARKLAND_WEB_PORT", "8950")),
            admin_token=os.getenv("MARKLAND_ADMIN_TOKEN", "").strip(),
            sentry_dsn=os.getenv("SENTRY_DSN", "").strip(),
            resend_api_key=os.getenv("RESEND_API_KEY", "").strip(),
            resend_from_email=os.getenv("RESEND_FROM_EMAIL", "notifications@markland.dev").strip(),
            session_secret=os.getenv("MARKLAND_SESSION_SECRET", "").strip(),
        )
    return _config


def reset_config() -> None:
    """Reset cached config (for tests)."""
    global _config
    _config = None
