import os

import pytest

from pyrit_eval_runner.cli import (
    build_parser,
    _resolve_optional_setting,
    _resolve_required_setting,
)


def test_required_setting_prefers_arg(monkeypatch):
    monkeypatch.delenv("TARGET_ENDPOINT", raising=False)
    value = _resolve_required_setting("from-arg", "TARGET_ENDPOINT")
    assert value == "from-arg"
    assert os.environ["TARGET_ENDPOINT"] == "from-arg"


def test_required_setting_uses_env(monkeypatch):
    monkeypatch.setenv("TARGET_ENDPOINT", "from-env")
    value = _resolve_required_setting(None, "TARGET_ENDPOINT")
    assert value == "from-env"


def test_required_setting_missing_raises(monkeypatch):
    monkeypatch.delenv("MISSING_ENV", raising=False)
    with pytest.raises(SystemExit) as exc:
        _resolve_required_setting(None, "MISSING_ENV")
    assert exc.value.code == 2


def test_optional_setting_prefers_arg(monkeypatch):
    monkeypatch.delenv("OPENAI_CHAT_ENDPOINT", raising=False)
    value = _resolve_optional_setting("https://from-arg", "OPENAI_CHAT_ENDPOINT", "https://default")
    assert value == "https://from-arg"
    assert os.environ["OPENAI_CHAT_ENDPOINT"] == "https://from-arg"


def test_optional_setting_uses_env(monkeypatch):
    monkeypatch.setenv("OPENAI_CHAT_ENDPOINT", "https://from-env")
    value = _resolve_optional_setting(None, "OPENAI_CHAT_ENDPOINT", "https://default")
    assert value == "https://from-env"


def test_optional_setting_uses_default(monkeypatch):
    monkeypatch.delenv("OPENAI_CHAT_MODEL", raising=False)
    value = _resolve_optional_setting(None, "OPENAI_CHAT_MODEL", "gpt-default")
    assert value == "gpt-default"
    assert os.environ["OPENAI_CHAT_MODEL"] == "gpt-default"


def test_parser_accepts_auth_flags():
    parser = build_parser()
    args = parser.parse_args(
        [
            "run",
            "--config",
            "config.yaml",
            "--target-endpoint",
            "https://example.com",
            "--auth-token",
            "token-value",
            "--openai-api-key",
            "sk-test",
            "--openai-chat-endpoint",
            "https://chat.example.com",
            "--openai-chat-model",
            "gpt-test",
        ]
    )

    assert args.target_endpoint == "https://example.com"
    assert args.auth_token == "token-value"
    assert args.openai_api_key == "sk-test"
    assert args.openai_chat_endpoint == "https://chat.example.com"
    assert args.openai_chat_model == "gpt-test"
