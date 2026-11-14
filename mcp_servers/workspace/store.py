"""Local mock calendar + mailbox (SQLite). Same interface a Google Calendar/Gmail backend would
implement; the agent only ever sees the MCP tools, never this module."""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path


class WorkspaceStore:
    def __init__(self, path: Path, seed: int = 3):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript("""
            create table if not exists events (id text primary key, user text, start text, end text,
              title text, kind text, idem text unique);
            create table if not exists drafts (id text primary key, user text, to_label text, subject text,
              body text, created text, idem text unique);
            """)
        self.seed = seed

    def _seed_busy(self, user: str, day0: datetime) -> None:
        """Deterministic busy blocks so free/busy looks like a real calendar."""
        n = self.conn.execute("select count(*) from events where user=? and kind='busy'", (user,)).fetchone()[0]
        if n:
            return
        r = random.Random(f"{self.seed}:{user}")
        for d in range(0, 21):
            day = day0 + timedelta(days=d)
            if day.weekday() >= 5:
                continue
            for _ in range(r.randint(1, 3)):
                h = r.randint(9, 16)
                s = datetime.combine(day.date(), time(h, r.choice([0, 30])), tzinfo=UTC)
                self.conn.execute("insert into events values (?,?,?,?,?,?,?)",
                                  (uuid.uuid4().hex, user, s.isoformat(), (s + timedelta(minutes=r.choice([30, 60, 90]))).isoformat(),
                                   "Busy", "busy", None))
        self.conn.commit()

    def busy(self, user: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        with self.lock:
            self._seed_busy(user, start.replace(hour=0, minute=0, second=0, microsecond=0))
            rows = self.conn.execute("select start, end from events where user=? and end>? and start<?",
                                     (user, start.isoformat(), end.isoformat())).fetchall()
        return [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in rows]

    def free_slots(self, user: str, start: datetime, days: int, duration_min: int, work_start: int, work_end: int,
                   max_slots: int) -> list[tuple[datetime, datetime]]:
        end = start + timedelta(days=days)
        busy = self.busy(user, start, end)
        out: list[tuple[datetime, datetime]] = []
        cur = start
        step = timedelta(minutes=30)
        dur = timedelta(minutes=duration_min)
        while cur + dur <= end and len(out) < max_slots:
            in_hours = cur.weekday() < 5 and work_start <= cur.hour and (cur + dur).hour <= work_end and (cur + dur).date() == cur.date()
            clash = any(a < cur + dur and cur < b for a, b in busy)
            spaced = not out or cur - out[-1][0] >= timedelta(hours=3)  # spread suggestions out
            if in_hours and not clash and spaced:
                out.append((cur, cur + dur))
            cur += step
        return out

    def hold(self, user: str, start: datetime, end: datetime, title: str, idem: str) -> dict:
        with self.lock:
            row = self.conn.execute("select id, start, end, title from events where idem=?", (idem,)).fetchone()
            if row:
                return {"id": row[0], "start": row[1], "end": row[2], "title": row[3], "replayed": True}
            clash = self.conn.execute("select count(*) from events where user=? and end>? and start<?",
                                      (user, start.isoformat(), end.isoformat())).fetchone()[0]
            if clash:
                raise ValueError("slot is no longer free")
            eid = "hold_" + uuid.uuid4().hex[:10]
            self.conn.execute("insert into events values (?,?,?,?,?,?,?)",
                              (eid, user, start.isoformat(), end.isoformat(), title, "tentative", idem))
            self.conn.commit()
        return {"id": eid, "start": start.isoformat(), "end": end.isoformat(), "title": title, "replayed": False}

    def draft(self, user: str, to_label: str, subject: str, body: str, idem: str) -> dict:
        with self.lock:
            row = self.conn.execute("select id from drafts where idem=?", (idem,)).fetchone()
            if row:
                return {"id": row[0], "replayed": True}
            did = "draft_" + uuid.uuid4().hex[:10]
            self.conn.execute("insert into drafts values (?,?,?,?,?,?,?)",
                              (did, user, to_label, subject, body, datetime.now(UTC).isoformat(), idem))
            self.conn.commit()
        return {"id": did, "replayed": False}

    def list_drafts(self, user: str) -> list[dict]:
        rows = self.conn.execute("select id, to_label, subject, body, created from drafts where user=? order by created desc",
                                 (user,)).fetchall()
        return [dict(zip(["id", "to", "subject", "body", "created"], r, strict=True)) for r in rows]

    def dump(self) -> str:
        return json.dumps(self.conn.execute("select count(*) from events").fetchone())
