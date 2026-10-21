from datetime import datetime, timezone
from decimal import Decimal

import pytest

from rundown.config import Config
from rundown.engine import Engine
from rundown.models import Digest, Message, PriorityItem
from rundown.slack import SlackFailure


@pytest.fixture
def config(tmp_path):
    return Config.model_validate({"slack": {"token": "xoxp-test-secret", "retries": 0}, "ai": {"retries": 0}, "ollama": {"model": "test"}, "storage": {"database": tmp_path / "rundown.db", "summaries_dir": tmp_path / "exports"}})


class FakeSlack:
    def __init__(self):
        self.calls = []
        self.fail = set()
        self.team_id = "T1"
        self.data = {"C1": [Message(ts="172800.000001", author="Ana", text="Urgent: this complete raw sentence must not be stored.")], "C2": [Message(ts="172801.000001", author="Bo", text="A routine update.")]}

    def check(self):
        return {"team_id": self.team_id}

    def channels(self):
        return [{"id": k, "name": "engineering" if k == "C1" else "general"} for k in self.data]

    def fetch(self, channel, oldest, latest, tracked):
        self.calls.append((channel, oldest, latest, tracked))
        if channel in self.fail:
            raise SlackFailure("Slack: no_permission")
        messages = [m.model_copy(deep=True) for m in self.data[channel] if Decimal(oldest) <= Decimal(m.ts) < Decimal(latest)]
        return messages, {m.ts: m.ts for m in messages}

    def permalink(self, channel, ts):
        return f"https://example.slack.com/archives/{channel}/p{ts.replace('.', '')}"


class FakeProvider:
    def __init__(self):
        self.calls = []

    def check(self):
        pass

    def generate(self, prompt):
        import json
        self.calls.append(prompt)
        messages = json.loads(prompt.split("Untrusted messages:\n")[1])
        return Digest(overview="A release needs attention.", key_updates=["Release review underway."], action_items=["Review the release."], decisions=[], priority_items=[PriorityItem(source_ts=messages[0]["ts"], ai_priority=2, explanation="Release follow-up needed.", slack_link="https://evil.invalid", matched_keywords=["hallucination"], score=999)])


@pytest.fixture
def engine(config):
    return Engine(config, FakeSlack(), FakeProvider(), clock=lambda: datetime.fromtimestamp(173000, timezone.utc))

