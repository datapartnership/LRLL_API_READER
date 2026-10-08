"""Browser-side Entra SPA authentication with a loopback token handoff."""

from __future__ import annotations

import json
import math
import secrets
import socket
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from typing import TypedDict
from urllib.parse import quote, unquote, urlsplit

from ddplrll_reader.entra_auth import EntraConfig, _validate_required_settings, save_token

_START_PATH = "/_entra/start"
_SCRIPT_PATH = "/_entra/browser.js"
_CONFIG_PATH = "/_entra/config"
_RESULT_PATH = "/_entra/result"
_MAX_PAYLOAD = 32768


class SpaTokenResult(TypedDict):
    """Access-token fields returned by the browser, without refresh or ID tokens."""

    access_token: str
    token_type: str
    expires_in: int
    scope: str


@dataclass(frozen=True)
class _SpaSettings:
    port: int
    origin: str
    callback_path: str
    browser_config: dict[str, str]


def _validate_config(config: EntraConfig) -> _SpaSettings:
    _validate_required_settings(config)
    message = (
        "ENTRA_SPA_REDIRECT_URI must be an exact registered SPA redirect URI like "
        "http://localhost:5173/callback, with an explicit port and no query or fragment."
    )
    try:
        uri = urlsplit(config.spa_redirect_uri)
        port = uri.port
    except ValueError as exc:
        raise ValueError(message) from exc
    if (
        uri.scheme != "http"
        or uri.hostname != "localhost"
        or port is None
        or not 1 <= port <= 65535
        or uri.netloc != f"localhost:{port}"
        or "?" in config.spa_redirect_uri
        or "#" in config.spa_redirect_uri
        or config.spa_redirect_uri != uri.geturl()
        or uri.path.startswith("/_entra/")
        or "\\" in uri.path
        or any(segment in (".", "..") for segment in unquote(uri.path).split("/"))
    ):
        raise ValueError(message)
    if not math.isfinite(config.spa_timeout_seconds) or not 1 <= config.spa_timeout_seconds <= 1800:
        raise ValueError("ENTRA_SPA_TIMEOUT_SECONDS must be between 1 and 1800.")
    if len(config.api_scope.split()) != 1:
        raise ValueError("ENTRA_API_SCOPE must contain one delegated API scope.")
    authority = (
        "https://login.microsoftonline.com/"
        + quote(config.tenant_id.strip(), safe="")
        + "/oauth2/v2.0"
    )
    return _SpaSettings(
        port=port,
        origin=f"http://localhost:{port}",
        callback_path=uri.path or "/",
        browser_config={
            "authorizeUrl": f"{authority}/authorize",
            "tokenUrl": f"{authority}/token",
            "clientId": config.client_id.strip(),
            "scope": config.api_scope.strip(),
            "redirectUri": config.spa_redirect_uri,
        },
    )


class _SpaServer(HTTPServer):
    def __init__(self, settings: _SpaSettings, timeout: float) -> None:
        self.settings = settings
        self.handoff_key = secrets.token_urlsafe(32)
        self.result: SpaTokenResult | None = None
        self.error: str | None = None
        self.deadline = time.monotonic() + timeout
        try:
            self.page = files("ddplrll_reader").joinpath("entra_spa.html").read_bytes()
            self.script = files("ddplrll_reader").joinpath("entra_spa.js").read_bytes()
        except OSError as exc:
            raise RuntimeError(
                "Could not load SPA browser resources. Reinstall with: pip install -e ."
            ) from exc
        super().__init__(("127.0.0.1", settings.port), _SpaHandler)

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(max(0.001, min(2.0, self.deadline - time.monotonic())))
        return connection, address


class _SpaHandler(BaseHTTPRequestHandler):
    server: _SpaServer

    def log_message(self, format: str, *args: object) -> None:
        # Default HTTP logging includes callback URLs containing authorization codes.
        pass

    def _reply(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; "
            "connect-src 'self' https://login.microsoftonline.com; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # A tab can close after sending a handoff; the accepted result remains valid.
            return

    def _valid_host(self) -> bool:
        if self.headers.get("Host") != urlsplit(self.server.settings.origin).netloc:
            self._reply(403, b"Invalid localhost host.")
            return False
        return True

    def _valid_key(self) -> bool:
        key = self.headers.get("X-Entra-Handoff", "")
        if not secrets.compare_digest(key.encode("utf-8"), self.server.handoff_key.encode("ascii")):
            self._reply(403, b"Invalid sign-in handoff credential.")
            return False
        return True

    def do_GET(self) -> None:
        if not self._valid_host():
            return
        try:
            path = urlsplit(self.path).path
        except ValueError:
            self._reply(400, b"Invalid sign-in route.")
            return
        if path in (_START_PATH, self.server.settings.callback_path):
            self._reply(200, self.server.page, "text/html")
        elif path == _SCRIPT_PATH:
            self._reply(200, self.server.script, "text/javascript")
        elif path == _CONFIG_PATH:
            if self._valid_key():
                self._reply(
                    200,
                    json.dumps(self.server.settings.browser_config).encode("utf-8"),
                    "application/json",
                )
        else:
            self._reply(404, b"Unknown sign-in route.")

    def do_POST(self) -> None:
        if not self._valid_host():
            return
        if self.path != _RESULT_PATH:
            self._reply(404, b"Unknown sign-in route.")
            return
        if self.headers.get("Origin") != self.server.settings.origin:
            self._reply(403, b"Invalid sign-in handoff origin.")
            return
        if not self._valid_key():
            return
        if self.server.result is not None or self.server.error is not None:
            self._reply(409, b"This sign-in attempt has already completed.")
            return
        if self.headers.get("Content-Type") != "application/json":
            self._reply(415, b"Sign-in handoff requires application/json.")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._reply(400, b"Invalid handoff content length.")
            return
        if not 0 < size <= _MAX_PAYLOAD or self.headers.get("Transfer-Encoding"):
            self._reply(400, b"Invalid handoff payload size or transfer encoding.")
            return
        try:
            payload = json.loads(self.rfile.read(size))
        except (json.JSONDecodeError, UnicodeDecodeError, TimeoutError):
            self._reply(400, b"Invalid or incomplete sign-in handoff JSON.")
            return
        if not isinstance(payload, dict):
            self._reply(400, b"Sign-in handoff must be a JSON object.")
            return
        if isinstance(payload.get("error"), str) and payload["error"]:
            description = payload.get("error_description")
            if not isinstance(description, str):
                self._reply(400, b"Sign-in error requires a description.")
                return
            self.server.error = f"{payload['error']}: {description}"
        else:
            token = payload.get("access_token")
            token_type = payload.get("token_type")
            expires_in = payload.get("expires_in")
            scope = payload.get("scope")
            if (
                not isinstance(token, str)
                or not token.strip()
                or not isinstance(token_type, str)
                or token_type.lower() != "bearer"
                or type(expires_in) is not int
                or expires_in <= 0
                or not isinstance(scope, str)
                or not scope.strip()
            ):
                self._reply(400, b"Invalid access-token result.")
                return
            self.server.result = {
                "access_token": token,
                "token_type": token_type,
                "expires_in": expires_in,
                "scope": scope,
            }
        self._reply(200, b'{"accepted":true}', "application/json")


def acquire_api_token_spa(config: EntraConfig) -> SpaTokenResult:
    """Acquire an API token in a real browser using a registered localhost SPA callback."""
    settings = _validate_config(config)
    try:
        server = _SpaServer(settings, config.spa_timeout_seconds)
    except OSError as exc:
        raise RuntimeError(
            f"Could not start the SPA sign-in server on localhost:{settings.port}: {exc}. "
            "Free that port or configure another exact registered SPA redirect URI."
        ) from exc
    with server:
        print(f"Opening your browser for Microsoft Entra SPA sign-in ({settings.origin})...")
        start_url = f"{settings.origin}{_START_PATH}#{server.handoff_key}"
        try:
            opened = webbrowser.open(start_url, new=1)
        except webbrowser.Error as exc:
            raise RuntimeError(f"Could not open the sign-in browser: {exc}") from exc
        if not opened:
            raise RuntimeError("Could not open the sign-in browser. Configure a default browser.")
        while server.result is None and server.error is None:
            remaining = server.deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "Microsoft Entra SPA sign-in timed out. Complete sign-in in the browser "
                    "or increase ENTRA_SPA_TIMEOUT_SECONDS."
                )
            server.timeout = min(0.25, remaining)
            server.handle_request()
        if server.error is not None:
            raise RuntimeError(f"Microsoft Entra SPA sign-in failed: {server.error}")
        if server.result is None:
            raise RuntimeError("Microsoft Entra SPA sign-in returned no access token.")
        return server.result


def login_entra_spa(
    config: EntraConfig | None = None,
    token_file: str | Path = "tokens.json",
) -> SpaTokenResult:
    """Sign in through the SPA browser flow and explicitly save the API token."""
    result = acquire_api_token_spa(config if config is not None else EntraConfig())
    save_token(result, token_file)
    return result
