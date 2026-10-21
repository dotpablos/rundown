import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rundown.config import Config, load_config, needs_setup, resolve_paths, save_config
from rundown.engine import Engine
from rundown.web import create_app

HEADERS = {"X-Rundown-Request": "1"}


def client_for(config, path):
    return TestClient(create_app(config=config, config_path=path))


def test_missing_and_empty_config_require_setup(tmp_path):
    path = tmp_path / "config.toml"
    cfg = resolve_paths(Config(), path)
    for empty_file in (False, True):
        if empty_file:
            path.write_text("")
            cfg = load_config(path)
        with client_for(cfg, path) as client:
            result = client.get("/api/config").json()
            assert result["setup_required"] is True
            assert result["token_configured"] is False
            assert client.get("/api/status").json()["setup_required"] is True
            assert client.post("/api/runs", headers=HEADERS).status_code == 409
            assert client.get("/static/settings.js").status_code == 200
            assert client.get("/static/slack-manifest.json").json()["display_information"]["name"] == "Rundown"
    # Merely opening setup must not create/overwrite credentials or defaults.
    assert path.read_text() == ""


def test_save_onboarding_reload_and_no_secret_in_response(tmp_path):
    path = tmp_path / "config.toml"
    cfg = resolve_paths(Config(), path)
    with client_for(cfg, path) as client:
        result = client.post("/api/config", headers=HEADERS, json={
            "slack": {"token": "xoxp-a-new-synthetic-token", "direct_messages": True},
            "ollama": {"model": "my-local-model"},
            "keywords": {"release deadline": 9, 'unicode 🦊 "phrase"': 4},
            "storage": {"summaries_dir": "my summaries"},
        })
        assert result.status_code == 200, result.text
        assert result.json()["setup_required"] is False
        assert result.json()["token_configured"] is True
        assert "xoxp-a-new-synthetic-token" not in result.text
        assert client.app.state.engine.config.ollama.model == "my-local-model"
        assert client.app.state.engine.config.slack.direct_messages is True
        assert client.get("/api/status").json()["setup_required"] is False
        assert "xoxp-a-new-synthetic-token" not in client.get("/api/config").text
    reloaded = load_config(path)
    assert not needs_setup(reloaded)
    assert reloaded.slack.token.get_secret_value() == "xoxp-a-new-synthetic-token"
    assert reloaded.storage.summaries_dir == tmp_path / "my summaries"
    assert reloaded.keywords['unicode 🦊 "phrase"'] == 4
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with client_for(reloaded, path) as client:
        assert client.get("/api/config").json()["setup_required"] is False


def test_blank_token_keeps_environment_reference(config, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("RUNDOWN_SETUP_TOKEN", "xoxp-from-environment")
    save_config(path, config, "env:RUNDOWN_SETUP_TOKEN")
    with client_for(load_config(path), path) as client:
        result = client.post("/api/config", headers=HEADERS, json={"slack": {"token": ""}, "ai": {"provider": "claude_code"}})
        assert result.status_code == 200, result.text
        assert result.json()["config"]["ai"]["provider"] == "claude_code"
        assert "xoxp-from-environment" not in path.read_text()
        assert 'env:RUNDOWN_SETUP_TOKEN' in path.read_text()
        assert client.app.state.engine.config.slack.token.get_secret_value() == "xoxp-from-environment"


def test_blank_token_keeps_existing_literal(config, tmp_path):
    path = tmp_path / "config.toml"
    save_config(path, config, config.slack.token.get_secret_value())
    with client_for(config, path) as client:
        result = client.post("/api/config", headers=HEADERS, json={"slack": {"token": ""}, "keywords": {}})
        assert result.status_code == 200
        assert load_config(path).slack.token.get_secret_value() == "xoxp-test-secret"
        assert load_config(path).keywords == {}
        assert client.post("/api/config", headers=HEADERS, json={"slack": {"token": "xoxp-replacement"}}).status_code == 200
        assert load_config(path).slack.token.get_secret_value() == "xoxp-replacement"


@pytest.mark.parametrize("payload", [
    {"ai": {"provider": "xoxp-do-not-echo"}},
    {"slack": {"token": ["xoxp-do-not-echo"]}},
    {"storage": {"timezone": "not/a-zone"}},
    {"ollama": {"base_url": "http://external.example"}},
    {"slack": {"token": "wrong-token"}},
    {"keywords": {"bad": -1}},
    {"unknown": {}},
])
def test_invalid_settings_never_overwrite_or_echo_secrets(config, tmp_path, payload):
    path = tmp_path / "config.toml"
    save_config(path, config, config.slack.token.get_secret_value())
    before = path.read_text()
    with client_for(config, path) as client:
        result = client.post("/api/config", headers=HEADERS, json=payload)
        assert result.status_code == 422
        assert "xoxp-do-not-echo" not in result.text
        assert path.read_text() == before


def test_save_has_same_request_guard_as_runs(config, tmp_path):
    with client_for(config, tmp_path / "config.toml") as client:
        assert client.post("/api/config", json={}).status_code == 403
        assert client.post("/api/config", json={}, headers={**HEADERS, "Origin": "https://untrusted.example"}).status_code == 403
        result = client.post("/api/config", content='{"token":"xoxp-do-not-echo"', headers={**HEADERS, "Content-Type": "application/json"})
        assert result.status_code == 422
        assert "xoxp-do-not-echo" not in result.text


def test_settings_blocked_while_run_active_and_history_preserved(engine, tmp_path):
    path = tmp_path / "config.toml"
    save_config(path, engine.config, engine.config.slack.token.get_secret_value())
    before = path.read_text()
    run_id = engine.begin()
    with TestClient(create_app(engine=engine, config_path=path)) as client:
        try:
            result = client.post("/api/config", headers=HEADERS, json={"keywords": {"release": 10}})
            assert result.status_code == 409
            assert path.read_text() == before
            assert client.app.state.engine is engine
        finally:
            engine.execute(run_id)
        assert client.post("/api/config", headers=HEADERS, json={"keywords": {"release": 10}}).status_code == 200
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "completed"
        date = client.get("/api/dates").json()[0]["date"]
        assert len(client.get("/api/digests", params={"date": date}).json()[0]["channels"]) == 2


def test_disk_save_failure_keeps_old_config_and_engine(config, tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(path, config, config.slack.token.get_secret_value())
    before = path.read_text()
    with client_for(config, path) as client:
        old_engine = client.app.state.engine
        monkeypatch.setattr("rundown.web.save_config", lambda *args: (_ for _ in ()).throw(OSError("disk error")))
        assert client.post("/api/config", headers=HEADERS, json={"keywords": {"changed": 1}}).status_code == 422
        assert path.read_text() == before
        assert client.app.state.engine is old_engine
        assert not old_engine.is_busy()


def test_serve_missing_file_starts_setup(tmp_path, monkeypatch):
    from rundown.__main__ import main
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))
    path = tmp_path / "new" / "config.toml"
    assert main(["serve", "--config", str(path)]) == 0
    with TestClient(captured["app"]) as client:
        assert client.get("/api/config").json()["setup_required"] is True
    assert not path.exists()


def test_setup_assets_and_controls_are_served(config, tmp_path):
    with client_for(config, tmp_path / "config.toml") as client:
        page = client.get("/")
        assert page.status_code == 200
        for control in ("theme-toggle", "dev-toggle", "dev-exit", "token-reveal", "slack-check", "provider-check", "settings-recheck", "settings-continue"):
            assert f'id="{control}"' in page.text
        assert '<main id="dashboard" hidden>' in page.text
        assert client.get("/static/theme.js").status_code == 200
        assert client.get("/static/demo.js").status_code == 200
        assert "YOUR DAILY SIGNAL" not in page.text
        assert "LESS SCROLLING" not in page.text
        assert "script-src 'self'" in page.headers["Content-Security-Policy"]


def test_connection_indicators_report_independent_redacted_failures(engine, tmp_path, monkeypatch):
    from rundown.providers import ProviderFailure
    from rundown.slack import SlackFailure

    with TestClient(create_app(engine=engine, config_path=tmp_path / "config.toml")) as client:
        monkeypatch.setattr(engine.provider, "check", lambda: (_ for _ in ()).throw(ProviderFailure("Model unavailable")))
        response = client.get("/api/status?check=true").json()["readiness"]
        assert response["slack"]["ready"] is True
        assert response["provider"] == {"ready": False, "message": "Model unavailable"}
        assert response["ready"] is False
        monkeypatch.setattr(engine.source, "check", lambda: (_ for _ in ()).throw(SlackFailure("Invalid token xoxp-test-secret")))
        response = client.get("/api/status?check=true")
        assert response.json()["readiness"]["slack"]["ready"] is False
        assert "xoxp-test-secret" not in response.text
        assert response.json()["setup_required"] is False
