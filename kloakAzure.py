# Keycloak Authorization Code Flow with Local Redirect + PKCE
# ─────────────────────────────────────────────────────────────
# Usage:
#   1. Fill in the CONFIG section below.
#   2. Run:  python keycloak_auth_code_flow.py
#   3. A browser window will open for login.
#   4. After login, the script prints your tokens.
#
# Requirements:  Python 3.7+  (no third-party packages needed)

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import time
import urllib.parse
import urllib.request
import webbrowser

# ──────────────────────────────────────────────────────────────
# CONFIG — edit these values before running
# ──────────────────────────────────────────────────────────────
KEYCLOAK_URL  = "https://lrllkeyclock.azurewebsites.net"   # or your Keycloak host
REALM         = "LowResourceLanguageDataTrust"
CLIENT_ID     = "LRLL-API-ID"
SCOPES        = "openid profile email"
CALLBACK_PORT = 8081                   # local port for the redirect
# ──────────────────────────────────────────────────────────────


# ── PKCE helpers ──────────────────────────────────────────────

def generate_code_verifier() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()

def generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ── Local callback server ──────────────────────────────────────

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.server.callback_params = {k: v[0] for k, v in params.items()}
        body = b"""
        <html><body style="font-family:sans-serif;text-align:center;padding:60px">
        <h2>Login successful!</h2>
        <p>You can close this tab and return to the terminal.</p>
        </body></html>
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def find_free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Could not find a free port in range {preferred}–{preferred + 19}.")


def wait_for_callback(port: int, timeout: int = 120) -> dict:
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.callback_params = None
    server.timeout = 5

    deadline = time.time() + timeout
    while time.time() < deadline:
        server.handle_request()
        if server.callback_params is not None:
            server.server_close()
            return server.callback_params

    server.server_close()
    raise TimeoutError(f"No callback received within {timeout} seconds.")


# ── Token exchange ─────────────────────────────────────────────

def exchange_code_for_tokens(code: str, redirect_uri: str, code_verifier: str) -> dict:
    token_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
    payload = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "client_id":     CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "code":          code,
        "code_verifier": code_verifier,
    }).encode()

    req = urllib.request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ── Main flow ──────────────────────────────────────────────────

def main():
    port = find_free_port(CALLBACK_PORT)
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    code_verifier  = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state          = secrets.token_urlsafe(16)

    auth_url = (
        f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode({
            "client_id":             CLIENT_ID,
            "redirect_uri":          redirect_uri,
            "response_type":         "code",
            "scope":                 SCOPES,
            "state":                 state,
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
        })
    )

    print(f"\n[*] Starting local callback listener on port {port} ...")
    print(f"[*] Opening browser for login ...\n")
    print(f"    If the browser does not open, visit:\n    {auth_url}\n")
    webbrowser.open(auth_url)

    try:
        params = wait_for_callback(port)
    except TimeoutError as e:
        print(f"[!] {e}")
        return

    if "error" in params:
        print(f"[!] Keycloak returned an error: {params['error']}")
        print(f"    Description: {params.get('error_description', 'n/a')}")
        return

    if params.get("state") != state:
        print("[!] State mismatch — possible CSRF attack. Aborting.")
        return

    code = params.get("code")
    if not code:
        print("[!] No authorization code in callback. Aborting.")
        return

    print("[+] Authorization code received.")
    print("[*] Exchanging code for tokens ...")

    try:
        tokens = exchange_code_for_tokens(code, redirect_uri, code_verifier)
    except urllib.error.HTTPError as e:
        print(f"[!] Token exchange failed ({e.code}): {e.read().decode()}")
        return

    print("\n" + "═" * 60)
    print("  TOKEN RESPONSE")
    print("═" * 60)
    print(f"\n  Token type   : {tokens.get('token_type', 'Bearer')}")
    print(f"  Expires in   : {tokens.get('expires_in', '?')}s")
    print(f"\n  Access token :\n  {tokens.get('access_token', '')[:80]}...")

    if tokens.get("id_token"):
        print(f"\n  ID token     :\n  {tokens['id_token'][:80]}...")
    if tokens.get("refresh_token"):
        print(f"\n  Refresh token:\n  {tokens['refresh_token'][:80]}...")

    print("\n  Full response saved to: tokens.json")
    print("═" * 60 + "\n")

    with open("tokens.json", "w") as f:
        json.dump(tokens, f, indent=2)


if __name__ == "__main__":
    main()
