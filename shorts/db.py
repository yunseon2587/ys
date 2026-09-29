"""SQLite 저장소: API 캐시, 할당량 사용 기록, 수집한 영상."""
import sqlite3

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key  TEXT PRIMARY KEY,
    endpoint   TEXT NOT NULL,
    response   TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS quota_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    day      TEXT NOT NULL,      -- 태평양 시간 기준 날짜 (YouTube 할당량 리셋 기준)
    endpoint TEXT NOT NULL,
    units    INTEGER NOT NULL,
    at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quota_day ON quota_log(day);
CREATE TABLE IF NOT EXISTS videos (
    video_id     TEXT PRIMARY KEY,
    title        TEXT,
    channel_id   TEXT,
    channel      TEXT,
    published_at TEXT,
    duration_sec INTEGER,
    thumbnail    TEXT,
    subs         INTEGER,
    views        INTEGER,
    likes        INTEGER,
    keyword      TEXT,
    first_seen   TEXT,
    last_seen    TEXT
);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
