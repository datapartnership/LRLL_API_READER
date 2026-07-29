"""Keycloak PKCE authorization helpers for the DDPLRLL Dataset Reader.

Two public entry points
-----------------------
login()      Local callback-server flow (kloakLocal_notebook, kloakAzure.py).
             Starts a temporary HTTP server on 127.0.0.1 so Keycloak can redirect
             back automatically — no manual copy-paste required.

login_oob()  Out-of-band flow (kloakAzure_notebook, remote Jupyter servers).
             Displays a login link, then waits for you to paste the redirect URL
             from the browser address bar.

Both functions save the tokens to *token_file* (default ``tokens.json``) and
return the raw token response dict.

Requirements:  Python 3.7+ (stdlib only).
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def generate_code_verifier() -> str:
    """Return a 32-byte, URL-safe base64-encoded PKCE code verifier."""
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()


def generate_code_challenge(verifier: str) -> str:
    """Return the S256 PKCE code challenge for *verifier*."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# Local callback server helpers  (used by login())
# ---------------------------------------------------------------------------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """One-shot HTTP handler that stores the /callback query params on the server."""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        self.server.callback_params = params  # type: ignore[attr-defined]

        body = (
            b"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            b"<h2>Login successful!</h2>"
            b"<p>You can close this tab and return to the notebook / terminal.</p>"
            b"</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:  # suppress access-log noise
        pass


def find_free_port(preferred: int, search_range: int = 20) -> int:
    """Return the first free port starting at *preferred* (searches up to +20)."""
    for port in range(preferred, preferred + search_range):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"Could not find a free port in range {preferred}–{preferred + search_range - 1}."
    )


def _wait_for_callback(port: int, timeout: int = 300) -> dict:
    """Block until an HTTP GET arrives at the callback server and return its query params."""
    try:
        server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as exc:
        raise RuntimeError(
            f"Port {port} is already in use.\n"
            f"Either free the port or change CALLBACK_PORT to an available port\n"
            f"and update the matching redirect URI in your Keycloak client settings."
        ) from exc
    server.callback_params = None  # type: ignore[attr-defined]
    server.timeout = 5

    deadline = time.time() + timeout
    while time.time() < deadline:
        server.handle_request()
        if server.callback_params is not None:
            server.server_close()
            return server.callback_params  # type: ignore[return-value]

    server.server_close()
    raise TimeoutError(f"No Keycloak callback received within {timeout} seconds.")


# ---------------------------------------------------------------------------
# Token exchange  (shared by both flows)
# ---------------------------------------------------------------------------

def _exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: str,
    keycloak_url: str,
    realm: str,
    client_id: str,
    verify_ssl: bool = True,
) -> dict:
    """POST to Keycloak's token endpoint and return the parsed JSON response."""
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"
    payload = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        }
    ).encode()
    req = urllib.request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    ssl_ctx: ssl.SSLContext | None = None
    if not verify_ssl:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ssl_ctx) as resp:
        return json.loads(resp.read())


def _print_token_summary(tokens: dict) -> None:
    sep = "=" * 60
    print(f"\n{sep}\n  TOKEN RESPONSE\n{sep}")
    print(f"  Token type  : {tokens.get('token_type', 'Bearer')}")
    print(f"  Expires in  : {tokens.get('expires_in', '?')}s")
    print(f"\n  Access token:\n  {tokens.get('access_token', '')[:80]}...")
    if tokens.get("id_token"):
        print(f"\n  ID token    :\n  {tokens['id_token'][:80]}...")
    if tokens.get("refresh_token"):
        print(f"\n  Refresh token:\n  {tokens['refresh_token'][:80]}...")
    print(f"{sep}")


def _save_tokens(tokens: dict, token_file: str) -> None:
    with open(token_file, "w") as fh:
        json.dump(tokens, fh, indent=2)
    print(f"\n  Tokens saved to: {token_file}")
    print("\n[+] Done. Run  ddplrll-reader run  to query the API.")


# ---------------------------------------------------------------------------
# Public entry point — local callback-server flow
# ---------------------------------------------------------------------------

def login(
    keycloak_url: str,
    realm: str,
    client_id: str,
    scopes: str = "openid profile email",
    callback_port: int = 8081,
    token_file: str = "tokens.json",
    jupyter: bool = True,
    verify_ssl: bool = True,
) -> dict:
    """Authenticate via Keycloak using PKCE and a local HTTP callback server.

    Finds a free port, opens your browser at the Keycloak login page, waits for
    the redirect callback, exchanges the authorization code for tokens, saves them
    to *token_file*, and returns the token response dict.

    Parameters
    ----------
    keycloak_url:
        Base URL of the Keycloak server (e.g. ``"https://my-keycloak.example.com"``).
    realm:
        Keycloak realm name.
    client_id:
        Public OIDC client ID registered in the realm.
    scopes:
        Space-separated OAuth scopes (default: ``"openid profile email"``).
    callback_port:
        Preferred local port for the redirect URI (default: 8081).
        A higher port is tried automatically if this one is busy.
    token_file:
        Path where the token JSON is saved (default: ``"tokens.json"``).
    jupyter:
        When ``True`` (default), displays an HTML login button via IPython.
        Set to ``False`` when running outside Jupyter.
    verify_ssl:
        Set to ``False`` to skip SSL certificate verification when exchanging
        the authorization code for tokens (e.g. behind a corporate proxy).

    Returns
    -------
    dict
        The raw token response from Keycloak.
    """
    # Use the exact port — Keycloak redirect URIs must be pre-registered and match exactly.
    port = callback_port
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(16)

    auth_url = (
        f"{keycloak_url}/realms/{realm}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scopes,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    if jupyter:
        try:
            from IPython.display import HTML, display  # type: ignore[import]

            display(
                HTML(
                    "<div style='font-family:sans-serif;padding:12px;border:1px solid #ccc;"
                    "border-radius:6px;max-width:700px'>"
                    "<b>Log in via Keycloak</b><br><br>"
                    "Browser should open automatically. If not, use the link below:<br><br>"
                    f"<a href='{auth_url}' target='_blank' "
                    "style='background:#0066cc;color:white;padding:8px 16px;"
                    "border-radius:4px;text-decoration:none;font-size:14px'>"
                    "&#128274;&nbsp; Click here to log in"
                    "</a><br><br>"
                    "<small>After login the browser redirects to the local callback server "
                    f"(<code>{redirect_uri}</code>). "
                    "The page will confirm success and this cell will continue automatically."
                    "</small></div>"
                )
            )
        except ImportError:
            pass

    webbrowser.open(auth_url)
    print(f"[*] Callback server listening on {redirect_uri}")
    print("[*] Waiting for Keycloak callback (timeout: 5 min) ...")

    params = _wait_for_callback(port)

    if "error" in params:
        raise RuntimeError(
            f"Keycloak returned an error: {params['error']}\n"
            f"Description: {params.get('error_description', 'n/a')}"
        )
    if params.get("state") != state:
        raise ValueError(
            "State mismatch — possible CSRF. "
            "Re-run this cell to generate a fresh login link and try again."
        )

    auth_code = params.get("code")
    if not auth_code:
        raise ValueError("No 'code' parameter in callback. Did the browser redirect correctly?")

    print(f"[+] Authorization code captured ({auth_code[:12]}...)")
    print("[*] Exchanging code for tokens ...")

    try:
        tokens = _exchange_code_for_tokens(
            auth_code, redirect_uri, code_verifier, keycloak_url, realm, client_id,
            verify_ssl=verify_ssl,
        )
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Token exchange failed ({exc.code}): {exc.read().decode()}"
        ) from exc

    _print_token_summary(tokens)
    _save_tokens(tokens, token_file)
    return tokens


# ---------------------------------------------------------------------------
# Public entry point — out-of-band (OOB) flow for remote Jupyter servers
# ---------------------------------------------------------------------------

def login_oob(
    keycloak_url: str,
    realm: str,
    client_id: str,
    scopes: str = "openid profile email",
    callback_port: int = 8082,
    token_file: str = "tokens.json",
    jupyter: bool = True,
    verify_ssl: bool = True,
) -> dict:
    """Authenticate via Keycloak using PKCE and manual URL copy-paste (OOB).

    Generates the auth URL, displays it (with an HTML login button in Jupyter),
    then waits for you to paste the full redirect URL from your browser's address
    bar.  Use this when Jupyter runs on a remote server where ``http://127.0.0.1``
    is not reachable from your browser.

    After clicking the login link your browser is redirected to
    ``http://127.0.0.1:{callback_port}/callback?code=...`` which shows a
    *connection error* — this is expected.  Copy the full URL and paste it into
    the input prompt that appears below the login button.

    Parameters
    ----------
    keycloak_url, realm, client_id, scopes, callback_port, token_file:
        Same as :func:`login`.
    jupyter:
        When ``True`` (default), displays an HTML login button via IPython.

    Returns
    -------
    dict
        The raw token response from Keycloak.
    """
    redirect_uri = f"http://127.0.0.1:{callback_port}/callback"

    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(16)

    auth_url = (
        f"{keycloak_url}/realms/{realm}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scopes,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    if jupyter:
        try:
            from IPython.display import HTML, display  # type: ignore[import]

            display(
                HTML(
                    "<div style='font-family:sans-serif;padding:12px;border:1px solid #ccc;"
                    "border-radius:6px;max-width:700px'>"
                    "<b>Step 1 — Log in via Keycloak</b><br><br>"
                    f"<a href='{auth_url}' target='_blank' "
                    "style='background:#0066cc;color:white;padding:8px 16px;"
                    "border-radius:4px;text-decoration:none;font-size:14px'>"
                    "&#128274;&nbsp; Click here to log in"
                    "</a><br><br>"
                    "<small>"
                    "After login your browser redirects to "
                    f"<code>http://127.0.0.1:{callback_port}/callback?code=...</code><br>"
                    "That page shows a <b>connection error</b> — this is expected.<br>"
                    "<b>Copy the full URL</b> from the address bar, "
                    "paste it into the input box below, and press Enter."
                    "</small>"
                    "<hr style='margin:10px 0'>"
                    "<details>"
                    "<summary style='cursor:pointer;font-size:12px'>"
                    "Cannot click the button? Expand for the plain URL"
                    "</summary>"
                    f"<code style='word-break:break-all;font-size:11px'>{auth_url}</code>"
                    "</details></div>"
                )
            )
        except ImportError:
            print(f"[*] Log in at:\n    {auth_url}\n")

    raw_callback_url = input("Paste the redirect URL here: ").strip()

    parsed = urllib.parse.urlparse(raw_callback_url)
    params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    if "error" in params:
        raise RuntimeError(
            f"Keycloak returned an error: {params['error']}\n"
            f"Description: {params.get('error_description', 'n/a')}"
        )
    if params.get("state") != state:
        raise ValueError(
            "State mismatch — possible CSRF. "
            "Re-run this cell to generate a fresh login link and try again."
        )

    auth_code = params.get("code")
    if not auth_code:
        raise ValueError("No 'code' parameter in URL. Did you paste the correct URL?")

    print(f"[+] Authorization code captured ({auth_code[:12]}...)")
    print("[*] Exchanging code for tokens ...")

    try:
        tokens = _exchange_code_for_tokens(
            auth_code, redirect_uri, code_verifier, keycloak_url, realm, client_id,
            verify_ssl=verify_ssl,
        )
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Token exchange failed ({exc.code}): {exc.read().decode()}"
        ) from exc

    _print_token_summary(tokens)
    _save_tokens(tokens, token_file)
    return tokens


# ---------------------------------------------------------------------------
# Two-step OOB helpers — avoids input() for VS Code notebooks
# ---------------------------------------------------------------------------

def login_oob_begin(
    keycloak_url: str,
    realm: str,
    client_id: str,
    scopes: str = "openid profile email",
    callback_port: int = 8082,
    jupyter: bool = True,
) -> dict:
    """Step 1 of the OOB flow: generate PKCE parameters and display the login link.

    Returns a session dict that must be passed unchanged to
    :func:`login_oob_complete` in the next cell.

    Parameters
    ----------
    keycloak_url, realm, client_id, scopes, callback_port:
        Same as :func:`login_oob`.
    jupyter:
        When ``True`` (default), displays an HTML login button via IPython.
    """
    redirect_uri = f"http://127.0.0.1:{callback_port}/callback"

    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(16)

    auth_url = (
        f"{keycloak_url}/realms/{realm}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scopes,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    if jupyter:
        try:
            from IPython.display import HTML, display  # type: ignore[import]

            display(
                HTML(
                    "<div style='font-family:sans-serif;padding:12px;border:1px solid #ccc;"
                    "border-radius:6px;max-width:700px'>"
                    "<b>Step 1 — Log in via Keycloak</b><br><br>"
                    f"<a href='{auth_url}' target='_blank' "
                    "style='background:#0066cc;color:white;padding:8px 16px;"
                    "border-radius:4px;text-decoration:none;font-size:14px'>"
                    "&#128274;&nbsp; Click here to log in"
                    "</a><br><br>"
                    "<small>"
                    "After login your browser redirects to "
                    f"<code>http://127.0.0.1:{callback_port}/callback?code=...</code><br>"
                    "That page shows a <b>connection error</b> — this is expected.<br>"
                    "<b>Copy the full URL</b> from the address bar, paste it into "
                    "<code>REDIRECT_URL</code> in the next cell, and run that cell."
                    "</small>"
                    "<hr style='margin:10px 0'>"
                    "<details>"
                    "<summary style='cursor:pointer;font-size:12px'>"
                    "Cannot click the button? Expand for the plain URL"
                    "</summary>"
                    f"<code style='word-break:break-all;font-size:11px'>{auth_url}</code>"
                    "</details></div>"
                )
            )
        except ImportError:
            print(f"[*] Log in at:\n    {auth_url}\n")
            print("Copy the redirect URL from your browser and paste it in the next cell.")

    return {
        "_oob": True,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "state": state,
        "keycloak_url": keycloak_url,
        "realm": realm,
        "client_id": client_id,
    }


def login_oob_complete(
    session: dict,
    redirect_url: str,
    token_file: str = "tokens.json",
    verify_ssl: bool = True,
) -> dict:
    """Step 2 of the OOB flow: exchange the authorization code for tokens.

    Parameters
    ----------
    session:
        The dict returned by :func:`login_oob_begin`.
    redirect_url:
        The full redirect URL copied from the browser's address bar after login.
        Looks like ``http://127.0.0.1:8082/callback?code=...&state=...``.
    token_file:
        Path where the token JSON is saved (default: ``"tokens.json"``).
    verify_ssl:
        Set to ``False`` to skip SSL certificate verification (e.g. behind a proxy).
    """
    if not redirect_url or not redirect_url.strip():
        raise ValueError(
            "redirect_url is empty. Paste the full URL from your browser's address bar."
        )

    parsed = urllib.parse.urlparse(redirect_url.strip())
    params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    if "error" in params:
        raise RuntimeError(
            f"Keycloak returned an error: {params['error']}\n"
            f"Description: {params.get('error_description', 'n/a')}"
        )
    if params.get("state") != session["state"]:
        raise ValueError(
            "State mismatch — the session has expired or the URL is from a different login.\n"
            "Re-run the previous cell to generate a fresh login link and try again."
        )

    auth_code = params.get("code")
    if not auth_code:
        raise ValueError("No 'code' parameter in URL. Did you paste the correct URL?")

    print(f"[+] Authorization code captured ({auth_code[:12]}...)")
    print("[*] Exchanging code for tokens ...")

    try:
        tokens = _exchange_code_for_tokens(
            auth_code,
            session["redirect_uri"],
            session["code_verifier"],
            session["keycloak_url"],
            session["realm"],
            session["client_id"],
            verify_ssl=verify_ssl,
        )
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Token exchange failed ({exc.code}): {exc.read().decode()}"
        ) from exc

    _print_token_summary(tokens)
    _save_tokens(tokens, token_file)
    return tokens
