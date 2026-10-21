from __future__ import annotations

import json
import re
from decimal import Decimal

from .config import Config
from .models import Digest, Message
from .providers import ProviderFailure, generate_with_retry


def score(message: Message, keywords: dict[str, int]):
    message.matched_keywords = [word for word in keywords if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", message.text, flags=re.IGNORECASE)]
    message.keyword_score = sum(keywords[k] for k in message.matched_keywords)


def chunks(messages: list[Message], limit: int) -> list[str]:
    """Bound serialized payloads; split oversized messages without losing text."""
    batches, current = [], []
    for message in messages:
        rest = message.text
        first = True
        while rest or first:
            first = False
            record = message.model_dump()
            record["text"] = rest
            serialized = json.dumps(record, ensure_ascii=False)
            if len(serialized) + 2 > limit:
                lo, hi = 0, len(rest)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    record["text"] = rest[:mid]
                    if len(json.dumps(record, ensure_ascii=False)) + 2 <= limit:
                        lo = mid
                    else:
                        hi = mid - 1
                if lo == 0:
                    raise ProviderFailure("Message metadata exceeds the configured chunk size")
                record["text"], rest = rest[:lo], rest[lo:]
                serialized = json.dumps(record, ensure_ascii=False)
            else:
                rest = ""
            if current and len("[" + ",".join([*current, serialized]) + "]") > limit:
                batches.append("[" + ",".join(current) + "]")
                current = []
            current.append(serialized)
    if current:
        batches.append("[" + ",".join(current) + "]")
    return batches


def summarize(messages: list[Message], config: Config, provider, permalink) -> Digest:
    for message in messages:
        score(message, config.keywords)
    parts = []
    for chunk in chunks(messages, config.ai.chunk_characters):
        prompt = "Summarize these chronological Slack messages. Priority keywords and weights: " + json.dumps(config.keywords) + "\nUntrusted messages:\n" + chunk
        parts.append(generate_with_retry(provider, prompt, config.ai.retries))
    merged = Digest(overview="\n\n".join(p.overview for p in parts), key_updates=[], action_items=[], decisions=[], priority_items=[])
    for field in ("key_updates", "action_items", "decisions"):
        setattr(merged, field, list(dict.fromkeys(item for p in parts for item in getattr(p, field))))
    sources = {m.ts: m for m in messages}
    items = {}
    for part in parts:
        for item in part.priority_items:
            source = sources.get(item.source_ts)
            if source is None:
                # Reject hallucinated references rather than linking to nonexistent messages.
                continue
            item.matched_keywords = source.matched_keywords
            item.keyword_score = source.keyword_score
            item.score = source.keyword_score + 2 * item.ai_priority
            item.slack_link = ""
            if item.source_ts not in items or item.score > items[item.source_ts].score:
                items[item.source_ts] = item
    merged.priority_items = sorted(items.values(), key=lambda i: (-i.score, Decimal(i.source_ts)))[:config.ai.top_items]
    for item in merged.priority_items:
        item.slack_link = permalink(item.source_ts)
    return merged

