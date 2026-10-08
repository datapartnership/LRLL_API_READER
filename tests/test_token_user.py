import base64
import json
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest

from ddplrll_reader import Settings, print_token_user


def token(claims: object) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{payload}.synthetic-signature"


@pytest.mark.parametrize(
    "claims, expected",
    [
        (
            {"name": "Test User", "preferred_username": "test@example.org"},
            "Test User (test@example.org)",
        ),
        ({"upn": "test@example.org"}, "test@example.org"),
        ({"unique_name": "test@example.org"}, "test@example.org"),
        ({"email": "test@example.org"}, "test@example.org"),
        ({"name": "Test User"}, "Test User"),
        ({"name": "same", "preferred_username": "same"}, "same"),
        ({"oid": "test-object-id", "sub": "test-subject"}, "User ID: test-object-id"),
        ({"sub": "test-subject"}, "User ID: test-subject"),
        ({"preferred_username": 123, "upn": "test@example.org"}, "test@example.org"),
    ],
)
def test_prints_user_without_token(claims, expected, capsys):
    access_token = token(claims)
    print_token_user(access_token)
    output = capsys.readouterr().out
    assert output == f"User (from token claims, unverified): {expected}\n"
    assert access_token not in output
    assert "synthetic-signature" not in output


@pytest.mark.parametrize(
    "access_token",
    [
        "opaque-token",
        "e30.!!!.signature",
        "e30._w.signature",
        token([]),
        token({}),
        token({"name": None, "preferred_username": {}}),
    ],
)
def test_unavailable_identity_does_not_break_download(access_token, capsys):
    print_token_user(access_token)
    output = capsys.readouterr().out
    assert output.startswith("User unavailable:")
    assert access_token not in output


def test_strips_terminal_controls(capsys):
    print_token_user(token({"name": "Test\nUser\x1b[31m"}))
    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert output.count("\n") == 1


@pytest.mark.parametrize("script_name", ["textWithSpaAuth.py", "textWithSpaToken.py"])
def test_text_examples_print_user_without_changing_query(script_name, monkeypatch, capsys):
    access_token = token({"name": "Test User", "upn": "test@example.org"})
    script = Path(__file__).parents[1] / script_name
    main = runpy.run_path(str(script))["main"]
    client = Mock()
    client.run.return_value = Path("synthetic.jsonld")
    factory = Mock(return_value=client)
    monkeypatch.setitem(main.__globals__, "DdplrllDatasetClient", factory)
    monkeypatch.setitem(main.__globals__, "preview_jsonld", Mock())
    monkeypatch.setitem(
        main.__globals__,
        "Settings",
        lambda **kwargs: Settings(_env_file=None, **{**kwargs, "api_token": access_token}),
    )
    if script_name == "textWithSpaAuth.py":
        monkeypatch.setitem(
            main.__globals__,
            "acquire_api_token_spa",
            lambda cfg: {"access_token": access_token},
        )
    main()
    output = capsys.readouterr().out
    assert "Test User (test@example.org)" in output
    assert access_token not in output
    assert client.run.call_args.kwargs["media_type"] == "Text"
    assert client.run.call_args.kwargs["limit"] == 10


@pytest.mark.parametrize(
    "script_name, auth_helper",
    [
        ("soundWithSpaAuth.py", "acquire_api_token_spa"),
        ("soundWithDesktopAuth.py", "acquire_api_token"),
        ("soundWithSpaToken.py", None),
    ],
)
def test_sound_examples_print_user_and_preserve_query(
    script_name, auth_helper, monkeypatch, capsys
):
    access_token = token({"name": "Test User", "upn": "test@example.org"})
    main = runpy.run_path(str(Path(__file__).parents[1] / script_name))["main"]
    client = Mock()
    client.run.return_value = Path("synthetic.jsonld")
    factory = Mock(return_value=client)
    preview = Mock()
    monkeypatch.setitem(main.__globals__, "DdplrllDatasetClient", factory)
    monkeypatch.setitem(main.__globals__, "preview_jsonld", preview)
    monkeypatch.setitem(
        main.__globals__,
        "Settings",
        lambda **kwargs: Settings(_env_file=None, **{**kwargs, "api_token": access_token}),
    )
    if auth_helper:
        acquire = Mock(return_value={"access_token": access_token})
        monkeypatch.setitem(main.__globals__, "EntraConfig", lambda: "synthetic-config")
        monkeypatch.setitem(main.__globals__, auth_helper, acquire)
    main()
    if auth_helper:
        acquire.assert_called_once_with("synthetic-config")
    output = capsys.readouterr().out
    assert "Test User (test@example.org)" in output
    assert access_token not in output
    assert factory.call_args.args[0].auth_token == access_token
    client.run.assert_called_once_with(
        media_type="Audio",
        language="ny",
        year=2026,
        limit=2,
        output_dir="./output/sound",
        download=True,
    )
    preview.assert_called_once_with(Path("synthetic.jsonld"))


@pytest.mark.parametrize("error", [ValueError("missing config"), RuntimeError("sign-in failed")])
def test_spa_sound_auth_failure_does_not_download(error, monkeypatch):
    main = runpy.run_path(str(Path(__file__).parents[1] / "soundWithSpaAuth.py"))["main"]
    factory = Mock()
    monkeypatch.setitem(main.__globals__, "acquire_api_token_spa", Mock(side_effect=error))
    monkeypatch.setitem(main.__globals__, "DdplrllDatasetClient", factory)
    with pytest.raises(SystemExit, match=str(error)):
        main()
    factory.assert_not_called()
