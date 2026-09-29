"""해외(한국·미국·영국)에서 조회수가 터진 쇼츠를 모은다. → 골라서 일본에 있는지 check로 확인."""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .db import connect
from .trending import chart_ids, enrich, search_ids

REGIONS = {"KR": ("ko", "한국"), "US": ("en", "미국"), "GB": ("en", "영국")}
DEFAULT_QUERY = "#shorts"
SORT_KEYS = {
    "views": lambda r: r["views"],
    "vph": lambda r: r["views_per_hour"],
    "outlier": lambda r: r["outlier"] or 0,
}


def estimate_units(n_regions, n_keywords, use_search=True):
    per_region = 15 + (102 * max(n_keywords, 1) if use_search else 0)
    return n_regions * per_region


def translate_link(title):
    """제목을 일본어로 바꿔 보는 구글 번역 링크 (해시태그는 뺀다)."""
    text = re.sub(r"#\S+", "", title).strip() or title
    return f"https://translate.google.com/?sl=auto&tl=ja&op=translate&text={quote(text)}"


def collect(regions=("KR", "US", "GB"), keywords=None, days=7, min_views=500_000,
            sort="views", use_search=True, refresh=False):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = {}
    for region in regions:
        lang = REGIONS[region][0]
        ids = chart_ids(region, refresh=refresh)
        if use_search:
            for kw in keywords or [DEFAULT_QUERY]:
                ids += search_ids(kw, days, 1, refresh, region=region, lang=lang)
        for r in enrich(ids, refresh):
            # 채널이 국가를 설정했으면 그걸 믿고, 없으면 찾은 지역으로 본다
            country = r["channel_country"] or region
            if country not in regions or r["published"] < since or r["views"] < min_views:
                continue  # 일본 등 다른 나라 채널, 너무 오래된 영상, 조회수 미달 제외
            found.setdefault(r["video_id"], {**r, "country": country})
    rows = sorted(found.values(), key=SORT_KEYS[sort], reverse=True)
    for r in rows:
        r["translate"] = translate_link(r["title"])
    save(rows)
    return rows


def save(rows):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        for r in rows:
            con.execute("""
                INSERT OR REPLACE INTO overseas_videos(video_id, country, title, channel, views, subs, outlier,
                                                       views_per_hour, published_at, url, thumbnail, found_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (r["video_id"], r["country"], r["title"], r["channel"], r["views"], r["subs"], r["outlier"],
                  r["views_per_hour"], r["published"], r["url"], r["thumbnail"], now))
