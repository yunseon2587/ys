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

  # 5) 해외(한국·미국·영국)에서 터진 쇼츠 모으기 → 골라서 check로 일본에 있는지 확인 (무료)
  python jp_shorts_finder.py overseas --days 7              # 쇼츠+롱폼 (--type shorts / long)
  python jp_shorts_finder.py check --keywords "ケチャップ 逆さま"

  # 6) 일본판 확인: 한국·미국에서 뜬 쇼츠가 일본에도 있는지 (Claude API 사용)
  python jp_shorts_finder.py jpcheck --region KR --limit 5
  python jp_shorts_finder.py jpcheck --region US --keywords "life hack" --limit 5
  python jp_shorts_finder.py jpcheck --title "케첩 거꾸로 짜기 챌린지"

API 키는 .env 파일의 YT_API_KEY, ANTHROPIC_API_KEY에서 읽습니다.
같은 검색은 12시간 동안 캐시되어 할당량을 다시 쓰지 않습니다 (--refresh로 강제 새로고침).
결과는 화면 출력 + output/ 폴더에 CSV로 저장됩니다.
"""
import argparse
import csv
import platform
import sys
from datetime import datetime

from shorts import youtube
from shorts import jp_check, overseas, schedule
from shorts.claude_ai import ClaudeError
from shorts.claude_ai import client as claude_client
from shorts.config import OUTPUT_DIR
from shorts.rising import find_rising, take_snapshot, tracking_status
from shorts.trending import collect, estimate_units

CSV_FIELDS = ["outlier", "views_per_hour", "gain", "gain_per_hour", "growth_pct", "span_hours",
              "views", "subs", "likes", "sec", "published",
              "title", "channel", "keyword", "url", "thumbnail", "video_id"]


JPCHECK_FIELDS = ["verdict", "reason", "source_title", "topic_ko", "jp_query", "source_views",
                  "similar_count", "hit_count", "source_url", "region", "checked_at"]


def save(rows, name, fields=CSV_FIELDS):
    if not rows:
        print("결과 없음")
        return
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{name}_{datetime.now():%Y%m%d_%H%M}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
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
    r, similar, excluded = jp_check.check_keywords(kw, a.days, a.hit_views, a.refresh, a.type == "all")
    icon = {"선점 가능": "🟢", "차별화 필요": "🟡", "포화": "🔴"}[r["verdict"]]
    what = "쇼츠+롱폼" if a.type == "all" else "쇼츠"
    print(f"일본 검색어: {kw}  (최근 {a.days}일, 검색 결과 {what} {len(similar) + len(excluded)}개)\n")
    print(f"{icon} [{r['verdict']}] {r['reason']}")
    print("   ※ 제목에 검색어가 모두 들어간 영상만 '같은 소재'로 셌어요.\n")
    print(f"✅ 같은 소재로 본 영상 ({len(similar)}개)")
    for s in similar[:a.show]:
        print(f"  {s['views']:>10,}회  {s['kind']}  {s['title'][:40]}  {s['url']}")
    if not similar:
        print("  (없음)")
    print(f"\n✖ 제외한 영상 중 조회수 상위 (전체 {len(excluded)}개) — 같은 소재인데 빠졌다면 검색어를 바꿔 보세요")
    for s in excluded[:a.show]:
        print(f"  {s['views']:>10,}회  {s['kind']}  {s['title'][:40]}  {s['url']}")
    save(similar + excluded, "check")


def cmd_overseas(a):
    need = overseas.estimate_units(len(a.regions), a.keywords, not a.no_search, a.type)
    kind_name = {"all": "쇼츠+롱폼", "shorts": "쇼츠", "long": "롱폼"}[a.type]
    print(f"{', '.join(overseas.REGIONS[r][1] for r in a.regions)} · {kind_name} · 최근 {a.days}일"
          f" · 조회수 {a.min_views:,} 이상 (캐시가 없으면 약 {need:,}유닛 사용)")
    rows = overseas.collect(a.regions, a.keywords, a.days, a.min_views, a.sort, not a.no_search, a.refresh,
                            a.type)
    sort_name = {"views": "조회수", "vph": "시간당 조회수", "outlier": "구독자 대비 배수"}[a.sort]
    n_short = sum(r["kind"] == "쇼츠" for r in rows)
    print(f"\n해외에서 터진 영상 {len(rows)}개 (쇼츠 {n_short} · 롱폼 {len(rows) - n_short}, {sort_name} 순)\n")
    for i, r in enumerate(rows[:a.top], 1):
        x = f"x{r['outlier']}" if r["outlier"] else "x-"
        tag = f"{r['country']}·쇼츠" if r["kind"] == "쇼츠" else f"{r['country']}·롱폼 {overseas.fmt_duration(r['sec'])}"
        print(f"{i:>2}. [{tag}] {r['views']:>11,}회 · {r['views_per_hour']:>7,}/h · {x:<7} {r['title'][:50]}")
        print(f"    영상: {r['url']}")
        print(f"    번역: {r['translate']}")
    if rows:
        print("\n다음 단계: 마음에 드는 영상의 소재를 일본어 단어 2~3개로 바꿔서 일본에 있는지 확인하세요.")
        print('  python jp_shorts_finder.py check --keywords "일본어 검색어"')
    else:
        print("조건에 맞는 영상이 없어요. --min-views 를 낮추거나 --days 를 늘려 보세요.")
    save(rows, "overseas", ["country", "kind", "sec", "views", "views_per_hour", "outlier", "subs", "published",
                            "title", "channel", "url", "translate", "video_id"])


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


def cmd_jpcheck(a):
    claude_client()  # Claude 키가 없으면 YouTube 할당량을 쓰기 전에 멈춘다
    if a.title:
        source, region = "titles", "직접입력"
    else:
        source, region = ("keywords" if a.keywords else "popular"), a.region
    n = len(a.title) if a.title else a.limit
    need = jp_check.estimate_units(n, source)
    left = youtube.remaining()
    print(f"일본 검색 {n}회 예정 · 캐시가 없으면 약 {need:,}유닛 사용 (오늘 남은 할당량 {left:,})")
    if need > left:
        print(f"할당량이 부족할 수 있어요. --limit 를 {max(1, (left - 110) // jp_check.JP_SEARCH_UNITS)} 이하로 줄여 보세요.")
        return

    if source == "titles":
        cands = jp_check.title_candidates(a.title)
    elif source == "keywords":
        cands = jp_check.keyword_candidates(a.region, a.keywords, a.days, a.limit)
    else:
        cands = jp_check.popular_candidates(a.region, a.limit)
    if not cands:
        print(f"{a.region} 인기 차트에 쇼츠가 없어요. --keywords 로 검색해 보세요.")
        return
    print(f"원본 {len(cands)}개 → Claude로 일본어 검색어 만드는 중...\n")

    def progress(i, total, title):
        print(f"  [{i}/{total}] 일본 검색: {title[:40]}")

    rows = jp_check.check_candidates(cands, region, a.jp_days, a.hit_views, progress)
    icon = {"선점 가능": "🟢", "차별화 필요": "🟡", "포화": "🔴"}
    order = {"선점 가능": 0, "차별화 필요": 1, "포화": 2}
    rows.sort(key=lambda r: (order[r["verdict"]], -(r["source_views"] or 0)))
    print()
    for r in rows:
        views = f" ({r['source_views']:,}회)" if r["source_views"] is not None else ""
        print(f"{icon[r['verdict']]} [{r['verdict']}] {r['source_title'][:50]}{views}")
        print(f"    소재: {r['topic_ko']}  |  일본 검색어: {r['jp_query']}")
        print(f"    {r['reason']}")
        if r["source_url"]:
            print(f"    원본: {r['source_url']}")
        for s in r["similar"][:3]:
            print(f"      · {s['views']:>10,}회  {s['title'][:40]}  {s['url']}")
        print()
    save(rows, "jpcheck", JPCHECK_FIELDS)


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
    c = sub.add_parser("check", help="일본어 검색어로 포화도 확인 (무료, Claude 안 씀)")
    c.add_argument("--keywords", nargs="+", required=True)
    c.add_argument("--days", type=int, default=365, help="최근 며칠 안의 일본 영상과 비교")
    c.add_argument("--hit-views", type=int, default=100000, help="이 조회수 이상이면 '뜬 영상'으로 봄")
    c.add_argument("--show", type=int, default=5, help="목록을 몇 개씩 보여줄지")
    c.add_argument("--type", choices=["shorts", "all"], default="shorts",
                   help="일본에서 찾을 영상: shorts 쇼츠만 / all 쇼츠+롱폼")
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
    ov = sub.add_parser("overseas", help="한국·미국·영국에서 조회수 터진 쇼츠·롱폼 모으기 (무료)")
    ov.add_argument("--type", choices=["all", "shorts", "long"], default="all",
                    help="all 쇼츠+롱폼 / shorts 쇼츠만 / long 롱폼만")
    ov.add_argument("--regions", nargs="+", choices=list(overseas.REGIONS), default=list(overseas.REGIONS),
                    help="볼 나라 (KR 한국, US 미국, GB 영국)")
    ov.add_argument("--keywords", nargs="+", help="이 키워드로 검색 (없으면 #shorts 로 검색)")
    ov.add_argument("--days", type=int, default=7, help="최근 며칠 안에 올라온 영상")
    ov.add_argument("--min-views", type=int, default=500000, help="이 조회수보다 적으면 제외")
    ov.add_argument("--sort", choices=["views", "vph", "outlier"], default="views",
                    help="정렬: views 조회수 / vph 시간당 조회수 / outlier 구독자 대비 배수")
    ov.add_argument("--top", type=int, default=30, help="화면에 보여줄 개수")
    ov.add_argument("--no-search", action="store_true", help="검색 없이 인기 차트만 (나라당 약 15유닛)")
    ov.add_argument("--refresh", action="store_true", help="캐시 무시하고 새로 검색")
    ov.set_defaults(func=cmd_overseas)
    jc = sub.add_parser("jpcheck", help="한국·미국 인기 쇼츠의 일본판이 있는지 확인 (Claude 사용)")
    jc.add_argument("--region", choices=["KR", "US"], default="KR", help="어느 나라에서 뜬 쇼츠를 볼지")
    jc.add_argument("--keywords", nargs="+", help="그 나라에서 이 키워드로 검색 (없으면 인기 차트 사용)")
    jc.add_argument("--title", nargs="+", help="확인하고 싶은 제목을 직접 입력")
    jc.add_argument("--limit", type=int, default=5, help="확인할 원본 개수 (1개당 약 102유닛)")
    jc.add_argument("--days", type=int, default=7, help="--keywords 검색 시 최근 며칠")
    jc.add_argument("--jp-days", type=int, default=365, help="일본에서 최근 며칠 안의 영상과 비교할지")
    jc.add_argument("--hit-views", type=int, default=100000, help="이 조회수 이상이면 '뜬 영상'으로 봄")
    jc.set_defaults(func=cmd_jpcheck)
    a = p.parse_args()

    try:
        a.func(a)
    except (youtube.YouTubeError, ClaudeError) as e:
        print(f"\n[오류] {e}")
        print("\n" + youtube.quota_summary())
        sys.exit(1)
    print("\n" + youtube.quota_summary())


if __name__ == "__main__":
    main()
