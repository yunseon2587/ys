"""장르 비교: 일본 쇼츠에서 장르별로 실제 성과가 어떤지, 잘하는 일본 채널은 누구인지.

YouTube 검색 '조회수 순' 상위 영상을 기준으로 계산한다 (장르끼리 같은 기준으로 비교하기 위한 것).
"""
import statistics
from datetime import datetime, timedelta, timezone

from .trending import enrich, search_ids

# 장르 키: (이름, 일본어 검색어). 검색 1회 = 100유닛
GENRES = {
    "idol": ("아이돌 자컨", ["韓国アイドル 日本語字幕", "K-POP アイドル 面白い", "SEVENTEEN 日本語字幕"]),
    "kvariety": ("한국 예능", ["韓国バラエティ 日本語字幕", "ランニングマン 日本語字幕", "韓国 バラエティ 面白い"]),
    "usvariety": ("미국 버라이어티", ["海外バラエティ 日本語字幕", "海外 トーク番組 日本語字幕", "海外 ドッキリ 日本語字幕"]),
    "jpreaction": ("일본판 국뽕(海外の反応)", ["海外の反応 日本", "外国人 日本 感動", "日本旅行 外国人 反応"]),
}
GOAL_VIEWS = 10_000_000  # 쇼츠 수익화 조건: 최근 90일 조회수 1000만


def estimate_units(genres, keywords=None):
    if keywords:
        return 102 * len(keywords)
    return sum(102 * len(GENRES[g][1]) for g in genres)


def summarize(name, queries, rows):
    """한 장르의 영상 목록 → 요약 수치 + 잘하는 채널 + 조회수 상위 영상."""
    views = [r["views"] for r in rows]
    outliers = [r["outlier"] for r in rows if r["outlier"]]
    med = int(statistics.median(views)) if views else 0

    channels = {}
    for r in rows:
        c = channels.setdefault(r["channel_id"], {"channel": r["channel"], "channel_id": r["channel_id"],
                                                 "subs": r["subs"], "videos": 0, "views": 0})
        c["videos"] += 1
        c["views"] += r["views"]
    top_channels = sorted(channels.values(), key=lambda c: c["views"], reverse=True)

    return {
        "name": name,
        "queries": queries,
        "count": len(rows),
        "median_views": med,
        "over_100k": sum(v >= 100_000 for v in views),
        "over_1m": sum(v >= 1_000_000 for v in views),
        "median_outlier": round(statistics.median(outliers), 1) if outliers else None,
        # 영상 1개가 이 장르의 중간 조회수만큼 나온다고 칠 때, 1000만까지 필요한 개수 (참고용)
        "videos_for_goal": -(-GOAL_VIEWS // med) if med else None,
        "channels": top_channels,
        "videos": sorted(rows, key=lambda r: r["views"], reverse=True),
    }


def compare(genres=tuple(GENRES), keywords=None, days=30, refresh=False):
    """장르별로 일본 쇼츠를 검색해 요약한다. keywords를 주면 그걸로 '직접 입력' 장르 하나만 본다."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    targets = [("직접 입력", keywords)] if keywords else [GENRES[g] for g in genres]
    results = []
    for name, queries in targets:
        ids = []
        for q in queries:
            ids += search_ids(q, days, 1, refresh, region="JP", lang="ja")
        rows = [r for r in enrich(ids, refresh) if r["published"] >= since]
        results.append(summarize(name, queries, rows))
    return results
