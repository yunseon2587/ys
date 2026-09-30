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
CREATE TABLE IF NOT EXISTS snapshots (
    video_id TEXT NOT NULL,
    taken_at REAL NOT NULL,      -- 유닉스 시간(초)
    views    INTEGER NOT NULL,
    likes    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(video_id, taken_at);
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key  TEXT PRIMARY KEY,
    response   TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jp_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at      TEXT,
    region          TEXT,     -- KR / US / 직접입력
    source_video_id TEXT,
    source_title    TEXT,
    source_views    INTEGER,
    source_url      TEXT,
    thumbnail       TEXT,
    topic_ko        TEXT,     -- 무슨 내용인지 한국어 요약
    jp_query        TEXT,     -- 일본 검색에 쓴 키워드
    verdict         TEXT,     -- 선점 가능 / 차별화 필요 / 포화
    reason          TEXT,
    similar_count   INTEGER,
    hit_count       INTEGER,
    similar_json    TEXT      -- 비슷한 일본 쇼츠 목록
);
CREATE TABLE IF NOT EXISTS kukppong_videos (
    video_id       TEXT PRIMARY KEY,
    mode           TEXT,      -- bench(한국 국뽕 쇼츠) / source(외국인 원본)
    kind           TEXT,      -- 쇼츠 / 롱폼
    duration_sec   INTEGER,
    title          TEXT,
    channel        TEXT,
    channel_id     TEXT,
    views          INTEGER,
    subs           INTEGER,
    outlier        REAL,
    views_per_hour INTEGER,
    published_at   TEXT,
    url            TEXT,
    thumbnail      TEXT,
    found_at       TEXT
);
CREATE TABLE IF NOT EXISTS overseas_videos (
    video_id       TEXT PRIMARY KEY,
    country        TEXT,      -- KR / US / GB
    kind           TEXT,      -- 쇼츠 / 롱폼
    duration_sec   INTEGER,
    title          TEXT,
    channel        TEXT,
    views          INTEGER,
    subs           INTEGER,
    outlier        REAL,
    views_per_hour INTEGER,
    published_at   TEXT,
    url            TEXT,
    thumbnail      TEXT,
    found_at       TEXT
);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _add_missing_columns(con)
    return con


# 예전 버전으로 만든 DB에 새로 생긴 칸을 추가한다 (데이터는 그대로 유지)
NEW_COLUMNS = {"overseas_videos": {"kind": "TEXT", "duration_sec": "INTEGER"}}


def _add_missing_columns(con):
    for table, cols in NEW_COLUMNS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols.items():
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
