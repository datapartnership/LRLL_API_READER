"""High-level client: query → download referenced files → save JSON-LD."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

from ddplrll_reader.config import Settings
from ddplrll_reader.downloader import (
    download_bundle,
    download_files_and_rewrite,
    rewrite_bundle_urls,
)
from ddplrll_reader.models import CroissantResponse

logger = logging.getLogger(__name__)


class DdplrllDatasetClient:
    """Convenience wrapper around the collections API (text, audio, and video).

    Parameters
    ----------
    settings : Settings | None
        Configuration object.  When *None* a new ``Settings()`` is created
        which reads from env-vars / ``.env``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    # ── public helpers ────────────────────────────────────────────────

    def query(self, **filters) -> dict:
        """Query the API synchronously and return the raw JSON dict.

        Accepts the same filters as :meth:`aquery`.
        """
        return asyncio.run(self.aquery(**filters))

    async def aquery(
        self,
        *,
        media_type: str | None = None,
        collection_id: str | None = None,
        provider: str | None = None,
        language: str | None = None,
        keyword: str | None = None,
        theme: str | None = None,
        author: str | None = None,
        year: int | None = None,
        limit: int | None = None,
    ) -> dict:
        """Query ``/api/collections/query`` asynchronously and return the raw JSON dict.

        All filters are optional and combinable; unset filters fall back to ``Settings``.

        media_type
            ``Text``, ``Audio``, or ``Video``.
        collection_id
            Restrict to a single collection.
        provider
            Provider name (partial, case-insensitive), e.g. ``National Statistics Office``.
        language
            Collection language name or code (partial), e.g. ``nya``.
        keyword, theme
            File or collection keyword / theme (partial).
        author
            Text file author (partial).
        year
            Text publication year, or a year inside the collection's coverage.
        limit
            Max file entries returned (1-100).
        """
        s = self.settings
        filters: dict[str, str | int | None] = {
            "MediaType": media_type or s.media_type,
            "CollectionId": collection_id or s.collection_id,
            "Provider": provider or s.provider,
            "Language": language or s.language,
            "Keyword": keyword or s.keyword,
            "Theme": theme or s.theme,
            "Author": author or s.author,
            "Year": year or s.year,
            "Limit": limit or s.limit,
        }
        params = {k: v for k, v in filters.items() if v}

        url = f"{s.api_base_url.rstrip('/')}/api/collections/query"
        headers = s.auth_headers

        logger.info("GET %s  params=%s", url, params)

        async with httpx.AsyncClient(
            timeout=s.request_timeout,
            verify=s.verify_ssl,
        ) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # ── full pipeline ────────────────────────────────────────────────

    def run(self, **kwargs) -> Path:
        """Run the full pipeline synchronously and return the JSON-LD path.

        Accepts the same arguments as :meth:`arun`.
        """
        return asyncio.run(self.arun(**kwargs))

    async def arun(
        self,
        *,
        output_dir: str | None = None,
        download: bool | None = None,
        **filters,
    ) -> Path:
        """Run the full pipeline:

        1. Query the API (``filters`` are passed to :meth:`aquery`).
        2. (Optionally) download all files referenced in ``sc:contentUrl``,
           including audio/video transcriptions.
        3. Rewrite ``sc:contentUrl`` to point to the local files.
        4. Save the resulting JSON-LD document to *output_dir*.

        Returns the ``Path`` to the saved JSON-LD file.
        """
        data = await self.aquery(**filters)

        out = Path(output_dir or self.settings.output_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)
        files_dir = out / "files"

        should_download = download if download is not None else self.settings.download_files
        has_graph = bool(data.get("@graph") or data.get("graph"))

        if not has_graph:
            logger.warning(data.get("message") or "The API returned no datasets.")
        elif should_download:
            data = await download_files_and_rewrite(
                data,
                files_dir=files_dir,
                api_token=self.settings.auth_token,
                max_concurrent=self.settings.max_concurrent_downloads,
                timeout=self.settings.download_timeout,
                file_timeout=self.settings.file_download_timeout,
                verify_ssl=self.settings.verify_ssl,
            )

        jsonld_path = out / "dataset.jsonld"
        jsonld_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved JSON-LD → %s", jsonld_path)

        return jsonld_path

    # ── whole collections ────────────────────────────────────────────

    def list_collections(self, **filters) -> list[dict]:
        """List matching collections synchronously.

        Accepts the same filters as :meth:`alist_collections`.
        """
        return asyncio.run(self.alist_collections(**filters))

    async def alist_collections(
        self,
        *,
        media_type: str | None = None,
        provider: str | None = None,
        language: str | None = None,
        theme: str | None = None,
        year: int | None = None,
    ) -> list[dict]:
        """Return every collection matching the filters, walking all catalog pages.

        Uses ``/api/catalog/collections``, which is paged in a stable order, so unlike
        :meth:`aquery` the result is complete rather than a random sample.
        """
        s = self.settings
        filters: dict[str, str | int | None] = {
            "MediaType": media_type or s.media_type,
            "Provider": provider or s.provider,
            "Language": language or s.language,
            "Theme": theme or s.theme,
            "Year": year or s.year,
        }
        params: dict[str, str | int] = {k: v for k, v in filters.items() if v}
        url = f"{s.api_base_url.rstrip('/')}/api/catalog/collections"

        collections: list[dict] = []
        async with httpx.AsyncClient(timeout=s.request_timeout, verify=s.verify_ssl) as client:
            page = 1
            while True:
                logger.info("GET %s  params=%s page=%d", url, params, page)
                resp = await client.get(
                    url, params={**params, "Page": page, "PageSize": 50}, headers=s.auth_headers
                )
                resp.raise_for_status()
                body = resp.json()
                collections.extend(body.get("results", []))
                if page >= body.get("totalPages", 0):
                    return collections
                page += 1

    def download_collections(self, **kwargs) -> list[Path]:
        """Download whole collections synchronously.

        Accepts the same arguments as :meth:`adownload_collections`.
        """
        return asyncio.run(self.adownload_collections(**kwargs))

    async def adownload_collections(
        self,
        *,
        output_dir: str | None = None,
        keep_zip: bool = False,
        **filters,
    ) -> list[Path]:
        """Download **every** file of every matching audio/video collection.

        Each collection's bundle (``/api/collections/{id}/bundle``) holds all its media
        files, each followed by its transcription, plus a ``metadata.jsonld`` Croissant
        document. It is extracted to ``<output_dir>/<collection id>/``.

        ``filters`` are passed to :meth:`alist_collections`. Text collections cannot be
        bundled by the API and are skipped with a warning. Collections whose folder
        already exists are skipped, so an interrupted run can simply be restarted.

        Returns the extracted collection folders. Raises ``RuntimeError`` after trying
        every collection if any of them failed.
        """
        s = self.settings
        out = Path(output_dir or s.output_dir).resolve()
        collections = await self.alist_collections(**filters)
        if not collections:
            logger.warning("No collections matched %s.", filters)
            return []

        folders: list[Path] = []
        failed: list[str] = []
        for c in collections:
            cid, name = c["id"], c.get("name", "")
            if c.get("mediaType") == "Text":
                logger.warning(
                    "Skipping text collection %s (%s): the API cannot bundle text.", cid, name
                )
                continue

            dest = out / cid
            if dest.exists():
                logger.info("Skipping %s: already downloaded to %s", cid, dest)
                # Also fixes folders downloaded before URLs were rewritten.
                await asyncio.to_thread(rewrite_bundle_urls, dest)
                folders.append(dest)
                continue

            logger.info("Collection %s – %s (%s files)", cid, name, c.get("items", "?"))
            try:
                folders.append(
                    await download_bundle(
                        f"{s.api_base_url.rstrip('/')}/api/collections/{cid}/bundle",
                        dest_dir=dest,
                        api_token=s.auth_token,
                        timeout=s.download_timeout,
                        verify_ssl=s.verify_ssl,
                        keep_zip=keep_zip,
                    )
                )
            except Exception as exc:  # keep going; report every failure at the end
                logger.error("Failed to download collection %s: %s", cid, exc)
                failed.append(cid)

        if failed:
            raise RuntimeError(f"Failed to download collection(s): {', '.join(failed)}")
        return folders

    # ── validated query ───────────────────────────────────────────────

    def query_validated(self, **filters) -> CroissantResponse:
        """Like :meth:`query` but returns a validated Pydantic model."""
        raw = self.query(**filters)
        return CroissantResponse.model_validate(raw)


def preview_jsonld(jsonld_path: "str | Path") -> None:
    """Print a summary of a saved Croissant JSON-LD file.

    Shows sampling info (totalMatched, returned, randomSample), the name,
    provider, media type and file count of each dataset in ``@graph``, and key
    metadata fields of the first file entry.
    """

    def _get(node: dict, *keys: str) -> object:
        for k in keys:
            v = node.get(k)
            if v is not None:
                return v
        return None

    def _org_name(node: dict, *keys: str) -> object:
        org = _get(node, *keys)
        return _get(org, "sc:name", "scName") if isinstance(org, dict) else org

    with open(jsonld_path, encoding="utf-8") as fh:
        data = json.load(fh)

    datasets = data.get("@graph") or data.get("graph") or []
    if not datasets:
        print(f"\n{data.get('message') or 'No datasets returned.'}")
        return

    sampling = data.get("samplingInfo", {})
    print(
        f"\nMatched: {sampling.get('totalMatched')}  "
        f"Returned: {sampling.get('returned')}  "
        f"Random sample: {sampling.get('randomSample')}"
    )

    for dataset in datasets:
        print(f"\nDataset : {_get(dataset, 'sc:name', 'scName')}")
        print(f"Provider: {_org_name(dataset, 'sc:provider', 'scProvider')}")
        print(f"Media   : {_get(dataset, 'ddpv:mediaType', 'ddpvMediaType')}")
        print(f"Files   : {len(dataset.get('distribution', []))}")

    files = datasets[0].get("distribution", [])
    if not files:
        return

    f0 = files[0]
    print("\nFirst file:")
    for label, *keys in [
        ("Name    ", "sc:name", "scName"),
        ("URL     ", "sc:contentUrl", "scContentUrl"),
        ("Author  ", "sc:author", "scAuthor"),
        ("Keywords", "sc:keywords", "scKeywords"),
        ("Format  ", "sc:encodingFormat", "scEncodingFormat"),
        ("Duration", "ebucore:duration", "ebucoreDuration"),
    ]:
        val = _get(f0, *keys)
        if val is not None:
            print(f"  {label}: {val}")

    transcription = _get(f0, "ddpv:transcription", "ddpvTranscription")
    if isinstance(transcription, dict):
        print(f"  Transcr.: {_get(transcription, 'sc:contentUrl', 'scContentUrl')}")
