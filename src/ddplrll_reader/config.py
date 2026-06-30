"""Configuration via environment variables or .env file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict


AUTHORIZATION_HEADER: Final[str] = "Authorization"


class Settings(BaseSettings):
    """All settings can be overridden with environment variables prefixed ``DDPLRLL_``."""

    model_config = SettingsConfigDict(
        env_prefix="DDPLRLL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── API connection ────────────────────────────────────────────────
    api_base_url: str = "http://localhost:5000"
    """Base URL of the DDPLRLL Dataset API (no trailing slash)."""

    api_token: str = ""
    """Bearer token sent in the ``Authorization`` header."""

    token_file: str = "tokens.json"
    """Path to a JSON file containing an ``access_token`` field."""

    # ── Query defaults ────────────────────────────────────────────────
    keyword: str | None = None
    theme: str | None = None
    author: str | None = None
    year: str | None = None
    limit: int = 30

    # ── Download behaviour ────────────────────────────────────────────
    output_dir: str = "./output"
    """Directory where the JSON-LD file and downloaded files are stored."""

    download_files: bool = True
    """Whether to download the files referenced in contentUrl."""

    max_concurrent_downloads: int = 5
    """Maximum number of parallel file downloads."""

    request_timeout: float = 30.0
    """HTTP timeout in seconds for API requests."""

    download_timeout: float = 120.0
    """HTTP per-chunk read/connect timeout in seconds for file downloads."""

    file_download_timeout: float = 300.0
    """Maximum wall-clock seconds allowed for a single file to finish downloading.
    Audio/video streams that never send EOF will be cancelled after this limit."""

    verify_ssl: bool = True
    """Set to False to skip SSL certificate verification (e.g. self-signed certs)."""

    @property
    def auth_token(self) -> str:
        """Return bearer token from explicit config or token file."""
        if self.api_token:
            return self.api_token

        token_path = Path(self.token_file)
        if not token_path.is_absolute():
            token_path = Path.cwd() / token_path

        try:
            payload = json.loads(token_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError):
            return ""

        token = payload.get("access_token")
        return token if isinstance(token, str) else ""

    @property
    def auth_headers(self) -> dict[str, str]:
        """Return the authorization headers for API and file requests."""
        token = self.auth_token
        return {AUTHORIZATION_HEADER: f"Bearer {token}"} if token else {}
