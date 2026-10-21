from __future__ import annotations

import html
import re
import time
from decimal import Decimal

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError, SlackRequestError

from .config import Config
from .models import Message


class SlackFailure(RuntimeError):
    pass


CONTENT_SUBTYPES = {None, "bot_message", "me_message", "thread_broadcast", "reply_broadcast", "file_share"}


class SlackSource:
    def __init__(self, config: Config, client=None, sleep=time.sleep):
        self.config = config
        self.client = client or WebClient(token=config.slack.token.get_secret_value(), timeout=config.slack.timeout_seconds, retry_handlers=[])
        self.sleep = sleep
        self.users: dict[str, str] = {}
        self.channel_names: dict[str, str] = {}

    def call(self, method: str, **kwargs) -> dict:
        for attempt in range(self.config.slack.retries + 1):
            try:
                return dict(getattr(self.client, method)(**kwargs))
            except SlackApiError as exc:
                code = exc.response.get("error", "slack_error")
                if code not in {"ratelimited", "internal_error", "fatal_error", "service_unavailable", "request_timeout"} or attempt == self.config.slack.retries:
                    raise SlackFailure(f"Slack: {code}") from None
                delay = min(2 ** attempt, 30)
                if code == "ratelimited":
                    delay = int(exc.response.headers.get("Retry-After", exc.response.headers.get("retry-after", 1)))
                    if delay > self.config.slack.max_retry_after_seconds:
                        raise SlackFailure(f"Slack rate limited; retry in {delay} seconds") from None
                self.sleep(max(1, delay))
            except (SlackRequestError, OSError):
                if attempt == self.config.slack.retries:
                    raise SlackFailure("Slack connection failed") from None
                self.sleep(min(2 ** attempt, 30))
        raise SlackFailure("Slack request failed")

    def check(self) -> dict:
        if not self.config.slack.token.get_secret_value().startswith("xoxp-"):
            raise SlackFailure("Set a Slack user OAuth token (xoxp-...) in config or SLACK_USER_TOKEN")
        result = self.call("auth_test")
        return {"team_id": result["team_id"], "team": result.get("team", "Slack"), "user_id": result["user_id"]}

    def pages(self, method: str, key: str, **kwargs):
        cursor = None
        while True:
            result = self.call(method, limit=200, cursor=cursor, **kwargs)
            yield from result.get(key, [])
            next_cursor = result.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                if result.get("has_more"):
                    # History supports time pagination when a cursor is absent.
                    rows = result.get(key, [])
                    if method == "conversations_history" and rows:
                        boundary = min(rows, key=lambda m: Decimal(m["ts"]))["ts"]
                        if kwargs.get("latest") == boundary:
                            raise SlackFailure("Slack pagination did not advance")
                        kwargs["latest"] = boundary
                        kwargs["inclusive"] = False
                        cursor = None
                        continue
                    raise SlackFailure("Slack returned incomplete pagination")
                break
            if next_cursor == cursor:
                raise SlackFailure("Slack pagination did not advance")
            cursor = next_cursor

    def channels(self) -> list[dict]:
        cfg = self.config.slack
        types = []
        if cfg.joined_public or cfg.unjoined_public:
            types.append("public_channel")
        if cfg.private_channels:
            types.append("private_channel")
        if cfg.direct_messages:
            types.append("im")
        if cfg.group_messages:
            types.append("mpim")
        if not types:
            return []
        selected = []
        for c in self.pages("conversations_list", "channels", types=",".join(types), exclude_archived=True):
            if c.get("is_archived"):
                continue
            if c.get("is_im"):
                include = cfg.direct_messages
                c["name"] = "DM · " + self.user(c.get("user", c["id"]))
            elif c.get("is_mpim"):
                include = cfg.group_messages
            elif c.get("is_private"):
                include = cfg.private_channels and c.get("is_member", True)
            else:
                include = cfg.joined_public if c.get("is_member") else cfg.unjoined_public
            self.channel_names[c["id"]] = c.get("name", c["id"])
            if include:
                selected.append(c)
        return selected

    def user(self, user_id: str) -> str:
        if not user_id:
            return "Unknown"
        if user_id not in self.users:
            try:
                u = self.call("users_info", user=user_id)["user"]
                p = u.get("profile", {})
                self.users[user_id] = p.get("display_name") or p.get("real_name") or u.get("name") or user_id
            except SlackFailure:
                self.users[user_id] = user_id
        return self.users[user_id]

    def normalize(self, text: str) -> str:
        text = re.sub(r"<@([A-Z0-9]+)(?:\|[^>]+)?>", lambda m: "@" + self.user(m[1]), text)
        text = re.sub(r"<#([A-Z0-9]+)(?:\|([^>]+))?>", lambda m: "#" + (m[2] or self.channel_names.get(m[1], m[1])), text)
        text = re.sub(r"<!(here|channel|everyone)>", r"@\1", text)
        text = re.sub(r"<(https?://[^>|]+)\|([^>]+)>", r"\2 (\1)", text)
        text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
        return html.unescape(text)

    def fetch(self, channel: str, oldest: str, latest: str, tracked: list[str]) -> tuple[list[Message], dict[str, str]]:
        rows = list(self.pages("conversations_history", "messages", channel=channel, oldest=oldest, latest=latest, inclusive=True))
        roots = set(tracked)
        activity = {}
        for row in rows:
            if row.get("subtype") in CONTENT_SUBTYPES and "ts" in row:
                root = row.get("thread_ts") or row["ts"]
                # Track even roots with zero replies: a reply may arrive tomorrow.
                activity[root] = max(activity.get(root, root), row["ts"], key=Decimal)
                if row.get("reply_count", 0) or row.get("thread_ts"):
                    roots.add(root)
        for root in sorted(roots, key=Decimal):
            try:
                replies = list(self.pages("conversations_replies", "messages", channel=channel, ts=root, oldest=oldest, latest=latest, inclusive=True))
            except SlackFailure as exc:
                if str(exc) == "Slack: thread_not_found":
                    continue
                raise
            rows.extend(replies)
            fresh = [r["ts"] for r in replies if Decimal(oldest) <= Decimal(r["ts"]) < Decimal(latest)]
            if fresh:
                activity[root] = max(fresh, key=Decimal)
        messages = {}
        for r in rows:
            if r.get("subtype") not in CONTENT_SUBTYPES or not Decimal(oldest) <= Decimal(r["ts"]) < Decimal(latest):
                continue
            text = r.get("text", "").strip()
            if not text:
                continue
            author = self.user(r["user"]) if r.get("user") else r.get("bot_profile", {}).get("name") or r.get("username") or r.get("bot_id", "Bot")
            messages[r["ts"]] = Message(ts=r["ts"], author=author, text=self.normalize(text), thread_ts=r.get("thread_ts"))
        return sorted(messages.values(), key=lambda m: Decimal(m.ts)), activity

    def permalink(self, channel: str, ts: str) -> str:
        return self.call("chat_getPermalink", channel=channel, message_ts=ts)["permalink"]
