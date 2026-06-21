"""Single-GPU lease with priorities + preemption. low = custodian (idle-only, yields);
normal = real jobs (preempt a low holder: flag revoke, wait a grace window, then force-steal).
SQLite-backed; TTL backstops a dead holder. NULL priority (legacy rows) is treated as normal."""
from __future__ import annotations
import contextlib, sqlite3, time
from config import DB_PATH

_SCHEMA = """CREATE TABLE IF NOT EXISTS gpu_lease(
  id INTEGER PRIMARY KEY CHECK (id=1), holder TEXT, task TEXT,
  acquired_at REAL, expires_at REAL, priority TEXT, revoked INTEGER DEFAULT 0);"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute(_SCHEMA)
    for col, decl in (("priority", "TEXT"), ("revoked", "INTEGER DEFAULT 0")):
        try:
            c.execute(f"ALTER TABLE gpu_lease ADD COLUMN {col} {decl}")  # idempotent migration
        except sqlite3.OperationalError:
            pass
    return c


def _upsert(c, holder, task, now, ttl, priority):
    c.execute("INSERT INTO gpu_lease(id,holder,task,acquired_at,expires_at,priority,revoked) "
              "VALUES(1,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET holder=excluded.holder, "
              "task=excluded.task, acquired_at=excluded.acquired_at, expires_at=excluded.expires_at, "
              "priority=excluded.priority, revoked=0",
              (holder, task, now, now + ttl, priority))


def _try_once(holder, task, ttl, priority) -> str:  # "ok" | "busy" | "revoking"
    now = time.time()
    with contextlib.closing(_conn()) as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT holder, expires_at, priority FROM gpu_lease WHERE id=1").fetchone()
        live = bool(row) and row["expires_at"] > now
        if live and row["holder"] != holder:
            if priority == "normal" and row["priority"] == "low":
                c.execute("UPDATE gpu_lease SET revoked=1 WHERE id=1")
                c.execute("COMMIT")
                return "revoking"
            c.execute("ROLLBACK")
            return "busy"
        _upsert(c, holder, task, now, ttl, priority)
        c.execute("COMMIT")
        return "ok"


def _force_steal(holder, task, ttl, priority):
    now = time.time()
    with contextlib.closing(_conn()) as c:
        c.execute("BEGIN IMMEDIATE")
        _upsert(c, holder, task, now, ttl, priority)
        c.execute("COMMIT")


def acquire_gpu(holder, task, priority="normal", ttl=1800, wait=True, poll=0.05,
                timeout=None, grace=10.0) -> bool:
    deadline = None if timeout is None else time.time() + timeout
    revoke_deadline = None
    while True:
        res = _try_once(holder, task, ttl, priority)
        if res == "ok":
            return True
        if res == "revoking":
            if revoke_deadline is None:
                revoke_deadline = time.time() + grace
            if time.time() >= revoke_deadline:
                _force_steal(holder, task, ttl, priority)
                return True
        if not wait or (deadline is not None and time.time() >= deadline):
            return False
        time.sleep(poll)


def release_gpu(holder) -> None:
    with contextlib.closing(_conn()) as c, c:
        c.execute("DELETE FROM gpu_lease WHERE id=1 AND holder=?", (holder,))


def is_revoked(holder) -> bool:
    with contextlib.closing(_conn()) as c:
        row = c.execute("SELECT holder, revoked, expires_at FROM gpu_lease WHERE id=1").fetchone()
    return bool(row and row["holder"] == holder and row["expires_at"] > time.time() and row["revoked"])


def gpu_is_idle() -> bool:
    now = time.time()
    with contextlib.closing(_conn()) as c:
        row = c.execute("SELECT priority, expires_at FROM gpu_lease WHERE id=1").fetchone()
    if not row or row["expires_at"] <= now:
        return True
    return row["priority"] == "low"


def gpu_lease_status() -> dict | None:
    now = time.time()
    with contextlib.closing(_conn()) as c:
        row = c.execute("SELECT * FROM gpu_lease WHERE id=1").fetchone()
    if not row or row["expires_at"] <= now:
        return None
    return dict(row)
