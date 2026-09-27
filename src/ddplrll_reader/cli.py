"""CLI interface powered by Typer."""

from __future__ import annotations

import logging
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from ddplrll_reader.client import DdplrllDatasetClient
from ddplrll_reader.config import Settings

app = typer.Typer(
    name="ddplrll-reader",
    help="Query the dataset API and download referenced files.",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@app.command()
def run(
    api_url: Annotated[
        str,
        typer.Option("--api-url", "-u", envvar="DDPLRLL_API_BASE_URL", help="Base URL of the API."),
    ] = "http://localhost:5000",
    api_token: Annotated[
        str,
        typer.Option("--api-token", "-k", help="Bearer token for authentication."),
    ] = "",
    media_type: Annotated[
        Optional[str],
        typer.Option("--media-type", "-m", help="Filter by media type: Text, Audio, or Video."),
    ] = None,
    collection_id: Annotated[
        Optional[str],
        typer.Option("--collection-id", help="Restrict to a single collection."),
    ] = None,
    provider: Annotated[
        Optional[str],
        typer.Option("--provider", "-P", help="Filter by provider (partial, case-insensitive)."),
    ] = None,
    language: Annotated[
        Optional[str],
        typer.Option("--language", "-L", help="Filter by language name or code (e.g. nya)."),
    ] = None,
    keyword: Annotated[
        Optional[str],
        typer.Option("--keyword", "-K", help="Filter by keyword."),
    ] = None,
    theme: Annotated[
        Optional[str],
        typer.Option("--theme", "-t", help="Filter by theme."),
    ] = None,
    author: Annotated[
        Optional[str],
        typer.Option("--author", "-a", help="Filter by text author."),
    ] = None,
    year: Annotated[
        Optional[int],
        typer.Option("--year", "-y", help="Filter by year (e.g. 2024)."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max files returned (1-100)."),
    ] = 30,
    output_dir: Annotated[
        str,
        typer.Option("--output", "-o", help="Directory for JSON-LD and downloaded files."),
    ] = "./output",
    no_download: Annotated[
        bool,
        typer.Option("--no-download", help="Skip downloading referenced files."),
    ] = False,
    max_concurrent: Annotated[
        int,
        typer.Option("--concurrency", "-c", help="Max parallel downloads."),
    ] = 5,
    file_timeout: Annotated[
        float,
        typer.Option("--file-timeout", help="Max seconds allowed for a single file download end-to-end."),
    ] = 300.0,
    no_verify_ssl: Annotated[
        bool,
        typer.Option("--no-verify-ssl", help="Skip SSL certificate verification."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Query the API, download referenced files, and save a local JSON-LD document."""
    _setup_logging(verbose)

    settings = Settings(
        api_base_url=api_url,
        api_token=api_token,
        media_type=media_type,
        collection_id=collection_id,
        provider=provider,
        language=language,
        keyword=keyword,
        theme=theme,
        author=author,
        year=year,
        limit=limit,
        output_dir=output_dir,
        download_files=not no_download,
        max_concurrent_downloads=max_concurrent,
        file_download_timeout=file_timeout,
        verify_ssl=not no_verify_ssl,
    )

    client = DdplrllDatasetClient(settings)
    jsonld_path = client.run(output_dir=output_dir, download=not no_download)

    console.print(f"\n[bold green]✓[/] JSON-LD saved to [cyan]{jsonld_path}[/]")


@app.command()
def health(
    api_url: Annotated[
        str,
        typer.Option("--api-url", "-u", envvar="DDPLRLL_API_BASE_URL", help="Base URL of the API."),
    ] = "http://localhost:5000",
    api_token: Annotated[
        str,
        typer.Option("--api-token", "-k", help="Bearer token for authentication."),
    ] = "",
    no_verify_ssl: Annotated[
        bool,
        typer.Option("--no-verify-ssl", help="Skip SSL certificate verification (e.g. behind a proxy)."),
    ] = False,
) -> None:
    """Check the API health endpoint."""
    import httpx

    url = f"{api_url.rstrip('/')}/api/collections/health"
    headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}
    resp = httpx.get(url, headers=headers, timeout=10, verify=not no_verify_ssl)
    resp.raise_for_status()
    console.print_json(data=resp.json())


if __name__ == "__main__":
    app()
