# Keycloak Authorization Code Flow with Local Redirect + PKCE
# ─────────────────────────────────────────────────────────────
# Usage:
#   1. Fill in the CONFIG section below (if needed).
#   2. Run:  python kloakAzure.py
#   3. A browser window will open for login.
#   4. After login, the script prints your tokens and saves tokens.json.
#
# Requirements:  ddplrll-dataset-reader installed
#                (pip install -e . from the project root)

from ddplrll_reader.auth import login

# ──────────────────────────────────────────────────────────────
# CONFIG — edit these values before running
# ──────────────────────────────────────────────────────────────
KEYCLOAK_URL  = "https://lrllkeyclock.azurewebsites.net"   # or your Keycloak host
REALM         = "LowResourceLanguageDataTrust"
CLIENT_ID     = "LRLL-API-ID"
SCOPES        = "openid profile email"
CALLBACK_PORT = 8081                   # local port for the redirect
# ──────────────────────────────────────────────────────────────


# ── Main flow ──────────────────────────────────────────────────

def main() -> None:
    login(KEYCLOAK_URL, REALM, CLIENT_ID, SCOPES, CALLBACK_PORT, jupyter=False)


if __name__ == "__main__":
    main()
