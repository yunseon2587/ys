"""해외(한국·미국·영국)에서 많이 본 예능·시트콤·아이돌 등 웃기거나 자극적인 쇼츠·롱폼을 모은다.
→ 골라서 일본에 있는지 check로 확인."""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from .db import connect
from .trending import chart_ids, enrich, search_ids

REGIONS = {"KR": ("ko", "한국"), "US": ("en", "미국"), "GB": ("en", "영국")}

# 기본 검색어 (분야: 예능·시트콤·몰카·아이돌·토크쇼). 검색 1회 = 100유닛
PRESET_QUERIES = {
    "ko": ["예능 레전드", "시트콤", "몰래카메라", "아이돌 예능"],
    "en": ["sitcom funny", "talk show funny moments", "prank", "SNL"],
}

SORT_KEYS = {
    "views": lambda r: r["views"],
    "vph": lambda r: r["views_per_hour"],
    "outlier": lambda r: r["outlier"] or 0,
}
KINDS = {"all": ("쇼츠", "롱폼"), "shorts": ("쇼츠",), "long": ("롱폼",)}

# 남길 YouTube 카테고리: 22 인물·블로그, 23 코미디, 24 엔터테인먼트
# (빠지는 것: 1 영화·애니메이션(예고편), 10 음악(뮤직비디오), 20 게임, 25 뉴스, 30 영화, 44 예고편 등)
FUN_CATEGORIES = {"22", "23", "24"}

# 저작권이 큰 영상(예고편·뮤직비디오·영화)과 인도 영상을 제목으로 한 번 더 거른다
BLOCKED_TITLE = re.compile(
    r"trailer|teaser|official\s+(music\s+)?video|lyric|\bm/?v\b|music\s+video|full\s+movie|\bmovie\b"
    r"|예고편|티저|뮤직비디오|뮤비|영화"
    r"|bollywood|hindi|\bindian?\b|tollywood|bhojpuri",
    re.IGNORECASE,
)
# 힌디어·타밀어 등 인도 글자(U+0900~0DFF)와 아랍·우르두 글자(U+0600~06FF)
FOREIGN_SCRIPT = re.compile(r"[؀-ۿऀ-෿]")


def search_plan(regions, keywords=None, use_search=True):
    """[(검색어, 언어, 검색 지역)]. 미국·영국은 같은 영어 검색이라 한 번만 하고 채널 국가로 나눈다."""
    if not use_search:
        return []
    plan = []
    if "KR" in regions:
        plan += [(q, "ko", "KR") for q in keywords or PRESET_QUERIES["ko"]]
    en = [r for r in ("US", "GB") if r in regions]
    if en:
        plan += [(q, "en", en[0]) for q in keywords or PRESET_QUERIES["en"]]
    return plan


def estimate_units(regions, keywords=None, use_search=True):
    return len(regions) * 15 + 102 * len(search_plan(regions, keywords, use_search))


def fmt_duration(sec):
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def lang_ok(lang, country):
    """영상 언어가 그 나라 것인지. 언어 정보가 없으면 None (모름)."""
    if not lang:
        return None
    if country == "KR":
        return lang.startswith("ko")
    return lang in ("en", "en-us", "en-gb")  # en-in(인도 영어), hi(힌디어) 등은 제외


def pick_country(r, region, from_chart, regions):
    """이 영상을 어느 나라 영상으로 볼지. 목록에서 뺄 영상이면 None."""
    if FOREIGN_SCRIPT.search(r["title"]):
        return None                                   # 힌디어·아랍어 등 제목
    country = r["channel_country"]
    if country:                                       # 채널이 국가를 설정한 경우: 그대로 믿는다
        if country not in regions or lang_ok(r["lang"], country) is False:
            return None
        return country
    if r["lang"] == "en-gb" and "GB" in regions:
        region = "GB"
    ok = lang_ok(r["lang"], region)
    if ok is False:
        return None                                   # 언어가 다름 (예: 미국 검색에 나온 인도 영어 영상)
    if ok is None and not from_chart:
        return None                                   # 검색 결과인데 국가·언어 정보가 모두 없음 → 확인 불가라 제외
    return region                                     # 그 나라 인기 차트에 있었거나 언어가 맞음


def is_wanted(r, all_categories):
    """예능·코미디 등 원하는 종류인지 (예고편·뮤직비디오·영화 등 저작권 큰 영상 제외)."""
    if all_categories:
        return True
    return r["category_id"] in FUN_CATEGORIES and not BLOCKED_TITLE.search(r["title"])


def translate_link(title):
    """제목을 일본어로 바꿔 보는 구글 번역 링크 (해시태그는 뺀다)."""
    text = re.sub(r"#\S+", "", title).strip() or title
    return f"https://translate.google.com/?sl=auto&tl=ja&op=translate&text={quote(text)}"


def collect(regions=("KR", "US", "GB"), keywords=None, days=7, min_views=500_000,
            sort="views", use_search=True, refresh=False, kind="all", all_categories=False):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    duration = "short" if kind == "shorts" else "any"

    # (영상 ID 목록, 찾은 지역, 인기 차트인지)
    batches = [(chart_ids(region, refresh=refresh), region, True) for region in regions]
    for q, lang, region in search_plan(regions, keywords, use_search):
        batches.append((search_ids(q, days, 1, refresh, region=region, lang=lang, duration=duration), region, False))

    found = {}
    for ids, region, from_chart in batches:
        for r in enrich(ids, refresh, include_long=kind != "shorts"):
            if r["video_id"] in found or r["kind"] not in KINDS[kind]:
                continue
            if r["published"] < since or r["views"] < min_views:
                continue  # 너무 오래된 영상, 조회수 미달
            if not is_wanted(r, all_categories):
                continue  # 예고편·뮤직비디오·영화·게임·뉴스 등
            country = pick_country(r, region, from_chart, regions)
            if country:
                found[r["video_id"]] = {**r, "country": country}
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
                  r["subs"], r["outlier"], r["views_per_hour"], r["published"], r["url"], r["thumbnail"], now))
