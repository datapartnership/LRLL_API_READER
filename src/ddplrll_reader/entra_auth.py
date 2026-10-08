"""Microsoft Entra ID authentication for the dataset reader."""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class EntraConfig(BaseSettings):
    """Public-client sign-in settings from ENTRA_* environment variables or .env."""

    model_config = SettingsConfigDict(env_prefix="ENTRA_", env_file=".env", extra="ignore")

    tenant_id: str = ""
    client_id: str = ""
    api_scope: str = ""
    callback_port: int = 8081
    spa_redirect_uri: str = "http://localhost:5173/callback"
    spa_timeout_seconds: float = 300.0


def _validate_required_settings(config: EntraConfig) -> None:
    missing = [
        name for name in ("tenant_id", "client_id", "api_scope")
        if not getattr(config, name).strip()
    ]
    if missing:
        names = ", ".join(f"ENTRA_{name.upper()}" for name in missing)
        raise ValueError(f"Set {names} in .env or the environment before signing in.")


def acquire_api_token(config: EntraConfig) -> dict:
    """Get a delegated API access token using MSAL's browser and PKCE flow."""
    _validate_required_settings(config)
    if not 1 <= config.callback_port <= 65535:
        raise ValueError("ENTRA_CALLBACK_PORT must be between 1 and 65535.")

    try:
        from msal import PublicClientApplication
    except ImportError as exc:
        raise RuntimeError("Install project dependencies with: pip install -e .") from exc

    app = PublicClientApplication(
        config.client_id,
        authority=f"https://login.microsoftonline.com/{config.tenant_id}",
    )
    print("Opening your browser for Microsoft Entra sign-in...")
    result = app.acquire_token_interactive(
        scopes=[config.api_scope],
        port=config.callback_port,
    )
    if "access_token" not in result:
        error = result.get("error", "unknown_error")
        description = result.get("error_description", "No access token was returned.")
        raise RuntimeError(f"Microsoft Entra sign-in failed: {error}: {description}")
    return result


def save_token(result: Mapping[str, object], path: str | Path = "tokens.json") -> None:
    """Save the access token as ``{"access_token": "..."}``, with private file permissions."""
    token_path = Path(path)
    payload = {"access_token": result["access_token"]}
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    token_path.chmod(0o600)
    print(f"Access token saved to {token_path}")


def print_token_user(access_token: str) -> None:
    """Display unverified JWT user claims only; never use them for authorization."""
    parts = access_token.split(".")
    if len(parts) != 3:
        print("User unavailable: access token is not a readable JWT.", flush=True)
        return
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.b64decode(payload, altchars=b"-_", validate=True))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        print("User unavailable: access token has an unreadable JWT payload.", flush=True)
        return
    if not isinstance(claims, dict):
        print("User unavailable: access token has no user claims.", flush=True)
        return

    def claim(*names: str) -> str:
        for name in names:
            value = claims.get(name)
            if isinstance(value, str) and value.strip():
                return "".join(char if char.isprintable() else " " for char in value).strip()
        return ""

    name = claim("name")
    username = claim("preferred_username", "upn", "unique_name", "email")
    user = f"{name} ({username})" if name and username and name != username else name or username
    if not user:
        identifier = claim("oid", "sub")
        user = f"User ID: {identifier}" if identifier else ""
    if user:
        print(f"User (from token claims, unverified): {user}", flush=True)
    else:
        print("User unavailable: access token has no user claims.", flush=True)


def login_entra(
    config: EntraConfig | None = None,
    token_file: str | Path = "tokens.json",
) -> dict:
    """Sign in through Entra ID, save the token, and return the MSAL result."""
    result = acquire_api_token(config if config is not None else EntraConfig())
    save_token(result, token_file)
    return result
