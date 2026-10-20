"""SQLite storage: every event we accepted, and every delivery attempt."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,         -- Stripe's evt_ id; the idempotency key
    event_type   TEXT NOT NULL,
    received_at  TEXT NOT NULL,
    handled      INTEGER NOT NULL,         -- 0 = ignored type
    record_json  TEXT,                     -- normalized Record, NULL when ignored
    raw_json     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL REFERENCES events(event_id),
    channel      TEXT NOT NULL,            -- slack | sheets
    payload_json TEXT NOT NULL,
    status       TEXT NOT NULL,            -- sent | preview | failed
    detail       TEXT,
    attempts     INTEGER NOT NULL DEFAULT 1,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at  TEXT NOT NULL,
    outcome      TEXT NOT NULL,            -- processed | duplicate | ignored | rejected
    event_id     TEXT,
    detail       TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def insert_event(self, event: dict, record: dict | None) -> bool:
        """Insert the event. Returns False if we have already seen this event id."""
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                (event["id"], event["type"], _now(), int(record is not None),
                 json.dumps(record) if record else None, json.dumps(event)))
            return cur.rowcount == 1

    def add_delivery(self, event_id: str, channel: str, payload: dict, status: str, detail: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO deliveries (event_id, channel, payload_json, status, detail, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (event_id, channel, json.dumps(payload), status, detail, _now()))
            return cur.lastrowid

    def update_delivery(self, delivery_id: int, status: str, detail: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE deliveries SET status=?, detail=?, attempts=attempts+1, updated_at=? WHERE id=?",
                      (status, detail, _now(), delivery_id))

    def get_delivery(self, delivery_id: int):
        with self._conn() as c:
            return c.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()

    def log_request(self, outcome: str, event_id: str | None, detail: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO webhook_log (received_at, outcome, event_id, detail) VALUES (?,?,?,?)",
                      (_now(), outcome, event_id, detail))

    def request_log(self, limit: int = 12) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM webhook_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def version(self) -> str:
        """Changes whenever anything the dashboard shows changes."""
        with self._conn() as c:
            row = c.execute("SELECT (SELECT COUNT(*) FROM webhook_log) || '-' || "
                            "(SELECT COALESCE(SUM(attempts), 0) FROM deliveries)").fetchone()
        return row[0]

    def records(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT record_json FROM events WHERE handled=1 "
                             "ORDER BY json_extract(record_json, '$.occurred_at') DESC").fetchall()
        return [json.loads(r["record_json"]) for r in rows]

    def feed(self, limit: int = 50) -> list[dict]:
        """Recent events with their deliveries attached, newest first."""
        with self._conn() as c:
            events = c.execute("SELECT event_id, event_type, received_at, handled, record_json "
                               "FROM events ORDER BY received_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
            out = []
            for e in events:
                deliveries = c.execute("SELECT * FROM deliveries WHERE event_id=? ORDER BY channel",
                                       (e["event_id"],)).fetchall()
                out.append({
                    **dict(e),
                    "record": json.loads(e["record_json"]) if e["record_json"] else None,
                    "deliveries": [{**dict(d), "payload": json.loads(d["payload_json"])} for d in deliveries],
                })
            return out

    def reset(self) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM webhook_log")
            c.execute("DELETE FROM deliveries")
            c.execute("DELETE FROM events")
