"""
일본 쇼츠 소재 찾기 (YouTube Data API v3)

사용법 (자세한 설명은 README.md)
  # 1) 트렌드: 최근 N일간 일본에서 뜬 쇼츠를 outlier·시간당 조회수 순으로
  python jp_shorts_finder.py trend --days 7 --keywords バラエティ 神回 ドッキリ

  # 2) 체크: 이 소재로 일본 쇼츠가 이미 있는지(포화도) 확인
  python jp_shorts_finder.py check --keywords "ケチャップ 逆さま"

  # 3) 오늘 남은 할당량 보기 (할당량 안 씀)
  python jp_shorts_finder.py quota

API 키는 .env 파일의 YT_API_KEY에서 읽습니다.
같은 검색은 12시간 동안 캐시되어 할당량을 다시 쓰지 않습니다 (--refresh로 강제 새로고침).
결과는 화면 출력 + output/ 폴더에 CSV로 저장됩니다.
"""
import argparse
import csv
import sys
from datetime import datetime

from shorts import youtube
from shorts.config import OUTPUT_DIR
from shorts.trending import collect, enrich, estimate_units, search_ids

CSV_FIELDS = ["outlier", "views_per_hour", "views", "subs", "likes", "sec", "published",
              "title", "channel", "keyword", "url", "thumbnail", "video_id"]


def save(rows, name):
    if not rows:
        print("결과 없음")
        return
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{name}_{datetime.now():%Y%m%d_%H%M}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n저장: {path}")


def cmd_trend(a):
    need = estimate_units(len(a.keywords), a.pages)
    print(f"키워드 {len(a.keywords)}개 × {a.pages}페이지 검색 (캐시가 없으면 약 {need}유닛 사용)")
    rows = collect(a.keywords, a.days, a.pages, a.min_views, a.refresh)
    print(f"\n최근 {a.days}일 · 조회수 {a.min_views:,} 이상 · {len(rows)}개\n")
    print(f"{'배수':<7} {'조회수':>11} {'시간당':>8}  제목")
    for r in rows[:a.top]:
        print(f"x{str(r['outlier'] or '-'):<6} {r['views']:>10,}회 {r['views_per_hour']:>7,}/h  "
              f"{r['title'][:40]}  {r['url']}")
    save(rows, "trend")


def cmd_check(a):
    kw = " ".join(a.keywords)
    rows = enrich(search_ids(kw, a.days, 1, a.refresh), a.refresh)
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


def cmd_quota(a):
    pass  # 아래 main()에서 요약을 출력한다


def main():
    # 윈도우 터미널에서 일본어가 깨지지 않도록
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser(description="일본 쇼츠 소재 찾기")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trend", help="최근 인기 쇼츠 수집")
    t.add_argument("--keywords", nargs="+", default=["バラエティ", "神回", "切り抜き"])
    t.add_argument("--days", type=int, default=7)
    t.add_argument("--pages", type=int, default=1, help="키워드당 검색 페이지 수 (1페이지=50개, 100유닛)")
    t.add_argument("--min-views", type=int, default=100000)
    t.add_argument("--top", type=int, default=30)
    t.add_argument("--refresh", action="store_true", help="캐시 무시하고 새로 검색")
    t.set_defaults(func=cmd_trend)
    c = sub.add_parser("check", help="소재의 일본 포화도 확인")
    c.add_argument("--keywords", nargs="+", required=True)
    c.add_argument("--days", type=int, default=365)
    c.add_argument("--refresh", action="store_true", help="캐시 무시하고 새로 검색")
    c.set_defaults(func=cmd_check)
    q = sub.add_parser("quota", help="오늘 사용한 할당량 보기")
    q.set_defaults(func=cmd_quota)
    a = p.parse_args()

    try:
        a.func(a)
    except youtube.YouTubeError as e:
        print(f"\n[오류] {e}")
        print("\n" + youtube.quota_summary())
        sys.exit(1)
    print("\n" + youtube.quota_summary())


if __name__ == "__main__":
    main()
