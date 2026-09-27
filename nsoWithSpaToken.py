"""Download every National Statistics Office recording, each with its transcript, using the access token in tokens.json."""

import logging

from ddplrll_reader import DdplrllDatasetClient, Settings

API_BASE_URL = "https://lrldtmetadataqa.worldbank.org/"
OUTPUT_DIR = "./output/nso"
PROVIDER = "National Statistics Office"
# The provider also has a Text collection of segmented chunks; "Audio" keeps only the recordings.
MEDIA_TYPE = "Audio"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings(api_base_url=API_BASE_URL, output_dir=OUTPUT_DIR)
    if not settings.auth_token:
        raise SystemExit('Paste the API access token into tokens.json as {"access_token": "..."}.')

    # Downloads whole collections (no limit, no sampling). Re-running skips finished collections.
    folders = DdplrllDatasetClient(settings).download_collections(
        provider=PROVIDER, media_type=MEDIA_TYPE
    )
    for folder in folders:
        print(f"Collection saved to: {folder}  (metadata: {folder / 'metadata.jsonld'})")


if __name__ == "__main__":
    main()
