"""Sign in with Microsoft Entra ID and fetch the notebook's text/sound datasets.

Install with ``pip install -e .``, configure ENTRA_* in .env, then run
``python kloakAzure.py``. The Entra app registration must be a public desktop
client with ``http://localhost`` registered as its redirect URI.
"""

from __future__ import annotations

import argparse

from ddplrll_reader import DdplrllDatasetClient, Settings, login_entra, preview_jsonld


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("text", "sound", "both"), default="both")
    parser.add_argument("--api-url", default="https://lrllapi.azurewebsites.net")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--text-output", default="./output/text")
    parser.add_argument("--text-keyword", default="malaria")
    parser.add_argument("--text-theme")
    parser.add_argument("--text-author")
    parser.add_argument("--text-year")
    parser.add_argument("--text-limit", type=int, default=10)
    parser.add_argument("--sound-output", default="./output/sound")
    parser.add_argument("--sound-language", default="ny")
    parser.add_argument("--sound-programme")
    parser.add_argument("--sound-keyword")
    parser.add_argument("--sound-year", type=int, default=2024)
    parser.add_argument("--sound-limit", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = login_entra()

    settings = Settings(
        api_base_url=args.api_url,
        api_token=result["access_token"],
        verify_ssl=True,
        file_download_timeout=120.0,
    )
    client = DdplrllDatasetClient(settings)
    download = not args.no_download

    if args.dataset in ("text", "both"):
        path = client.run(
            keyword=args.text_keyword,
            theme=args.text_theme,
            author=args.text_author,
            year=args.text_year,
            limit=args.text_limit,
            output_dir=args.text_output,
            download=download,
        )
        print(f"Text JSON-LD saved to: {path}")
        preview_jsonld(path)

    if args.dataset in ("sound", "both"):
        path = client.run_sound(
            language=args.sound_language,
            programme=args.sound_programme,
            keyword=args.sound_keyword,
            year=args.sound_year,
            limit=args.sound_limit,
            output_dir=args.sound_output,
            download=download,
        )
        print(f"Sound JSON-LD saved to: {path}")
        preview_jsonld(path)


if __name__ == "__main__":
    main()
