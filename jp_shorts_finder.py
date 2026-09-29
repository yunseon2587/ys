"""
일본 쇼츠 소재 찾기 (YouTube Data API v3)

사용법 (자세한 설명은 README.md)
  # 1) 트렌드: 최근 N일간 일본에서 뜬 쇼츠를 outlier·시간당 조회수 순으로
  python jp_shorts_finder.py trend --days 7 --keywords バラエティ 神回 ドッキリ

  # 2) 체크: 이 소재로 일본 쇼츠가 이미 있는지(포화도) 확인
  python jp_shorts_finder.py check --keywords "ケチャップ 逆さま"

  # 3) 오늘 남은 할당량 보기 (할당량 안 씀)
  python jp_shorts_finder.py quota

  # 4) 급상승: 수집한 영상 조회수 기록 → 최근 증가량 큰 순으로 보기
  python jp_shorts_finder.py snapshot          # 지금 조회수 기록 (50개당 1유닛)
  python jp_shorts_finder.py rising --hours 24
  python jp_shorts_finder.py schedule --every 3   # 3시간마다 자동 기록 등록

API 키는 .env 파일의 YT_API_KEY에서 읽습니다.
같은 검색은 12시간 동안 캐시되어 할당량을 다시 쓰지 않습니다 (--refresh로 강제 새로고침).
결과는 화면 출력 + output/ 폴더에 CSV로 저장됩니다.
"""
import argparse
import csv
import platform
import sys
from datetime import datetime

from shorts import youtube
from shorts import schedule
from shorts.config import OUTPUT_DIR
from shorts.rising import find_rising, take_snapshot, tracking_status
from shorts.trending import collect, enrich, estimate_units, search_ids

CSV_FIELDS = ["outlier", "views_per_hour", "gain", "gain_per_hour", "growth_pct", "span_hours",
              "views", "subs", "likes", "sec", "published",
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


def cmd_snapshot(a):
    saved, total = take_snapshot(a.max_age)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 최근 {a.max_age}일 영상 {total}개 중 {saved}개 조회수 기록")
    print(tracking_status())


def cmd_rising(a):
    print(tracking_status())
    rows = find_rising(a.hours, a.min_gain)
    if not rows:
        print("\n아직 비교할 기록이 없어요. trend로 영상을 모은 뒤, 1시간 이상 지나서 snapshot을 실행하세요.")
        return
    print(f"\n최근 {a.hours}시간 조회수 증가 순 · {len(rows)}개  (기간이 {a.hours}시간보다 짧으면 실제 기록 간격)\n")
    print(f"{'시간당 증가':>10} {'증가량':>12} {'증가율':>7} {'기간':>6} {'현재 조회수':>12}  제목")
    for r in rows[:a.top]:
        pct = f"+{r['growth_pct']}%" if r["growth_pct"] is not None else "-"
        print(f"{r['gain_per_hour']:>+9,}/h {r['gain']:>+11,}회 {pct:>7} {r['span_hours']:>5}h "
              f"{r['views']:>11,}회  {r['title'][:36]}  {r['url']}")
    save(rows, "rising")


def cmd_schedule(a):
    if platform.system() == "Windows":
        r = schedule.windows_create(a.every)
        if r.returncode == 0:
            print(f"등록 완료: {a.every}시간마다 조회수를 자동 기록해요 (작업 이름: {schedule.TASK_NAME})")
            print("컴퓨터가 켜져 있고 로그인된 동안만 실행돼요. 기록은 data\\snapshot.log 에서 볼 수 있어요.")
            print("그만하려면: python jp_shorts_finder.py unschedule")
        else:
            print("등록 실패:", (r.stderr or r.stdout).strip())
    else:
        print("맥/리눅스는 터미널에서 `crontab -e`를 입력하고 아래 한 줄을 붙여넣은 뒤 저장하세요:\n")
        print(schedule.cron_line(a.every))


def cmd_unschedule(a):
    if platform.system() == "Windows":
        r = schedule.windows_delete()
        print("자동 기록을 해제했어요." if r.returncode == 0 else "해제 실패: " + (r.stderr or r.stdout).strip())
    else:
        print("`crontab -e`를 열고 jp_shorts_finder.py snapshot 줄을 지우세요.")


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
    sn = sub.add_parser("snapshot", help="수집한 영상의 지금 조회수 기록 (50개당 1유닛)")
    sn.add_argument("--max-age", type=int, default=14, help="최근 며칠 안에 올라온 영상만 기록")
    sn.set_defaults(func=cmd_snapshot)
    ri = sub.add_parser("rising", help="최근 조회수 증가량이 큰 영상 보기 (할당량 안 씀)")
    ri.add_argument("--hours", type=float, default=24, help="최근 몇 시간 동안의 증가량")
    ri.add_argument("--min-gain", type=int, default=0, help="이보다 적게 오른 영상은 제외")
    ri.add_argument("--top", type=int, default=30)
    ri.set_defaults(func=cmd_rising)
    sc = sub.add_parser("schedule", help="조회수 자동 기록 등록")
    sc.add_argument("--every", type=int, default=3, help="몇 시간마다 기록할지")
    sc.set_defaults(func=cmd_schedule)
    us = sub.add_parser("unschedule", help="조회수 자동 기록 해제")
    us.set_defaults(func=cmd_unschedule)
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
