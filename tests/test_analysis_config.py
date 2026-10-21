import json

import pytest
from pydantic import ValidationError

from rundown.analysis import chunks, score, summarize
from rundown.config import Config, load_config, redact
from rundown.models import Message, PriorityItem


def test_load_config_relative_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNDOWN_TEST_TOKEN", "xoxp-synthetic")
    file = tmp_path / "config.toml"
    file.write_text('[slack]\ntoken="env:RUNDOWN_TEST_TOKEN"\n[storage]\ndatabase="local/state.db"\n')
    cfg = load_config(file)
    assert cfg.slack.token.get_secret_value() == "xoxp-synthetic"
    assert cfg.storage.database == tmp_path / "local/state.db"
    assert "xoxp-synthetic" not in repr(cfg)
    assert redact("token xoxp-synthetic", cfg) == "token [redacted]"


@pytest.mark.parametrize("data", [{"ai":{"provider":"bad"}}, {"storage":{"timezone":"fake/zone"}}, {"keywords":{"":2}}, {"keywords":{"urgent":-1}}, {"ollama":{"base_url":"https://remote.example"}}, {"slack":{"unexpected":True}}])
def test_config_validation(data):
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_keyword_boundaries_and_weights():
    m = Message(ts="1", author="a", text="URGENT urgent! Urgently unblocker. Action required.")
    score(m, {"urgent":5,"blocker":5,"action required":4})
    assert m.keyword_score == 9
    assert m.matched_keywords == ["urgent", "action required"]


def test_chunks_bound_serialization_and_preserve_all_content():
    text = ('Unicode 🦊 " \\ newline\n' * 1500)
    messages = [Message(ts="1.000001",author="a",text=text), Message(ts="2",author="b",text="last")]
    result = chunks(messages, 2000)
    assert all(len(c) <= 2000 for c in result)
    records = [m for c in result for m in json.loads(c)]
    assert "".join(m["text"] for m in records if m["ts"] == "1.000001") == text
    assert records[-1]["text"] == "last"


def test_source_validation_ranking_and_chunk_merge(engine):
    original = engine.provider.generate
    def generate(prompt):
        d = original(prompt)
        d.priority_items.append(PriorityItem(source_ts="invented", ai_priority=3, explanation="Fake source"))
        return d
    engine.provider.generate = generate
    messages = engine.source.data["C1"]
    result = summarize(messages, engine.config, engine.provider, lambda ts: "https://example.slack.com/verified")
    assert len(result.priority_items) == 1
    item = result.priority_items[0]
    assert item.score == 9
    assert item.matched_keywords == ["urgent"]
    assert item.slack_link == "https://example.slack.com/verified"

