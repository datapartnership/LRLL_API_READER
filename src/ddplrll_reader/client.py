"""High-level client: query → download referenced files → save JSON-LD."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

from ddplrll_reader.config import Settings
from ddplrll_reader.downloader import download_files_and_rewrite
from ddplrll_reader.models import CroissantResponse

logger = logging.getLogger(__name__)


class DdplrllDatasetClient:
    """Convenience wrapper around the Nation Newspaper Dataset API.

    Parameters
    ----------
    settings : Settings | None
        Configuration object.  When *None* a new ``Settings()`` is created
        which reads from env-vars / ``.env``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    # ── public helpers ────────────────────────────────────────────────

    def query(
        self,
        *,
        keyword: str | None = None,
        theme: str | None = None,
        author: str | None = None,
        year: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """Query the API synchronously and return the raw JSON dict."""
        return asyncio.run(
            self.aquery(
                keyword=keyword,
                theme=theme,
                author=author,
                year=year,
                limit=limit,
            )
        )

    async def aquery(
        self,
        *,
        keyword: str | None = None,
        theme: str | None = None,
        author: str | None = None,
        year: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """Query the API asynchronously and return the raw JSON dict."""
        params: dict[str, str | int] = {}
        kw = keyword or self.settings.keyword
        th = theme or self.settings.theme
        au = author or self.settings.author
        yr = year or self.settings.year
        lm = limit or self.settings.limit

        if kw:
            params["Keyword"] = kw
        if th:
            params["Theme"] = th
        if au:
            params["Author"] = au
        if yr:
            params["Year"] = yr
        if lm:
            params["Limit"] = lm

        url = f"{self.settings.api_base_url.rstrip('/')}/api/Datasets/query"
        headers = self.settings.auth_headers

        logger.info("GET %s  params=%s", url, params)

        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout,
            verify=self.settings.verify_ssl,
        ) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # ── full pipeline ────────────────────────────────────────────────

    def run(
        self,
        *,
        keyword: str | None = None,
        theme: str | None = None,
        author: str | None = None,
        year: str | None = None,
        limit: int | None = None,
        output_dir: str | None = None,
        download: bool | None = None,
    ) -> Path:
        """Run the full pipeline synchronously and return the JSON-LD path."""
        return asyncio.run(
            self.arun(
                keyword=keyword,
                theme=theme,
                author=author,
                year=year,
                limit=limit,
                output_dir=output_dir,
                download=download,
            )
        )

    async def arun(
        self,
        *,
        keyword: str | None = None,
        theme: str | None = None,
        author: str | None = None,
        year: str | None = None,
        limit: int | None = None,
        output_dir: str | None = None,
        download: bool | None = None,
    ) -> Path:
        """Run the full pipeline:

        1. Query the API.
        2. (Optionally) download all files referenced in ``sc:contentUrl``.
        3. Rewrite ``scContentUrl`` to point to the local files.
        4. Save the resulting JSON-LD document to *output_dir*.

        Returns the ``Path`` to the saved JSON-LD file.
        """
        data = await self.aquery(
            keyword=keyword,
            theme=theme,
            author=author,
            year=year,
            limit=limit,
        )

        out = Path(output_dir or self.settings.output_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)
        files_dir = out / "files"

        should_download = download if download is not None else self.settings.download_files

        if should_download:
            data = await download_files_and_rewrite(
                data,
                files_dir=files_dir,
                api_token=self.settings.auth_token,
                max_concurrent=self.settings.max_concurrent_downloads,
                timeout=self.settings.download_timeout,
                verify_ssl=self.settings.verify_ssl,
            )

        jsonld_path = out / "dataset.jsonld"
        jsonld_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved JSON-LD → %s", jsonld_path)

        return jsonld_path

    # ── validated query ───────────────────────────────────────────────

    def query_validated(self, **kwargs) -> CroissantResponse:
        """Like :meth:`query` but returns a validated Pydantic model."""
        raw = self.query(**kwargs)
        return CroissantResponse.model_validate(raw)
