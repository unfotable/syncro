"""
The SQLite store — every user asset and every trace of user work lands here.

Tables
------
profiles   one row per ID: identity, password proof, avatar, joined date,
           the removed flag (owner tombstone).
retained   the bus's durable layer: topic -> payload, exactly like a retained
           message on an MQTT broker, but in Python and on disk.
assets     profile pictures extracted from payloads, stored as real blobs and
           served from /assets/<id>.<ext>.
journal    the activity journal — every meaningful thing a user does.
sessions   bearer tokens for the server-side API (export / activity / owner).
"""

import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id         TEXT PRIMARY KEY,
    name       TEXT,
    color      TEXT,
    pic        TEXT,
    joined     INTEGER,
    dev        TEXT,
    salt       TEXT,
    hash       TEXT,
    removed    INTEGER NOT NULL DEFAULT 0,
    friends    INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS retained (
    topic      TEXT PRIMARY KEY,
    payload    TEXT,
    sender     TEXT,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id         TEXT PRIMARY KEY,
    owner      TEXT,
    ext        TEXT,
    mime       TEXT,
    nbytes     INTEGER,
    data       BLOB,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_owner ON assets(owner);
CREATE TABLE IF NOT EXISTS journal (
    seq    INTEGER PRIMARY KEY AUTOINCREMENT,
    uid    TEXT,
    kind   TEXT NOT NULL,
    detail TEXT,
    at     INTEGER NOT NULL,
    ip     TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_uid ON journal(uid);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    uid        TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    last_seen  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_uid ON sessions(uid);
"""


class Store:
    """Thread-safe SQLite persistence.  One connection, one lock — simple and
    bullet-proof for the scale this server targets."""

    def __init__(self, db_path, journal_keep=5000):
        self.db_path = db_path
        self.journal_keep = journal_keep
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._prune_every = 64
        self._writes = 0

    def init(self):
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        return self

    def close(self):
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ #
    # profiles — the identity table
    # ------------------------------------------------------------------ #
    def upsert_profile(self, pid, **fields):
        """Create or update a profile.  Only non-None fields are written."""
        now = int(time.time() * 1000)
        with self._lock:
            row = self._conn.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
            if row is None:
                base = dict(id=pid, created_at=now, updated_at=now, removed=0)
                base.update({k: v for k, v in fields.items() if v is not None})
                cols = ", ".join(base.keys())
                marks = ", ".join("?" for _ in base)
                self._conn.execute(f"INSERT INTO profiles ({cols}) VALUES ({marks})",
                                   list(base.values()))
            else:
                sets, vals = [], []
                for k, v in fields.items():
                    if v is not None:
                        sets.append(f"{k}=?")
                        vals.append(v)
                if sets:
                    vals.append(now)
                    vals.append(pid)
                    self._conn.execute(
                        f"UPDATE profiles SET {', '.join(sets)}, updated_at=? WHERE id=?", vals)
            self._conn.commit()

    def get_profile(self, pid):
        with self._lock:
            row = self._conn.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None

    def list_profiles(self):
        with self._lock:
            rows = self._conn.execute("SELECT * FROM profiles ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def mark_removed(self, pid, removed):
        now = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                "UPDATE profiles SET removed=?, updated_at=? WHERE id=?",
                (1 if removed else 0, now, pid))
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # retained — the durable layer of the live bus
    # ------------------------------------------------------------------ #
    def set_retained(self, topic, payload_text, sender=None):
        now = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                "INSERT INTO retained(topic,payload,sender,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(topic) DO UPDATE SET payload=excluded.payload,"
                "sender=excluded.sender,updated_at=excluded.updated_at",
                (topic, payload_text, sender, now))
            self._conn.commit()

    def clear_retained(self, topic):
        with self._lock:
            self._conn.execute("DELETE FROM retained WHERE topic=?", (topic,))
            self._conn.commit()

    def get_retained(self, topic):
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, updated_at FROM retained WHERE topic=?", (topic,)).fetchone()
        if row is None or row["payload"] is None or row["payload"] == "":
            return None
        return {"topic": topic, "payload": row["payload"], "updated_at": row["updated_at"]}

    def list_retained_all(self, limit=2000):
        with self._lock:
            rows = self._conn.execute(
                "SELECT topic, payload, updated_at FROM retained ORDER BY updated_at DESC "
                "LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows if r["payload"]]

    def count_retained(self):
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) c FROM retained").fetchone()["c"]

    # ------------------------------------------------------------------ #
    # assets — user pictures, kept as real blobs
    # ------------------------------------------------------------------ #
    def save_asset(self, aid, owner, ext, mime, blob):
        """INSERT OR IGNORE — content-addressed ids make saving idempotent."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO assets(id,owner,ext,mime,nbytes,data,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (aid, owner, ext, mime, len(blob), blob, int(time.time() * 1000)))
            self._conn.commit()
            return cur.rowcount > 0

    def get_asset(self, aid):
        with self._lock:
            row = self._conn.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
        return dict(row) if row else None

    def assets_for(self, owner, with_data=False):
        cols = "id,owner,ext,mime,nbytes,created_at" + (",data" if with_data else "")
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {cols} FROM assets WHERE owner=? ORDER BY created_at DESC", (owner,)).fetchall()
        return [dict(r) for r in rows]

    def count_assets(self):
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) c FROM assets").fetchone()["c"]

    # ------------------------------------------------------------------ #
    # journal — the running story of what every user did
    # ------------------------------------------------------------------ #
    def journal(self, uid, kind, detail=None, ip=None):
        at = int(time.time() * 1000)
        with self._lock:
            self._conn.execute(
                "INSERT INTO journal(uid,kind,detail,at,ip) VALUES(?,?,?,?,?)",
                (uid, kind, json.dumps(detail, ensure_ascii=False) if detail else None, at, ip))
            self._writes += 1
            if self._writes % self._prune_every == 0:
                self._conn.execute(
                    "DELETE FROM journal WHERE seq <= "
                    "(SELECT seq FROM journal ORDER BY seq DESC LIMIT 1 OFFSET ?)",
                    (self.journal_keep,))
            self._conn.commit()

    def journal_for(self, uid, limit=200):
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq,uid,kind,detail,at,ip FROM journal WHERE uid=? "
                "ORDER BY seq DESC LIMIT ?", (uid, limit)).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["detail"] = json.loads(item["detail"]) if item["detail"] else None
            except (TypeError, ValueError):
                pass
            out.append(item)
        return out

    def count_journal(self):
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) c FROM journal").fetchone()["c"]

    # ------------------------------------------------------------------ #
    # sessions — bearer tokens for the server-side API
    # ------------------------------------------------------------------ #
    def session_create(self, token, uid, ttl_hours):
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions(token,uid,created_at,last_seen) VALUES(?,?,?,?)",
                (token, uid, now, now))
            self._conn.commit()

    def session_get(self, token, ttl_hours):
        if not token:
            return None
        now = int(time.time())
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
            if row is None or now - row["last_seen"] > ttl_hours * 3600:
                return None
            self._conn.execute(
                "UPDATE sessions SET last_seen=? WHERE token=?", (now, token))
            self._conn.commit()
        return dict(row)

    def session_drop(self, token):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            self._conn.commit()

    def sessions_drop_for(self, uid):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE uid=?", (uid,))
            self._conn.commit()

    # ------------------------------------------------------------------ #
    def counts(self):
        with self._lock:
            users = self._conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"]
        return {
            "profiles": users,
            "retained": self.count_retained(),
            "assets": self.count_assets(),
            "journal": self.count_journal(),
        }
