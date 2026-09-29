"""
일본 쇼츠 소재 찾기 MVP (YouTube Data API v3)

사용법
  pip install requests
  export YT_API_KEY="발급받은_키"

  # 1) 트렌드: 최근 N일간 일본에서 조회수 높은 쇼츠 뽑기
  python jp_shorts_finder.py trend --days 7 --keywords バラエティ 神回 ドッキリ

  # 2) 체크: 이 소재로 일본 쇼츠가 이미 있는지(포화도) 확인
  python jp_shorts_finder.py check --keywords "ケチャップ 逆さま"

결과는 화면 출력 + CSV 파일로 저장됩니다.
할당량: search 1회 = 100유닛, 기본 하루 10,000유닛 → 키워드 검색 약 90회/일
"""
import argparse, csv, os, re, sys
from datetime import datetime, timedelta, timezone
import requests

API = "https://www.googleapis.com/youtube/v3"
KEY = os.environ.get("YT_API_KEY")
MAX_SHORT_SEC = 180  # 현재 쇼츠 최대 길이 기준


def get(endpoint, **params):
    params["key"] = KEY
    r = requests.get(f"{API}/{endpoint}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def iso_to_sec(d):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def search_ids(keyword, days, pages):
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids, token = [], None
    for _ in range(pages):
        p = dict(part="id", q=keyword, type="video", maxResults=50,
                 regionCode="JP", relevanceLanguage="ja", videoDuration="short",
                 order="viewCount", publishedAfter=after)
        if token:
            p["pageToken"] = token
        data = get("search", **p)
        ids += [it["id"]["videoId"] for it in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token:
            break
    return ids


def chunks(lst, n=50):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def enrich(ids):
    videos = []
    for c in chunks(list(dict.fromkeys(ids))):
        data = get("videos", part="snippet,statistics,contentDetails", id=",".join(c))
        videos += data.get("items", [])
    ch_ids = list({v["snippet"]["channelId"] for v in videos})
    subs = {}
    for c in chunks(ch_ids):
        for ch in get("channels", part="statistics", id=",".join(c)).get("items", []):
            subs[ch["id"]] = int(ch["statistics"].get("subscriberCount", 0) or 0)

    now = datetime.now(timezone.utc)
    rows = []
    for v in videos:
        sec = iso_to_sec(v["contentDetails"].get("duration"))
        if sec == 0 or sec > MAX_SHORT_SEC:
            continue
        st, sn = v["statistics"], v["snippet"]
        views = int(st.get("viewCount", 0))
        pub = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        hours = max((now - pub).total_seconds() / 3600, 1)
        s = subs.get(sn["channelId"], 0)
        rows.append({
            "title": sn["title"],
            "channel": sn["channelTitle"],
            "views": views,
            "subs": s,
            "outlier": round(views / s, 1) if s else None,  # 구독자 대비 조회수 배수
            "views_per_hour": int(views / hours),          # 조회수 속도
            "likes": int(st.get("likeCount", 0) or 0),
            "sec": sec,
            "published": sn["publishedAt"][:10],
            "url": f"https://youtube.com/shorts/{v['id']}",
        })
    return rows


def save(rows, name):
    if not rows:
        print("결과 없음")
        return
    path = f"{name}_{datetime.now():%Y%m%d_%H%M}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"\n저장: {path}")


def cmd_trend(a):
    ids = []
    for kw in a.keywords:
        ids += search_ids(kw, a.days, a.pages)
    rows = enrich(ids)
    rows.sort(key=lambda r: (r["outlier"] or 0, r["views_per_hour"]), reverse=True)
    rows = [r for r in rows if r["views"] >= a.min_views]
    for r in rows[:a.top]:
        print(f"x{str(r['outlier'] or '-'):<6} {r['views']:>10,}회 {r['views_per_hour']:>7,}/h  {r['title'][:40]}  {r['url']}")
    save(rows, "trend")


def cmd_check(a):
    kw = " ".join(a.keywords)
    rows = enrich(search_ids(kw, a.days, 1))
    rows.sort(key=lambda r: r["views"], reverse=True)
    total = sum(r["views"] for r in rows)
    print(f"'{kw}' 관련 일본 쇼츠 {len(rows)}개 / 합계 조회수 {total:,}")
    if len(rows) == 0:
        print("→ 아직 일본판이 거의 없음: 선점 기회")
    elif len(rows) < 5:
        print("→ 일부 존재: 차별화하면 가능")
    else:
        print("→ 이미 많이 만들어짐: 포화 가능성 높음")
    for r in rows[:10]:
        print(f"{r['views']:>10,}회  {r['channel'][:15]:<15} {r['title'][:40]}  {r['url']}")
    save(rows, "check")


def main():
    if not KEY:
        sys.exit("환경변수 YT_API_KEY를 설정하세요.")
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trend")
    t.add_argument("--keywords", nargs="+", default=["バラエティ", "神回", "切り抜き"])
    t.add_argument("--days", type=int, default=7)
    t.add_argument("--pages", type=int, default=1)
    t.add_argument("--min-views", type=int, default=100000)
    t.add_argument("--top", type=int, default=30)
    t.set_defaults(func=cmd_trend)
    c = sub.add_parser("check")
    c.add_argument("--keywords", nargs="+", required=True)
    c.add_argument("--days", type=int, default=365)
    c.set_defaults(func=cmd_check)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
