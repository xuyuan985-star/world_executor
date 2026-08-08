import sqlite3
import threading
from pathlib import Path

from config import settings

_local = threading.local()


def conn():
    db = getattr(_local, "conn", None)
    if db is None:
        path = settings.runtime_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path))
        db.row_factory = sqlite3.Row
        _local.conn = db
        init(db)
    return db


SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    room TEXT,
    status TEXT NOT NULL,
    started_at TEXT DEFAULT (datetime('now', 'localtime')),
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS fail_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    fail_type TEXT NOT NULL,
    fail_reason TEXT,
    screenshot_path TEXT,
    logged_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS repair_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    repaired_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    success INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    duration_ms INTEGER,
    recorded_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS state_observation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    value TEXT NOT NULL,
    observer TEXT NOT NULL,
    confidence REAL,
    observed_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_progress_target ON progress(target_id);
CREATE INDEX IF NOT EXISTS idx_fail_target ON fail_log(target_id);
CREATE INDEX IF NOT EXISTS idx_state_target ON state_observation(target_id);
"""


def init(db):
    db.executescript(SCHEMA)
    db.commit()


def record_state_observation(target_id, value, observer, confidence=None):
    db = conn()
    db.execute(
        "INSERT INTO state_observation (target_id, value, observer, confidence) VALUES (?, ?, ?, ?)",
        (target_id, value, observer, confidence),
    )
    db.commit()


def record_fail(execution_id, target_id, fail_type, reason, screenshot_path=None):
    db = conn()
    db.execute(
        "INSERT INTO fail_log (execution_id, target_id, fail_type, fail_reason, screenshot_path) VALUES (?, ?, ?, ?, ?)",
        (execution_id, target_id, fail_type, reason, screenshot_path),
    )
    db.commit()


def record_progress(execution_id, target_id, room, status):
    db = conn()
    db.execute(
        "UPDATE progress SET status=?, room=?, ended_at=CASE WHEN ? IN ('DONE','ABORT') THEN datetime('now','localtime') ELSE ended_at END WHERE execution_id=? AND target_id=?",
        (status, room, status, execution_id, target_id),
    )
    db.commit()


def start_progress(execution_id, target_id, room):
    db = conn()
    db.execute(
        "INSERT INTO progress (execution_id, target_id, room, status) VALUES (?, ?, ?, 'RUNNING')",
        (execution_id, target_id, room),
    )
    db.commit()
