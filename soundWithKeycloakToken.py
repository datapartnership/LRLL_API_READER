"""Download a small sound sample using a Keycloak access token in tokens.json.

Run kloakAzure.py (or soundWithKeycloakAuth.py) first to create tokens.json.
"""

from pathlib import Path

from ddplrll_reader import DdplrllDatasetClient, Settings, preview_jsonld, print_token_user

API_BASE_URL = "http://localhost:8080"
OUTPUT_DIR = "./output/sound"
LANGUAGE = "ny"
YEAR = 2026
LIMIT = 2


def main() -> None:
    token_file = Path(__file__).with_name("tokens.json")
    settings = Settings(
        api_base_url=API_BASE_URL,
        api_token="",
        token_file=str(token_file),
        output_dir=OUTPUT_DIR,
        verify_ssl=False,
    )
    if not settings.auth_token:
        raise SystemExit(
            "No access token found. Run kloakAzure.py to sign in with Keycloak and create tokens.json."
        )

    print(f"Token loaded. Querying and downloading up to {LIMIT} sound files...", flush=True)
    print_token_user(settings.auth_token)
    path = DdplrllDatasetClient(settings).run(
        media_type="Audio",
        language=LANGUAGE,
        year=YEAR,
        limit=LIMIT,
        output_dir=OUTPUT_DIR,
        download=True,
    )
    print(f"Sound JSON-LD saved to: {path}")
    preview_jsonld(path)


if __name__ == "__main__":
    main()
