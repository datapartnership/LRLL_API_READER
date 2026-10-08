from __future__ import annotations

import json
import runpy
import shutil
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import httpx
import pytest

from ddplrll_reader import (
    EntraConfig,
    Settings,
    acquire_api_token,
    acquire_api_token_spa,
    login_entra_spa,
)
from ddplrll_reader.entra_spa_auth import _SpaServer, _validate_config

TOKEN = {
    "access_token": "synthetic-test-token",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "api://test-api/access_as_user",
}


def config(**overrides: object) -> EntraConfig:
    values = {
        "tenant_id": "test-tenant",
        "client_id": "test-client",
        "api_scope": TOKEN["scope"],
        **overrides,
    }
    return EntraConfig(_env_file=None, **values)


@pytest.fixture
def server():
    settings = replace(_validate_config(config()), port=0)
    with _SpaServer(settings, 30) as instance:
        port = instance.server_port
        origin = f"http://localhost:{port}"
        instance.settings = replace(
            settings,
            port=port,
            origin=origin,
            browser_config={**settings.browser_config, "redirectUri": f"{origin}/callback"},
        )
        thread = threading.Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        try:
            yield instance
        finally:
            instance.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


def headers(server: _SpaServer) -> dict[str, str]:
    return {
        "Origin": server.settings.origin,
        "X-Entra-Handoff": server.handoff_key,
        "Content-Type": "application/json",
    }


def test_defaults_and_root_callback():
    assert config().spa_redirect_uri == "http://localhost:5173/callback"
    assert config().callback_port == 8081
    settings = _validate_config(config(spa_redirect_uri="http://localhost:5071"))
    assert settings.callback_path == "/"
    assert settings.port == 5071
    assert settings.browser_config["redirectUri"] == "http://localhost:5071"
    assert settings.browser_config["scope"] == TOKEN["scope"]


@pytest.mark.parametrize(
    "uri",
    [
        "https://localhost:5173/callback",
        "http://example.com:5173/callback",
        "http://127.0.0.1:5173/callback",
        "http://localhost/callback",
        "http://user@localhost:5173/callback",
        "http://localhost:0/callback",
        "http://localhost:65536/callback",
        "http://localhost:abc/callback",
        "http://localhost:5173/callback?x=1",
        "http://localhost:5173/callback#fragment",
        "http://localhost:5173/_entra/result",
        "http://localhost:5173/foo/../callback",
        "http://localhost:5173/%2e/callback",
        "http://localhost:5173/foo\\callback",
    ],
)
def test_rejects_invalid_redirect(uri):
    with pytest.raises(ValueError, match="ENTRA_SPA_REDIRECT_URI"):
        _validate_config(config(spa_redirect_uri=uri))


@pytest.mark.parametrize("timeout", [0, -1, 1801, float("nan"), float("inf")])
def test_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="ENTRA_SPA_TIMEOUT_SECONDS"):
        _validate_config(config(spa_timeout_seconds=timeout))


def test_missing_scope_and_multiple_scopes():
    with pytest.raises(ValueError, match="ENTRA_API_SCOPE"):
        _validate_config(config(api_scope=""))
    with pytest.raises(ValueError, match="one delegated API scope"):
        _validate_config(config(api_scope="scope1 scope2"))


def test_missing_browser_resource_is_reported(monkeypatch):
    resource = Mock()
    resource.joinpath.return_value.read_bytes.side_effect = FileNotFoundError("missing asset")
    monkeypatch.setattr("ddplrll_reader.entra_spa_auth.files", lambda package: resource)
    with pytest.raises(RuntimeError, match="Could not load SPA browser resources"):
        acquire_api_token_spa(config())


def test_serves_only_local_routes_and_protects_config(server):
    with httpx.Client(base_url=server.settings.origin, trust_env=False) as client:
        page = client.get("/_entra/start")
        assert page.status_code == 200
        assert 'src="/_entra/browser.js"' in page.text
        assert page.headers["Cache-Control"] == "no-store"
        assert page.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        assert client.get("/callback?code=synthetic&state=test").status_code == 200
        assert client.get("/_entra/browser.js").status_code == 200
        assert client.get("/tokens.json").status_code == 404
        assert client.get("/_entra/config").status_code == 403
        response = client.get("/_entra/config", headers=headers(server))
        assert response.json() == server.settings.browser_config
        assert server.handoff_key not in response.text
        assert client.get("/_entra/start", headers={"Host": "attacker.test"}).status_code == 403


@pytest.mark.parametrize(
    "field,value",
    [
        ("Origin", "http://attacker.test"),
        ("Origin", ""),
        ("X-Entra-Handoff", "incorrect"),
        ("Host", "attacker.test"),
    ],
)
def test_rejects_untrusted_handoff(server, field, value):
    with httpx.Client(base_url=server.settings.origin, trust_env=False) as client:
        response = client.post(
            "/_entra/result",
            headers={**headers(server), field: value},
            json=TOKEN,
        )
        assert response.status_code == 403
        assert server.result is None
        assert server.error is None


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"id_token": "not-an-access-token"},
        {**TOKEN, "access_token": ""},
        {**TOKEN, "token_type": "Basic"},
        {**TOKEN, "expires_in": True},
        {**TOKEN, "expires_in": 0},
        {**TOKEN, "scope": ""},
        {"error": "invalid_client"},
    ],
)
def test_rejects_invalid_result(server, payload):
    with httpx.Client(base_url=server.settings.origin, trust_env=False) as client:
        response = client.post("/_entra/result", headers=headers(server), json=payload)
        assert response.status_code == 400
        assert server.result is None
        assert server.error is None


def test_rejects_malformed_and_oversized_payload(server):
    with httpx.Client(base_url=server.settings.origin, trust_env=False) as client:
        for content in (b"{", b"\xff", b"x" * 32769):
            response = client.post("/_entra/result", headers=headers(server), content=content)
            assert response.status_code == 400
        response = client.post(
            "/_entra/result",
            headers={**headers(server), "Content-Type": "text/plain"},
            content=json.dumps(TOKEN),
        )
        assert response.status_code == 415


def test_accepts_one_token_and_discards_refresh_token(server, capsys):
    with httpx.Client(base_url=server.settings.origin, trust_env=False) as client:
        response = client.post(
            "/_entra/result",
            headers=headers(server),
            json={**TOKEN, "refresh_token": "must-not-return", "id_token": "must-not-return"},
        )
        assert response.status_code == 200
        assert response.json() == {"accepted": True}
        assert server.result == TOKEN
        assert (
            client.post(
                "/_entra/result",
                headers=headers(server),
                json=TOKEN,
            ).status_code
            == 409
        )
    output = capsys.readouterr()
    assert not output.err
    assert TOKEN["access_token"] not in output.out


def test_accepts_error_only_once(server):
    with httpx.Client(base_url=server.settings.origin, trust_env=False) as client:
        response = client.post(
            "/_entra/result",
            headers=headers(server),
            json={"error": "invalid_client", "error_description": "synthetic rejection"},
        )
        assert response.status_code == 200
        assert server.error == "invalid_client: synthetic rejection"
        assert server.result is None
        assert (
            client.post(
                "/_entra/result",
                headers=headers(server),
                json=TOKEN,
            ).status_code
            == 409
        )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def assert_port_closed(port: int) -> None:
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.parametrize(
    "result",
    [
        TOKEN,
        {"error": "access_denied", "error_description": "synthetic cancellation"},
    ],
)
def test_acquisition_result_and_cleanup(monkeypatch, result):
    port = free_port()
    with ThreadPoolExecutor(max_workers=1) as executor:
        requests = []

        def browser_handoff(url, new):
            parsed = urlsplit(url)

            def send():
                with httpx.Client(
                    base_url=f"http://localhost:{port}",
                    trust_env=False,
                ) as client:
                    response = client.post(
                        "/_entra/result",
                        headers={
                            "Origin": f"http://localhost:{port}",
                            "X-Entra-Handoff": parsed.fragment,
                        },
                        json=result,
                    )
                    assert response.status_code == 200

            requests.append(executor.submit(send))
            return True

        monkeypatch.setattr("ddplrll_reader.entra_spa_auth.webbrowser.open", browser_handoff)
        settings = config(spa_redirect_uri=f"http://localhost:{port}/callback")
        if "error" in result:
            with pytest.raises(RuntimeError, match="access_denied: synthetic cancellation"):
                acquire_api_token_spa(settings)
        else:
            assert acquire_api_token_spa(settings) == TOKEN
        requests[0].result(timeout=5)
    assert_port_closed(port)


def test_browser_launch_failure_and_cleanup(monkeypatch):
    port = free_port()
    monkeypatch.setattr("ddplrll_reader.entra_spa_auth.webbrowser.open", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="Could not open"):
        acquire_api_token_spa(config(spa_redirect_uri=f"http://localhost:{port}/callback"))
    assert_port_closed(port)


def test_timeout_and_cleanup(monkeypatch):
    port = free_port()
    monkeypatch.setattr("ddplrll_reader.entra_spa_auth.webbrowser.open", lambda *a, **k: True)
    with pytest.raises(RuntimeError, match="timed out"):
        acquire_api_token_spa(
            config(
                spa_redirect_uri=f"http://localhost:{port}/callback",
                spa_timeout_seconds=1,
            )
        )
    assert_port_closed(port)


def test_interruption_and_cleanup(monkeypatch):
    port = free_port()
    monkeypatch.setattr("ddplrll_reader.entra_spa_auth.webbrowser.open", lambda *a, **k: True)
    monkeypatch.setattr(_SpaServer, "handle_request", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        acquire_api_token_spa(config(spa_redirect_uri=f"http://localhost:{port}/callback"))
    assert_port_closed(port)


def test_port_conflict_does_not_open_browser(monkeypatch):
    opener = Mock()
    monkeypatch.setattr("ddplrll_reader.entra_spa_auth.webbrowser.open", opener)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        with pytest.raises(RuntimeError, match="Free that port"):
            acquire_api_token_spa(
                config(
                    spa_redirect_uri=f"http://localhost:{sock.getsockname()[1]}/callback",
                )
            )
    opener.assert_not_called()


def test_explicit_save_and_existing_token_loading(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ddplrll_reader.entra_spa_auth.acquire_api_token_spa",
        lambda cfg: TOKEN.copy(),
    )
    path = tmp_path / "tokens.json"
    assert login_entra_spa(config(), path) == TOKEN
    assert json.loads(path.read_text()) == {"access_token": TOKEN["access_token"]}
    assert path.stat().st_mode & 0o777 == 0o600
    assert Settings(_env_file=None, token_file=str(path)).auth_token == TOKEN["access_token"]
    assert (
        Settings(
            _env_file=None,
            token_file=str(path),
            api_token="explicit-token",
        ).auth_token
        == "explicit-token"
    )


def test_desktop_flow_is_unchanged(monkeypatch):
    app = Mock()
    app.acquire_token_interactive.return_value = TOKEN.copy()
    factory = Mock(return_value=app)
    monkeypatch.setitem(sys.modules, "msal", SimpleNamespace(PublicClientApplication=factory))
    assert acquire_api_token(config()) == TOKEN
    factory.assert_called_once_with(
        "test-client",
        authority="https://login.microsoftonline.com/test-tenant",
    )
    app.acquire_token_interactive.assert_called_once_with(scopes=[TOKEN["scope"]], port=8081)


def test_spa_text_example_preserves_query_and_uses_in_memory_token(monkeypatch):
    script = Path(__file__).parents[1] / "textWithSpaAuth.py"
    main = runpy.run_path(str(script))["main"]
    client = Mock()
    client.run.return_value = Path("synthetic.jsonld")
    factory = Mock(return_value=client)
    preview = Mock()
    monkeypatch.setitem(main.__globals__, "EntraConfig", config)
    monkeypatch.setitem(main.__globals__, "acquire_api_token_spa", lambda cfg: TOKEN.copy())
    monkeypatch.setitem(main.__globals__, "DdplrllDatasetClient", factory)
    monkeypatch.setitem(main.__globals__, "preview_jsonld", preview)
    main()
    settings = factory.call_args.args[0]
    assert settings.api_token == TOKEN["access_token"]
    assert settings.api_base_url == "https://lrldtmetadataqa.worldbank.org/"
    client.run.assert_called_once_with(
        media_type="Text",
        keyword="malaria",
        limit=10,
        output_dir="./output/text",
        download=True,
    )
    preview.assert_called_once_with(Path("synthetic.jsonld"))


def test_browser_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser JavaScript unit tests.")
    script = Path(__file__).with_name("entra_spa_browser.test.cjs")
    subprocess.run([node, "--test", str(script)], check=True, timeout=30)
