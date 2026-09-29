"""1단계: 최근 N일간 일본 인기 쇼츠를 키워드로 수집한다."""
from datetime import datetime, timedelta, timezone

from . import youtube
from .config import SEARCH_TTL, STATS_TTL
from .db import connect
from .metrics import MAX_SHORT_SEC, iso_to_sec, outlier, views_per_hour
from .rising import record_snapshot


def chunks(lst, n=50):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def estimate_units(n_keywords, pages):
    """대략적인 예상 사용량: 검색 100유닛 × 횟수 + 영상/채널 조회 몇 유닛."""
    return n_keywords * pages * 100 + n_keywords * pages * 2


def search_ids(keyword, days, pages, refresh=False, region="JP", lang="ja", duration="short"):
    """duration: short(4분 미만) / medium(4~20분) / long(20분 초과) / any(전부)"""
    # 날짜 단위로 맞춰야 같은 날 같은 검색이 캐시에 걸린다
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    ids, token = [], None
    for _ in range(pages):
        p = dict(part="id", q=keyword, type="video", maxResults=50,
                 regionCode=region, relevanceLanguage=lang, videoDuration=duration,
                 order="viewCount", publishedAfter=after)
        if token:
            p["pageToken"] = token
        data = youtube.get("search", ttl=0 if refresh else SEARCH_TTL, **p)
        ids += [it["id"]["videoId"] for it in data.get("items", []) if "videoId" in it.get("id", {})]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids


def chart_ids(region, pages=4, refresh=False):
    """그 나라 '인기 급상승' 차트의 영상 ID (50개당 1유닛). 쇼츠가 아닌 영상도 섞여 있다."""
    ids, token = [], None
    for _ in range(pages):
        p = dict(part="id", chart="mostPopular", regionCode=region, maxResults=50)
        if token:
            p["pageToken"] = token
        data = youtube.get("videos", ttl=0 if refresh else SEARCH_TTL, **p)
        ids += [it["id"] for it in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids


def enrich(ids, refresh=False, include_long=False):
    """include_long=True면 3분 넘는 롱폼도 남긴다 (기본은 쇼츠만)."""
    ttl = 0 if refresh else STATS_TTL
    videos = []
    for c in chunks(list(dict.fromkeys(ids))):
        data = youtube.get("videos", ttl=ttl, part="snippet,statistics,contentDetails", id=",".join(c))
        videos += data.get("items", [])
    ch_ids = sorted({v["snippet"]["channelId"] for v in videos})
    subs, country = {}, {}
    for c in chunks(ch_ids):
        # snippet을 같이 받아도 비용은 1유닛 그대로 (채널 국가 정보용)
        for ch in youtube.get("channels", ttl=ttl, part="snippet,statistics", id=",".join(c)).get("items", []):
            subs[ch["id"]] = int(ch["statistics"].get("subscriberCount", 0) or 0)
            country[ch["id"]] = ch.get("snippet", {}).get("country", "")

    now = datetime.now(timezone.utc)
    rows = []
    for v in videos:
        sec = iso_to_sec(v["contentDetails"].get("duration"))
        is_short = 0 < sec <= MAX_SHORT_SEC
        if sec == 0 or (not is_short and not include_long):
            continue
        st, sn = v["statistics"], v["snippet"]
        views = int(st.get("viewCount", 0) or 0)
        s = subs.get(sn["channelId"], 0)
        thumbs = sn.get("thumbnails", {})
        thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        rows.append({
            "video_id": v["id"],
            "title": sn["title"],
            "channel": sn["channelTitle"],
            "channel_id": sn["channelId"],
            "channel_country": country.get(sn["channelId"], ""),  # 채널이 설정한 국가 (없으면 빈칸)
            "views": views,
            "subs": s,
            "outlier": outlier(views, s),                               # 구독자 대비 조회수 배수
            "views_per_hour": views_per_hour(views, sn["publishedAt"], now),  # 조회수 속도
            "likes": int(st.get("likeCount", 0) or 0),
            "sec": sec,
            "published": sn["publishedAt"],
            "thumbnail": thumb,
            "kind": "쇼츠" if is_short else "롱폼",
            "url": f"https://youtube.com/shorts/{v['id']}" if is_short else f"https://youtube.com/watch?v={v['id']}",
        })
    return rows


def save_videos(rows, keyword):
    """수집한 영상을 DB에 저장 (2단계 급상승 추적 대상이 된다)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        for r in rows:
            record_snapshot(con, r["video_id"], r["views"], r["likes"])
            con.execute("""
                INSERT INTO videos(video_id, title, channel_id, channel, published_at, duration_sec,
                                   thumbnail, subs, views, likes, keyword, first_seen, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title=excluded.title, subs=excluded.subs, views=excluded.views,
                    likes=excluded.likes, thumbnail=excluded.thumbnail, last_seen=excluded.last_seen
            """, (r["video_id"], r["title"], r["channel_id"], r["channel"], r["published"], r["sec"],
                  r["thumbnail"], r["subs"], r["views"], r["likes"], keyword, now, now))


def collect(keywords, days=7, pages=1, min_views=0, refresh=False):
    """키워드별로 검색 → 상세정보 → outlier·시간당 조회수 순 정렬."""
    by_id = {}
    for kw in keywords:
        rows = enrich(search_ids(kw, days, pages, refresh), refresh)
        save_videos(rows, kw)
        for r in rows:
            by_id.setdefault(r["video_id"], {**r, "keyword": kw})
    rows = [r for r in by_id.values() if r["views"] >= min_views]
    rows.sort(key=lambda r: (r["outlier"] or 0, r["views_per_hour"]), reverse=True)
    return rows
