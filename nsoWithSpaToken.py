"""Download National Statistics Office audio, each with its transcript, using the access token in tokens.json."""

from ddplrll_reader import DdplrllDatasetClient, Settings, preview_jsonld

API_BASE_URL = "https://lrldtmetadataqa.worldbank.org/"
OUTPUT_DIR = "./output/nso"
PROVIDER = "National Statistics Office"
# The provider also has a Text collection of segmented chunks; "Audio" keeps only the recordings.
MEDIA_TYPE = "Audio"
LIMIT = 5


def main() -> None:
    settings = Settings(api_base_url=API_BASE_URL, output_dir=OUTPUT_DIR)
    if not settings.auth_token:
        raise SystemExit('Paste the API access token into tokens.json as {"access_token": "..."}.')

    path = DdplrllDatasetClient(settings).run(
        provider=PROVIDER, media_type=MEDIA_TYPE, limit=LIMIT, download=True
    )
    print(f"JSON-LD saved to: {path}")
    preview_jsonld(path)


if __name__ == "__main__":
    main()
