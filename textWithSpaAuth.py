"""Download a small text sample after signing in with the Entra SPA browser flow."""

from ddplrll_reader import (
    DdplrllDatasetClient,
    EntraConfig,
    Settings,
    acquire_api_token_spa,
    preview_jsonld,
    print_token_user,
)

API_BASE_URL = "https://lrldtmetadataqa.worldbank.org/"
OUTPUT_DIR = "./output/text"


def main() -> None:
    try:
        result = acquire_api_token_spa(EntraConfig())
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    settings = Settings(
        api_base_url=API_BASE_URL,
        api_token=result["access_token"],
        output_dir=OUTPUT_DIR,
        verify_ssl=False,
    )
    print("Signed in", flush=True)
    print_token_user(result["access_token"])
    path = DdplrllDatasetClient(settings).run(
        media_type="Text",
        keyword="malaria",
        limit=10,
        output_dir=OUTPUT_DIR,
        download=True,
    )
    print(f"Text JSON-LD saved to: {path}")
    preview_jsonld(path)


if __name__ == "__main__":
    main()
