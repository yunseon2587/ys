"""해외(한국·미국·영국)에서 조회수가 터진 쇼츠·롱폼을 모은다. → 골라서 일본에 있는지 check로 확인."""
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


# 힌디어·타밀어 등 인도 글자(U+0900~0DFF)와 아랍·우르두 글자(U+0600~06FF)
FOREIGN_SCRIPT = re.compile(r"[\u0600-\u06FF\u0900-\u0DFF]")
MUSIC_CATEGORY = "10"  # YouTube 카테고리 '음악' (뮤직비디오·음원)
KINDS = {"all": ("쇼츠", "롱폼"), "shorts": ("쇼츠",), "long": ("롱폼",)}


def _searches(kind, keywords, use_search):
    """나라마다 할 검색 목록 [(검색어, 길이 조건)]. 롱폼은 인기 차트로 충분해서 키워드가 있을 때만 검색한다."""
    if not use_search:
        return []
    if keywords:
        return [(kw, "short" if kind == "shorts" else "any") for kw in keywords]
    return [] if kind == "long" else [(DEFAULT_QUERY, "short")]


def estimate_units(n_regions, keywords=None, use_search=True, kind="all"):
    return n_regions * (15 + 102 * len(_searches(kind, keywords, use_search)))


def fmt_duration(sec):
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def lang_ok(lang, country):
    """영상 언어가 그 나라 것인지. 언어 정보가 없으면 None (모름)."""
    if not lang:
        return None
    if country == "KR":
        return lang.startswith("ko")
    return lang in ("en", "en-us", "en-gb")  # en-in(인도 영어) 등은 제외


def pick_country(r, region, from_chart, regions):
    """이 영상을 어느 나라 영상으로 볼지. 목록에서 뺄 영상이면 None."""
    if FOREIGN_SCRIPT.search(r["title"]):
        return None                                   # 힌디어·아랍어 등 제목
    country = r["channel_country"]
    if country:                                       # 채널이 국가를 설정한 경우: 그대로 믿는다
        if country not in regions or lang_ok(r["lang"], country) is False:
            return None
        return country
    ok = lang_ok(r["lang"], region)
    if ok is False:
        return None                                   # 언어가 다름 (예: 미국 검색에 나온 인도 영어 영상)
    if ok is None and not from_chart:
        return None                                   # 검색 결과인데 국가·언어 정보가 모두 없음 → 확인 불가라 제외
    return region                                     # 그 나라 인기 차트에 있었거나 언어가 맞음


def translate_link(title):
    """제목을 일본어로 바꿔 보는 구글 번역 링크 (해시태그는 뺀다)."""
    text = re.sub(r"#\S+", "", title).strip() or title
    return f"https://translate.google.com/?sl=auto&tl=ja&op=translate&text={quote(text)}"


def collect(regions=("KR", "US", "GB"), keywords=None, days=7, min_views=500_000,
            sort="views", use_search=True, refresh=False, kind="all", include_music=False):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = {}
    for region in regions:
        lang = REGIONS[region][0]
        ids = chart_ids(region, refresh=refresh)
        in_chart = set(ids)
        for kw, duration in _searches(kind, keywords, use_search):
            ids += search_ids(kw, days, 1, refresh, region=region, lang=lang, duration=duration)
        for r in enrich(ids, refresh, include_long=kind != "shorts"):
            if r["kind"] not in KINDS[kind]:
                continue
            if not include_music and r["category_id"] == MUSIC_CATEGORY:
                continue  # 뮤직비디오는 저작권 때문에 편집·재업로드가 어려워 기본 제외
            if r["published"] < since or r["views"] < min_views:
                continue  # 너무 오래된 영상, 조회수 미달
            country = pick_country(r, region, r["video_id"] in in_chart, regions)
            if not country:
                continue  # 일본·인도 등 다른 나라 영상
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
                INSERT OR REPLACE INTO overseas_videos(video_id, country, kind, duration_sec, title, channel, views,
                                                       subs, outlier, views_per_hour, published_at, url,
                                                       thumbnail, found_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (r["video_id"], r["country"], r["kind"], r["sec"], r["title"], r["channel"], r["views"],
                  r["subs"], r["outlier"],
                  r["views_per_hour"], r["published"], r["url"], r["thumbnail"], now))
