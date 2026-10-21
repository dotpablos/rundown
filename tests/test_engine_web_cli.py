import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from rundown.__main__ import main
from rundown.engine import Busy, Engine
from rundown.models import Message
from rundown.web import create_app


def test_first_run_incremental_storage_and_export(engine):
    first=engine.run()
    assert first["status"] == "completed"
    assert float(engine.source.calls[0][1]) == 173000-86400
    stored=engine.store.digests(first["id"])
    assert sum(c["message_count"] for c in stored) == 2
    export=open(first["export_path"]).read()
    assert stored[0]["digest"]["overview"] in export
    assert stored[0]["digest"]["priority_items"][0]["slack_link"] in export
    assert b"this complete raw sentence" not in engine.config.storage.database.read_bytes()
    assert b"xoxp-test-secret" not in engine.config.storage.database.read_bytes()
    engine.source.data["C1"].append(Message(ts="173000.000000",author="a",text="Boundary message"))
    engine.clock=lambda:datetime.fromtimestamp(174000,timezone.utc)
    second=engine.run()
    assert engine.source.calls[-2][1] == "173000.000000"
    assert sum(c["message_count"] for c in engine.store.digests(second["id"])) == 1
    third=engine.run()
    assert engine.store.digests(third["id"]) == []
    assert len(engine.provider.calls) == 3
    assert first["export_path"] != third["export_path"]


def test_partial_run_retries_only_failed_channel(engine):
    engine.source.fail={"C2"}
    first=engine.run()
    assert first["status"] == "partial"
    assert engine.store.checkpoint("C1") == "173000.000000"
    assert engine.store.checkpoint("C2") == "86600.000000"
    engine.source.fail.clear()
    engine.clock=lambda:datetime.fromtimestamp(400000,timezone.utc)
    second=engine.run()
    assert [c["channel_id"] for c in engine.store.digests(second["id"])] == ["C2"]


def test_provider_failure_preserves_channel_window(engine):
    from rundown.providers import ProviderFailure
    original = engine.provider.generate
    engine.provider.generate = lambda _: (_ for _ in ()).throw(ProviderFailure("AI unavailable"))
    first = engine.run()
    assert first["status"] == "failed"
    assert engine.store.checkpoint("C1") == "86600.000000"
    engine.provider.generate = original
    engine.clock=lambda:datetime.fromtimestamp(400000,timezone.utc)
    second = engine.run()
    assert sum(c["message_count"] for c in engine.store.digests(second["id"])) == 2


def test_export_failure_keeps_browser_copy_and_releases_lock(engine, monkeypatch):
    monkeypatch.setattr(engine, "export", lambda _: (_ for _ in ()).throw(OSError("full disk")))
    result = engine.run()
    assert result["status"] == "partial"
    assert engine.store.digests(result["id"])
    assert result["errors"][0]["channel"] == "Export"
    assert not engine.is_busy()


def test_lock_across_engines_and_subprocess_and_recovery(engine):
    run_id=engine.begin()
    try:
        other=Engine(engine.config,engine.source,engine.provider)
        assert other.store.run(run_id)["status"] == "running"
        with pytest.raises(Busy):
            other.begin()
        result=subprocess.run([sys.executable,"-c","from filelock import FileLock, Timeout\nimport sys\ntry:\n FileLock(sys.argv[1], timeout=0).acquire()\nexcept Timeout:\n sys.exit(7)",engine.lock_path],capture_output=True)
        assert result.returncode == 7
    finally:
        engine._lock.release()
        engine._lock=None
    other.recover()
    assert other.store.run(run_id)["status"] == "interrupted"


def test_workspace_binding(engine):
    engine.run()
    engine.source.team_id="T2"
    result=engine.run()
    assert result["status"] == "failed"
    assert "another Slack workspace" in result["errors"][0]["error"]


def test_web_endpoints_and_request_guard(engine):
    with TestClient(create_app(engine=engine)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/api/status?check=true").json()["readiness"]["ready"]
        assert client.post("/api/runs").status_code == 403
        assert client.post("/api/runs",headers={"X-Rundown-Request":"1","Origin":"https://evil.test"}).status_code == 403
        result=client.post("/api/runs",headers={"X-Rundown-Request":"1"})
        assert result.status_code == 202
        run_id=result.json()["id"]
        run=client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "completed"
        date=client.get("/api/dates").json()[0]["date"]
        data=client.get("/api/digests",params={"date":date})
        assert data.status_code == 200
        assert len(data.json()[0]["channels"]) == 2
        assert client.get("/api/digests?date=not-a-date").status_code == 422
        assert client.get("/api/runs/nope").status_code == 404
        assert client.get("/",headers={"Host":"evil.test"}).status_code == 400


def test_web_conflict(engine):
    run_id = engine.begin()
    try:
        with TestClient(create_app(engine=engine)) as client:
            assert client.post("/api/runs", headers={"X-Rundown-Request":"1"}).status_code == 409
    finally:
        engine.execute(run_id)


def test_cli_shared_engine_and_errors(engine,monkeypatch,capsys):
    monkeypatch.setattr("rundown.__main__.load_config",lambda _:engine.config)
    monkeypatch.setattr("rundown.__main__.Engine",lambda _:engine)
    assert main(["check"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"]
    assert main(["run"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"


def test_cli_bad_config_does_not_expose_token(tmp_path,capsys):
    file=tmp_path/"config.toml"
    file.write_text('[slack]\ntoken="xoxp-SECRET"\n[ai]\nprovider="bad"\n')
    assert main(["check","--config",str(file)]) == 2
    assert "xoxp-SECRET" not in capsys.readouterr().err
