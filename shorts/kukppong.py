"""국뽕 소재 찾기.

- bench  : 조회수 높은 한국 국뽕 쇼츠 (벤치마킹용 — 어떤 구조가 터지는지 분석)
- source : 한국을 경험하는 외국인 크리에이터 영상 (원본 소스 — 신인 채널 발굴 포함)
"""
import re
from datetime import datetime, timedelta, timezone

from .db import connect
from .trending import enrich, search_ids

# 검색 1회 = 100유닛
PRESETS = {
    "bench": {"lang": "ko", "region": "KR", "duration": "short",
              "queries": ["외국인 반응 한국", "한국 여행 외국인", "외국인 한국음식 반응", "해외반응 한국"]},
    "source": {"lang": "en", "region": "US", "duration": "any",
               "queries": ["first time in Korea", "Korean food reaction", "foreigner living in Korea",
                           "Korea travel vlog"]},
}
MODE_NAME = {"bench": "벤치마킹용 한국 국뽕 쇼츠", "source": "원본 소스: 한국을 경험하는 외국인 영상"}

# 힌디어·타밀어 등 인도 글자, 아랍·우르두 글자
FOREIGN_SCRIPT = re.compile(r"[؀-ۿऀ-෿]")
SORT_KEYS = {
    "views": lambda r: r["views"],
    "vph": lambda r: r["views_per_hour"],
    "outlier": lambda r: r["outlier"] or 0,
}


def estimate_units(modes, keywords=None):
    return sum(102 * len(keywords or PRESETS[m]["queries"]) for m in modes)


def channel_url(channel_id):
    return f"https://youtube.com/channel/{channel_id}"


def collect(mode, keywords=None, days=30, min_views=100_000, max_subs=None, sort="outlier", refresh=False):
    """mode별 검색어로 모아서 정렬. max_subs를 주면 그 이하 구독자 채널만 (신인 발굴)."""
    preset = PRESETS[mode]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in keywords or preset["queries"]:
        ids += search_ids(q, days, 1, refresh, region=preset["region"], lang=preset["lang"],
                          duration=preset["duration"])
    found = {}
    for r in enrich(ids, refresh, include_long=preset["duration"] != "short"):
        if r["published"] < since or r["views"] < min_views:
            continue
        if FOREIGN_SCRIPT.search(r["title"]):
            continue
        if mode == "bench" and r["kind"] != "쇼츠":
            continue
        if max_subs is not None and r["subs"] > max_subs:
            continue
        found[r["video_id"]] = {**r, "mode": mode, "channel_url": channel_url(r["channel_id"])}
    rows = sorted(found.values(), key=SORT_KEYS[sort], reverse=True)
    save(rows)
    return rows


def save(rows):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        for r in rows:
            con.execute("""
                INSERT OR REPLACE INTO kukppong_videos(video_id, mode, kind, duration_sec, title, channel, channel_id,
                                                       views, subs, outlier, views_per_hour, published_at, url,
                                                       thumbnail, found_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (r["video_id"], r["mode"], r["kind"], r["sec"], r["title"], r["channel"], r["channel_id"],
                  r["views"], r["subs"], r["outlier"], r["views_per_hour"], r["published"], r["url"],
                  r["thumbnail"], now))
