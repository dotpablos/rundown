from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, started_at TEXT NOT NULL, date TEXT NOT NULL,
                    status TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0, processed INTEGER NOT NULL DEFAULT 0,
                    errors TEXT NOT NULL DEFAULT '[]', export_path TEXT);
                CREATE TABLE IF NOT EXISTS channels (id TEXT PRIMARY KEY, checkpoint TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS threads (
                    channel_id TEXT NOT NULL, ts TEXT NOT NULL, active_at TEXT NOT NULL,
                    PRIMARY KEY(channel_id, ts));
                CREATE TABLE IF NOT EXISTS messages (
                    channel_id TEXT NOT NULL, ts TEXT NOT NULL, hash TEXT NOT NULL,
                    PRIMARY KEY(channel_id, ts));
                CREATE TABLE IF NOT EXISTS digests (
                    run_id TEXT NOT NULL, channel_id TEXT NOT NULL, channel_name TEXT NOT NULL,
                    message_count INTEGER NOT NULL, window_start TEXT NOT NULL, window_end TEXT NOT NULL,
                    digest TEXT NOT NULL, PRIMARY KEY(run_id, channel_id));
            """)
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def bind_workspace(self, team_id: str):
        with self.connect() as db:
            existing = db.execute("SELECT value FROM metadata WHERE key='workspace'").fetchone()
            if existing and existing[0] != team_id:
                raise ValueError("This database belongs to another Slack workspace; choose a different database path")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('workspace', ?)", (team_id,))

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE runs SET status='interrupted', errors=? WHERE status='running'", (json.dumps([{"channel": "Run", "error": "The previous process stopped. Run again to retry incomplete channels."}]),))

    def create_run(self, run_id, started_at, date, provider, model):
        with self.connect() as db:
            db.execute("INSERT INTO runs (id, started_at, date, status, provider, model) VALUES (?, ?, ?, 'running', ?, ?)", (run_id, started_at, date, provider, model))

    def update_run(self, run_id: str, **fields):
        allowed = {"status", "total", "processed", "errors", "export_path"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid run fields")
        if "errors" in fields:
            fields["errors"] = json.dumps(fields["errors"])
        with self.connect() as db:
            db.execute("UPDATE runs SET " + ", ".join(f"{key}=?" for key in fields) + " WHERE id=?", (*fields.values(), run_id))

    def checkpoint(self, channel: str) -> str | None:
        with self.connect() as db:
            r = db.execute("SELECT checkpoint FROM channels WHERE id=?", (channel,)).fetchone()
        return r[0] if r else None

    def initialize_channels(self, channels: list[str], start: str):
        # Preserve the first attempted window even if a first run fails for days.
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO channels VALUES (?, ?)", [(channel, start) for channel in channels])

    def tracked(self, channel: str, cutoff: str) -> list[str]:
        with self.connect() as db:
            rows = db.execute("SELECT ts FROM threads WHERE channel_id=? AND CAST(active_at AS REAL)>=?", (channel, float(cutoff))).fetchall()
        return [r[0] for r in rows]

    def seen(self, channel: str, ts: str) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM messages WHERE channel_id=? AND ts=?", (channel, ts)).fetchone() is not None

    def commit_channel(self, run_id, channel, name, start, end, messages, threads, digest):
        import hashlib
        with self.connect() as db:
            if digest is not None:
                db.execute("INSERT INTO digests VALUES (?, ?, ?, ?, ?, ?, ?)", (run_id, channel, name, len(messages), start, end, digest.model_dump_json()))
            db.executemany("INSERT OR IGNORE INTO messages VALUES (?, ?, ?)", [(channel, m.ts, hashlib.sha256(m.text.encode()).hexdigest()) for m in messages])
            db.executemany("INSERT INTO threads VALUES (?, ?, ?) ON CONFLICT(channel_id, ts) DO UPDATE SET active_at=excluded.active_at", [(channel, ts, active) for ts, active in threads.items()])
            db.execute("INSERT INTO channels VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET checkpoint=excluded.checkpoint", (channel, end))

    def run(self, run_id: str) -> dict | None:
        with self.connect() as db:
            r = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if r is None:
            return None
        result = dict(r)
        result["errors"] = json.loads(result["errors"])
        return result

    def latest(self):
        with self.connect() as db:
            r = db.execute("SELECT id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        return self.run(r[0]) if r else None

    def dates(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT date, COUNT(*) AS runs FROM runs GROUP BY date ORDER BY date DESC")]

    def digests(self, run_id):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM digests WHERE run_id=?", (run_id,)).fetchall()
        result = []
        for row in rows:
            entry = dict(row)
            entry["digest"] = json.loads(entry["digest"])
            result.append(entry)
        return sorted(result, key=lambda c: (-max((p["score"] for p in c["digest"]["priority_items"]), default=0), c["channel_name"]))

    def by_date(self, date: str):
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM runs WHERE date=? ORDER BY started_at DESC", (date,))]
        return [{**self.run(i), "channels": self.digests(i)} for i in ids]
