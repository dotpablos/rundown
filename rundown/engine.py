from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from filelock import FileLock, Timeout

from .analysis import summarize
from .config import Config, redact
from .providers import ProviderFailure, provider_for
from .slack import SlackFailure, SlackSource
from .storage import Store


class Busy(RuntimeError):
    pass


class Engine:
    def __init__(self, config: Config, source=None, provider=None, clock=None):
        self.config = config
        self.store = Store(config.storage.database)
        self.source = source or SlackSource(config)
        self.provider = provider or provider_for(config)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock_path = str(config.storage.database) + ".lock"
        self._lock = None
        self.recover()

    def recover(self):
        try:
            with FileLock(self.lock_path, timeout=0):
                self.store.recover()
        except Timeout:
            pass

    def is_busy(self):
        try:
            with FileLock(self.lock_path, timeout=0):
                return False
        except Timeout:
            return True

    def check(self):
        results = {}
        for name, component in (("slack", self.source), ("provider", self.provider)):
            try:
                component.check()
                results[name] = {"ready": True, "message": "Connected"}
            except Exception as exc:
                results[name] = {"ready": False, "message": self.safe_error(exc)}
        return {"ready": all(item["ready"] for item in results.values()), "provider_name": self.config.ai.provider, **results}

    def safe_error(self, exc):
        if isinstance(exc, (SlackFailure, ProviderFailure, ValueError, Busy)):
            return redact(str(exc), self.config)
        if isinstance(exc, OSError):
            return "Local file access failed; check paths, permissions, and available disk space"
        return "Unexpected processing error; no checkpoint was advanced for the failed channel"

    def begin(self):
        lock = FileLock(self.lock_path, timeout=0, thread_local=False)
        try:
            lock.acquire()
        except Timeout:
            raise Busy("Another digest is already running") from None
        try:
            self.store.recover()
            now = self.clock()
            run_id = uuid.uuid4().hex
            model = self.config.ollama.model if self.config.ai.provider == "ollama" else self.config.claude_code.model
            self.store.create_run(run_id, now.isoformat(), now.astimezone(ZoneInfo(self.config.storage.timezone)).date().isoformat(), self.config.ai.provider, model)
            self._lock = lock
            return run_id
        except BaseException:
            lock.release()
            raise

    def run(self):
        run_id = self.begin()
        self.execute(run_id)
        return self.store.run(run_id)

    def execute(self, run_id):
        errors, successes = [], 0
        try:
            run = self.store.run(run_id)
            end = datetime.fromisoformat(run["started_at"]).timestamp()
            identity = self.source.check()
            self.store.bind_workspace(identity["team_id"])
            self.provider.check()
            channels = self.source.channels()
            self.store.initialize_channels([c["id"] for c in channels], f"{end - self.config.slack.initial_lookback_hours * 3600:.6f}")
            self.store.update_run(run_id, total=len(channels))
            for index, channel in enumerate(channels):
                channel_id, name = channel["id"], channel.get("name", channel["id"])
                try:
                    start = self.store.checkpoint(channel_id)
                    if float(start) > end:
                        raise ValueError("System clock is earlier than the last checkpoint; retry when the clock is correct")
                    tracked = self.store.tracked(channel_id, str(float(start) - self.config.slack.thread_tracking_days * 86400))
                    messages, threads = self.source.fetch(channel_id, start, f"{end:.6f}", tracked)
                    fresh = [m for m in messages if not self.store.seen(channel_id, m.ts)]
                    digest = summarize(fresh, self.config, self.provider, lambda ts: self.source.permalink(channel_id, ts)) if fresh else None
                    self.store.commit_channel(run_id, channel_id, name, start, f"{end:.6f}", fresh, threads, digest)
                    successes += 1
                except Exception as exc:
                    errors.append({"channel": name, "error": self.safe_error(exc)})
                self.store.update_run(run_id, processed=index + 1, errors=errors)
            status = "completed" if not errors else "partial" if successes else "failed"
            self.store.update_run(run_id, status=status, errors=errors)
        except Exception as exc:
            errors.append({"channel": "Run", "error": self.safe_error(exc)})
            self.store.update_run(run_id, status="failed", errors=errors)
        finally:
            try:
                self.export(run_id)
            except Exception as exc:
                errors.append({"channel": "Export", "error": self.safe_error(exc) + "; summaries remain available in the browser"})
                current = self.store.run(run_id)
                self.store.update_run(run_id, status="partial" if current["status"] == "completed" else current["status"], errors=errors)
            finally:
                if self._lock:
                    self._lock.release()
                    self._lock = None

    def export(self, run_id):
        run = self.store.run(run_id)
        channels = self.store.digests(run_id)
        local = datetime.fromisoformat(run["started_at"]).astimezone(ZoneInfo(self.config.storage.timezone))
        lines = [f"# Rundown — {local:%Y-%m-%d %H:%M:%S %Z}", "", f"Status: {run['status']} · Provider: {run['provider']} · Model: {run['model']}", "", "AI-generated summaries may contain inaccuracies. Source links open Slack.", ""]
        for error in run["errors"]:
            lines.extend([f"- {error['channel']}: {error['error']}", ""])
        if not channels:
            lines.extend(["No new messages were summarized.", ""])
        for channel in channels:
            d = channel["digest"]
            lines.extend([f"## {channel['channel_name']}", "", f"{channel['message_count']} new messages", "", d["overview"], ""])
            for key, title in (("key_updates", "Key updates"), ("action_items", "Action items"), ("decisions", "Decisions")):
                if d[key]:
                    lines.extend([f"### {title}", "", *[f"- {item}" for item in d[key]], ""])
            if d["priority_items"]:
                lines.extend(["### Priority messages", ""])
                for item in d["priority_items"]:
                    lines.append(f"- [{item['score']}] {item['explanation']} — [Open in Slack]({item['slack_link']}) · Keywords: {', '.join(item['matched_keywords']) or 'contextual relevance'}")
                lines.append("")
        directory = self.config.storage.summaries_dir
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{local:%Y-%m-%dT%H-%M-%S}-{run_id[:8]}.md"
        fd, temporary = tempfile.mkstemp(prefix=".rundown-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("\n".join(lines))
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.store.update_run(run_id, export_path=str(target))
