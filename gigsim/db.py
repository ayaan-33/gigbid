"""GigSim storage: a single SQLite file (durable across restarts, trivially resettable)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
create table if not exists accounts (
  token text primary key, freelancer_id text not null, name text, connects integer not null
);
create table if not exists clients (
  id text primary key, data text not null, hidden text not null
);
create table if not exists jobs (
  id text primary key, client_id text not null, release_at real not null,
  category text, data text not null, status text not null default 'open',
  proposals_count integer not null default 0
);
create table if not exists historical_jobs (
  id text primary key, category text, data text not null
);
create table if not exists proposals (
  id text primary key, freelancer_id text not null, job_id text not null,
  status text not null, data text not null, created_at real not null,
  submitted_at real, decide_at real, outcome text, connects_spent integer default 0
);
create table if not exists idempotency (
  key text primary key, freelancer_id text not null, endpoint text not null,
  response text not null, created_at real not null
);
create table if not exists connects_ledger (
  id integer primary key autoincrement, freelancer_id text, delta integer, reason text,
  ref text, at real
);
create table if not exists conversations (
  id text primary key, freelancer_id text not null, client_id text not null,
  job_id text, proposal_id text, state text not null default 'open', script text
);
create table if not exists messages (
  id text primary key, conversation_id text not null, sender text not null,
  text text not null, at real not null
);
create table if not exists events (
  id integer primary key autoincrement, freelancer_id text not null, type text not null,
  ref text, data text, at real not null
);
create table if not exists sim (k text primary key, v text not null);
"""


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma journal_mode=wal")
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def q(self, sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple | list = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def x(self, sql: str, args: tuple | list = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid or 0

    def tx(self):
        return _Tx(self)

    def get_sim(self, k: str, default: Any = None) -> Any:
        row = self.one("select v from sim where k=?", (k,))
        return json.loads(row["v"]) if row else default

    def set_sim(self, k: str, v: Any) -> None:
        self.x("insert or replace into sim values (?,?)", (k, json.dumps(v)))


class _Tx:
    def __init__(self, db: DB):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("begin immediate")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db.conn.execute("rollback" if exc_type else "commit")
        finally:
            self.db.lock.release()
        return False
