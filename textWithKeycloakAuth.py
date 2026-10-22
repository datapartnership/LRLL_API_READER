"""Download a small text sample after signing in with the Keycloak browser flow."""

from ddplrll_reader import DdplrllDatasetClient, Settings, preview_jsonld, print_token_user
from ddplrll_reader.auth import login

API_BASE_URL = "http://localhost:8080"
OUTPUT_DIR = "./output/text"

KEYCLOAK_URL = "http://localhost:8081"
REALM = "chambo"
CLIENT_ID = "chambo-frontend"
SCOPES = "openid profile email"
CALLBACK_PORT = 5000  # must match a redirect URI registered on the Keycloak client


def main() -> None:
    try:
        # Also saves the access token to tokens.json, so the *Token scripts can reuse it.
        tokens = login(KEYCLOAK_URL, REALM, CLIENT_ID, SCOPES, CALLBACK_PORT, jupyter=False)
    except (ValueError, RuntimeError, TimeoutError) as exc:
        raise SystemExit(str(exc)) from exc

    settings = Settings(
        api_base_url=API_BASE_URL,
        api_token=tokens["access_token"],
        output_dir=OUTPUT_DIR,
        verify_ssl=False,
    )
    print("Signed in", flush=True)
    print_token_user(tokens["access_token"])
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
