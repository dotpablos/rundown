from __future__ import annotations

from pydantic import Field
from .config import StrictModel


class PriorityItem(StrictModel):
    source_ts: str
    slack_link: str = ""
    matched_keywords: list[str] = Field(default_factory=list)
    ai_priority: int = Field(ge=0, le=3)
    explanation: str
    keyword_score: int = 0
    score: int = 0


class Digest(StrictModel):
    overview: str
    key_updates: list[str]
    action_items: list[str]
    decisions: list[str]
    priority_items: list[PriorityItem]


class Message(StrictModel):
    ts: str
    author: str
    text: str
    thread_ts: str | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    keyword_score: int = 0

