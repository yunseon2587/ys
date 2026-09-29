"""2단계: 수집한 영상의 조회수를 주기적으로 저장하고, 최근 증가량이 큰 영상을 찾는다."""
import time
from datetime import datetime, timedelta, timezone

from . import youtube
from .db import connect

MIN_GAP_SEC = 3600       # 1시간 안에 이미 기록했으면 새 기록을 추가하지 않음 (trend 재실행 시 중복 방지)
MIN_SPAN_HOURS = 0.5     # 기록 간격이 30분도 안 되면 증가량을 계산하지 않음


def chunks(lst, n=50):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def record_snapshot(con, video_id, views, likes, force=False):
    now = time.time()
    if not force:
        last = con.execute("SELECT MAX(taken_at) FROM snapshots WHERE video_id = ?", (video_id,)).fetchone()[0]
        if last and now - last < MIN_GAP_SEC:
            return False
    con.execute("INSERT INTO snapshots(video_id, taken_at, views, likes) VALUES (?,?,?,?)",
                (video_id, now, views, likes))
    return True


def tracked_ids(max_age_days):
    """최근 max_age_days일 안에 올라온 영상만 추적한다 (오래된 영상은 거의 안 오르므로)."""
    since = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as con:
        rows = con.execute("SELECT video_id FROM videos WHERE published_at >= ? ORDER BY published_at DESC",
                           (since,)).fetchall()
    return [r[0] for r in rows]


def take_snapshot(max_age_days=14):
    """추적 중인 영상의 현재 조회수를 저장. 50개당 1유닛. (저장한 개수, 추적 대상 수)를 돌려준다."""
    ids = tracked_ids(max_age_days)
    saved = 0
    for c in chunks(ids):
        data = youtube.get("videos", ttl=0, part="statistics", id=",".join(c))
        with connect() as con:
            for v in data.get("items", []):
                st = v.get("statistics", {})
                views = int(st.get("viewCount", 0) or 0)
                likes = int(st.get("likeCount", 0) or 0)
                record_snapshot(con, v["id"], views, likes, force=True)
                con.execute("UPDATE videos SET views = ?, likes = ? WHERE video_id = ?", (views, likes, v["id"]))
                saved += 1
    return saved, len(ids)


def find_rising(hours=24, min_gain=0):
    """최근 hours시간 동안 조회수 증가량을 계산해 시간당 증가량 순으로 정렬한다.

    기준점: 최신 기록보다 hours시간 이상 앞선 기록 중 가장 최근 것.
    그런 기록이 없으면(추적 시작한 지 얼마 안 됨) 가장 오래된 기록을 쓰고, 실제 간격(span_hours)을 함께 보여준다.
    """
    now = time.time()
    with connect() as con:
        snaps = con.execute("SELECT video_id, taken_at, views FROM snapshots ORDER BY video_id, taken_at").fetchall()
        info = {r["video_id"]: dict(r) for r in con.execute("SELECT * FROM videos")}

    by_vid = {}
    for s in snaps:
        by_vid.setdefault(s["video_id"], []).append(s)

    rows = []
    for vid, ss in by_vid.items():
        latest = ss[-1]
        if now - latest["taken_at"] > hours * 3600 or vid not in info:
            continue  # 최근에 기록이 없는 영상 (추적 끝남)
        cutoff = latest["taken_at"] - hours * 3600
        before = [s for s in ss if s["taken_at"] <= cutoff]
        base = before[-1] if before else ss[0]
        span = (latest["taken_at"] - base["taken_at"]) / 3600
        if span < MIN_SPAN_HOURS:
            continue
        gain = latest["views"] - base["views"]
        if gain < min_gain:
            continue
        v = info[vid]
        rows.append({
            "video_id": vid,
            "title": v["title"],
            "channel": v["channel"],
            "keyword": v["keyword"],
            "thumbnail": v["thumbnail"],
            "published": v["published_at"],
            "subs": v["subs"],
            "views": latest["views"],
            "gain": gain,                                   # 기간 중 늘어난 조회수
            "gain_per_hour": int(gain / span),              # 시간당 증가량
            "growth_pct": round(gain / base["views"] * 100, 1) if base["views"] else None,
            "span_hours": round(span, 1),
            "url": f"https://youtube.com/shorts/{vid}",
        })
    rows.sort(key=lambda r: r["gain_per_hour"], reverse=True)
    return rows


def tracking_status():
    with connect() as con:
        n_videos = con.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        n_snaps, last = con.execute("SELECT COUNT(*), MAX(taken_at) FROM snapshots").fetchone()
    last_str = datetime.fromtimestamp(last).strftime("%m/%d %H:%M") if last else "없음"
    return f"수집된 영상 {n_videos:,}개 · 조회수 기록 {n_snaps:,}건 · 마지막 기록 {last_str}"
