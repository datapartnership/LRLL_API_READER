"""Download a small text sample using an LRLL API access token in tokens.json."""

from pathlib import Path

from ddplrll_reader import DdplrllDatasetClient, Settings, preview_jsonld


# Set this to the API base URL used by the SPA.
API_BASE_URL = "https://lrllapi.azurewebsites.net"
OUTPUT_DIR = "./output/text"

def main() -> None:
    settings = Settings(
    api_base_url=API_BASE_URL,
    output_dir=OUTPUT_DIR,
    verify_ssl=False,
)
    if not settings.auth_token:
        raise SystemExit('Paste the LRLL API access token into tokens.json as {"access_token": "..."}.')

    print(f"Token loaded", flush=True)
    path = DdplrllDatasetClient(settings).run(
        media_type="Text",
        keyword="malaria",
        # theme="HEALTH",
        # author="John Banda",
        limit=10,
        output_dir=OUTPUT_DIR,
        download=True,
    )
    print(f"Text JSON-LD saved to: {path}")
    preview_jsonld(path)


if __name__ == "__main__":
    main()
