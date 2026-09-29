"""YouTube Data API 호출. 같은 요청은 SQLite에 캐시하고, 실제 호출한 만큼 할당량을 기록한다."""
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .config import DAILY_QUOTA, yt_key
from .db import connect

API = "https://www.googleapis.com/youtube/v3"
# 엔드포인트별 할당량 비용 (https://developers.google.com/youtube/v3/determine_quota_cost)
COST = {"search": 100, "videos": 1, "channels": 1}

# 이번 실행에서의 통계 (화면 표시용)
stats = {"api_calls": 0, "cache_hits": 0, "units": 0}


class YouTubeError(Exception):
    pass


class QuotaError(YouTubeError):
    pass


def quota_day():
    # YouTube 할당량은 태평양 시간 자정(한국 시간 오후 4~5시)에 초기화된다
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def used_today():
    with connect() as con:
        row = con.execute("SELECT COALESCE(SUM(units), 0) FROM quota_log WHERE day = ?",
                          (quota_day(),)).fetchone()
    return row[0]


def remaining():
    return DAILY_QUOTA - used_today()


def quota_summary():
    used = used_today()
    return (f"오늘 할당량: {used:,} / {DAILY_QUOTA:,} 유닛 사용 (남음 {DAILY_QUOTA - used:,})"
            f" · 이번 실행: API {stats['api_calls']}회({stats['units']}유닛), 캐시 {stats['cache_hits']}회")


def _cache_key(endpoint, params):
    return endpoint + "?" + json.dumps(params, sort_keys=True, ensure_ascii=False)


def _error_message(r):
    try:
        err = r.json()["error"]
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", "")
    except Exception:
        reason, msg = "", r.text[:200]
    if reason in ("quotaExceeded", "dailyLimitExceeded"):
        raise QuotaError("YouTube 오늘 할당량을 모두 썼어요. 태평양 시간 자정(한국 오후 4~5시)에 초기화됩니다.")
    if reason in ("keyInvalid",) or "API key not valid" in msg:
        raise YouTubeError(".env의 YT_API_KEY가 올바르지 않아요. 키를 다시 복사해 붙여넣어 주세요.")
    if reason == "accessNotConfigured" or "has not been used" in msg:
        raise YouTubeError("Google Cloud에서 'YouTube Data API v3'를 사용 설정(Enable)해 주세요.")
    raise YouTubeError(f"YouTube API 오류 {r.status_code}: {msg or reason}")


def get(endpoint, ttl=0, **params):
    """ttl초 이내에 같은 요청을 한 적이 있으면 캐시에서 돌려준다 (ttl=0이면 항상 새로 호출)."""
    key = _cache_key(endpoint, params)
    if ttl > 0:
        with connect() as con:
            row = con.execute("SELECT response, fetched_at FROM api_cache WHERE cache_key = ?",
                              (key,)).fetchone()
        if row and time.time() - row["fetched_at"] < ttl:
            stats["cache_hits"] += 1
            return json.loads(row["response"])

    if not yt_key():
        raise YouTubeError(".env 파일에 YT_API_KEY가 없어요. README의 '2. API 키 넣기'를 참고하세요.")
    cost = COST.get(endpoint, 1)
    if remaining() < cost:
        raise QuotaError(f"남은 할당량({remaining()})이 부족해서 {endpoint} 호출({cost}유닛)을 멈췄어요.")

    r = requests.get(f"{API}/{endpoint}", params={**params, "key": yt_key()}, timeout=20)
    if not r.ok:
        _error_message(r)
    data = r.json()

    now = time.time()
    with connect() as con:
        con.execute("INSERT INTO quota_log(day, endpoint, units, at) VALUES (?,?,?,?)",
                    (quota_day(), endpoint, cost, now))
        con.execute("INSERT OR REPLACE INTO api_cache VALUES (?,?,?,?)",
                    (key, endpoint, json.dumps(data, ensure_ascii=False), now))
    stats["api_calls"] += 1
    stats["units"] += cost
    return data
