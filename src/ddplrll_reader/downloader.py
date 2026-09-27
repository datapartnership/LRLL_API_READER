"""Download files referenced in the Croissant JSON-LD and rewrite content URLs."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import mimetypes
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from ddplrll_reader.config import AUTHORIZATION_HEADER

logger = logging.getLogger(__name__)


def _first_present(mapping: dict, *keys: str) -> object | None:
    """Return the first present key from a mapping."""
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _guess_extension(node: dict) -> str:
    """Choose a local file extension from dataset metadata when possible."""
    file_name = _first_present(node, "sc:name", "scName")
    if isinstance(file_name, str):
        suffix = Path(file_name).suffix
        if suffix:
            return suffix

    encoding_format = _first_present(node, "sc:encodingFormat", "scEncodingFormat")
    if not isinstance(encoding_format, str) or not encoding_format:
        return ""

    normalized = {
        "text/markdown": ".md",
        "audio/flac": ".flac",
        "audio/x-flac": ".flac",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
    }.get(encoding_format)
    if normalized:
        return normalized

    guessed = mimetypes.guess_extension(encoding_format, strict=False)
    return guessed or ""


def _build_destination(file_id: str, node: dict, used: set[str]) -> Path:
    """Build a local file name from the file's original ``sc:name``.

    Falls back to *file_id* when there is no usable name. A name already in *used*
    (compared case-insensitively) gets the file id appended, e.g. ``a-file-1a2b.wav``.
    """
    raw_name = _first_present(node, "sc:name", "scName")
    name = Path(raw_name.replace("\\", "/")).name if isinstance(raw_name, str) else ""
    candidate = Path(name if name not in {"", ".", ".."} else file_id)
    if not candidate.suffix:
        candidate = Path(candidate.name + _guess_extension(node))

    if candidate.name.lower() in used:
        candidate = Path(f"{candidate.stem}-{file_id}{candidate.suffix}")
    used.add(candidate.name.lower())
    return candidate


def _should_retry_as_http(url: str, exc: Exception) -> bool:
    """Detect localhost HTTPS URLs that are actually serving plain HTTP."""
    if "WRONG_VERSION_NUMBER" not in str(exc):
        return False

    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in {"localhost", "127.0.0.1", "::1"}


def _to_http_url(url: str) -> str:
    """Rewrite an HTTPS localhost URL to HTTP for a retry."""
    parts = urlsplit(url)
    return urlunsplit(("http", parts.netloc, parts.path, parts.query, parts.fragment))


def _adjust_for_content_type(dest: Path, content_type: str) -> Path:
    """Text files are served as plain text (even PDFs), so save them as ``.txt``."""
    if content_type.split(";")[0].strip() == "text/plain" and dest.suffix not in {".txt", ".md"}:
        return dest.with_suffix(".txt")
    return dest


async def _stream_to(client: httpx.AsyncClient, url: str, dest: Path) -> Path:
    """Stream *url* to disk and return the path actually written."""
    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        dest = _adjust_for_content_type(dest, resp.headers.get("content-type", ""))
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                fh.write(chunk)
    return dest


async def _download_one(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    semaphore: asyncio.Semaphore,
) -> Path:
    """Download a single file, returning the local path."""
    async with semaphore:
        logger.info("Downloading %s → %s", url, dest)
        try:
            dest = await _stream_to(client, url, dest)
        except httpx.ConnectError as exc:
            if not _should_retry_as_http(url, exc):
                raise

            http_url = _to_http_url(url)
            logger.warning("Retrying download over HTTP for localhost URL %s", http_url)
            dest = await _stream_to(client, http_url, dest)
    logger.info("  ✓ %s (%s bytes)", dest.name, dest.stat().st_size)
    return dest


def _collect_file_nodes(data: dict) -> list[dict]:
    """Walk the graph → distribution lists and return every FileObject dict.

    Audio/video file objects carry their transcription as a nested FileObject,
    which is returned too so it gets downloaded alongside the media file.
    """
    nodes: list[dict] = []
    for dataset in _first_present(data, "@graph", "graph") or []:
        for fo in dataset.get("distribution", []):
            transcription = _first_present(fo, "ddpv:transcription", "ddpvTranscription")
            for node in (fo, transcription):
                if isinstance(node, dict) and _first_present(node, "sc:contentUrl", "scContentUrl"):
                    nodes.append(node)
    return nodes


async def download_files_and_rewrite(
    data: dict,
    *,
    files_dir: Path,
    api_token: str = "",
    max_concurrent: int = 5,
    timeout: float = 120.0,
    file_timeout: float = 300.0,
    verify_ssl: bool = True,
) -> dict:
    """Download every referenced file in *data* and return a **copy** with rewritten URLs.

    Parameters
    ----------
    data
        The raw JSON dict from the API response.
    files_dir
        Directory where files will be saved.  Sub-directories per dataset-id
        are created automatically.
    api_token
        Passed as a bearer token in the ``Authorization`` header on each
        download request.
    max_concurrent
        Max simultaneous downloads.
    timeout
        Per-chunk httpx read/connect timeout in seconds.
    file_timeout
        Maximum wall-clock seconds allowed for a *single* file to finish
        downloading end-to-end.  Audio streams that never send EOF will be
        cancelled once this limit is reached.  Default: 300 s.

    Returns
    -------
    dict
        A deep copy of *data* with every content URL replaced by the
        local file path.
    """
    result = copy.deepcopy(data)
    file_nodes = _collect_file_nodes(result)

    if not file_nodes:
        logger.warning("No file nodes with content URLs found; nothing to download.")
        return result

    files_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrent)
    headers = {AUTHORIZATION_HEADER: f"Bearer {api_token}"} if api_token else {}

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True, verify=verify_ssl) as client:
        tasks: list[asyncio.Task] = []

        used_names: set[str] = set()
        for node in file_nodes:
            url = _first_present(node, "sc:contentUrl", "scContentUrl")
            file_id = _first_present(node, "@id", "id") or "unknown"
            dest = files_dir / _build_destination(str(file_id), node, used_names)

            tasks.append(
                asyncio.create_task(
                    asyncio.wait_for(
                        _download_one(client, url, dest, semaphore),
                        timeout=file_timeout,
                    )
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Rewrite URLs for successful downloads
    succeeded = 0
    failed = 0
    for node, res in zip(file_nodes, results):
        if isinstance(res, BaseException):
            logger.error(
                "Failed to download %s: %s",
                _first_present(node, "sc:contentUrl", "scContentUrl"),
                res,
            )
            failed += 1
        else:
            if "sc:contentUrl" in node:
                node["sc:contentUrl"] = str(res)
            else:
                node["scContentUrl"] = str(res)
            succeeded += 1

    logger.info(
        "Downloads complete: %d succeeded, %d failed out of %d total.",
        succeeded,
        failed,
        len(file_nodes),
    )
    return result


# Characters the API replaces with "_" in bundle entry names (Windows' invalid file name
# characters; a Linux host only replaces "\0", which the second pass below covers).
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*') | frozenset(chr(i) for i in range(32))


def _bundle_entry_names(node: dict) -> list[str]:
    """Return the names the API may have given *node*'s file inside a bundle ZIP.

    Mirrors the API's naming: the base name of ``sc:name`` with invalid characters
    replaced by ``_`` (the id when nothing is left), prefixed with ``<id>_`` when an
    earlier file already took the name. The prefixed name comes first because it can
    only belong to this file.
    """
    file_id = str(_first_present(node, "@id", "id") or "")
    raw_name = _first_present(node, "sc:name", "scName")
    base = raw_name.replace("\\", "/").rsplit("/", 1)[-1] if isinstance(raw_name, str) else ""

    names: list[str] = []
    for invalid in (_WINDOWS_INVALID_CHARS, frozenset("\0")):
        cleaned = "".join("_" if c in invalid else c for c in base).strip()
        name = file_id if cleaned in {"", ".", ".."} else cleaned
        names += [f"{file_id}_{name}", name]
    return list(dict.fromkeys(names))


def rewrite_bundle_urls(folder: Path) -> tuple[int, int]:
    """Point every ``sc:contentUrl`` in ``<folder>/metadata.jsonld`` at its extracted file.

    Covers media files and their nested ``ddpv:transcription`` objects. Files that are not
    in the folder (e.g. listed in ``MISSING_FILES.txt``) keep their API URL. Safe to run
    again on an already rewritten document.

    Returns ``(rewritten, not_found)``.
    """
    folder = folder.resolve()
    metadata_path = folder / "metadata.jsonld"
    data = json.loads(metadata_path.read_text(encoding="utf-8"))

    rewritten = not_found = 0
    for node in _collect_file_nodes(data):
        local = next(
            (folder / n for n in _bundle_entry_names(node) if (folder / n).is_file()), None
        )
        if local is None:
            not_found += 1
            continue
        node["sc:contentUrl" if "sc:contentUrl" in node else "scContentUrl"] = str(local)
        rewritten += 1

    metadata_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if not_found:
        logger.warning(
            "  %d file(s) in %s are not in the bundle and keep their API URL",
            not_found, metadata_path,
        )
    return rewritten, not_found


def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract *zip_path* into *dest_dir* via a temporary sibling directory.

    *dest_dir* only appears once extraction has finished, so its existence marks a
    complete download.
    """
    staging = dest_dir.with_name(dest_dir.name + ".extracting")
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging)
    staging.rename(dest_dir)


async def download_bundle(
    url: str,
    *,
    dest_dir: Path,
    api_token: str = "",
    timeout: float = 120.0,
    verify_ssl: bool = True,
    keep_zip: bool = False,
) -> Path:
    """Download a collection bundle ZIP from *url* and extract it into *dest_dir*.

    The ZIP streams to ``<dest_dir>.zip.part`` and is renamed once complete, so an
    interrupted download never looks finished. The bundle has no size limit, so there
    is no wall-clock cap; *timeout* applies per read/connect.

    Returns *dest_dir*.
    """
    zip_path = dest_dir.with_name(dest_dir.name + ".zip")
    part_path = zip_path.with_name(zip_path.name + ".part")
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    headers = {AUTHORIZATION_HEADER: f"Bearer {api_token}"} if api_token else {}

    if not zip_path.exists():
        logger.info("Downloading bundle %s → %s", url, zip_path)
        async with httpx.AsyncClient(
            timeout=timeout, headers=headers, follow_redirects=True, verify=verify_ssl
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                written = 0
                next_report = 500 * 1024 * 1024
                try:
                    with part_path.open("wb") as fh:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                            fh.write(chunk)
                            written += len(chunk)
                            if written >= next_report:
                                logger.info("  … %.1f GB received", written / 1024**3)
                                next_report += 500 * 1024 * 1024
                except BaseException:
                    part_path.unlink(missing_ok=True)  # the stream cannot be resumed
                    raise
        part_path.rename(zip_path)
        logger.info("  ✓ %s (%.2f GB)", zip_path.name, zip_path.stat().st_size / 1024**3)

    logger.info("Extracting %s → %s", zip_path.name, dest_dir)
    await asyncio.to_thread(_extract_zip, zip_path, dest_dir)
    rewritten, _ = await asyncio.to_thread(rewrite_bundle_urls, dest_dir)
    logger.info("  Rewrote %d content URL(s) in metadata.jsonld to local paths", rewritten)

    missing = dest_dir / "MISSING_FILES.txt"
    if missing.exists():
        count = sum(1 for line in missing.read_text(encoding="utf-8").splitlines() if line.strip())
        logger.warning("  %d file(s) were missing on the server; see %s", count, missing)

    if not keep_zip:
        zip_path.unlink()
    return dest_dir
