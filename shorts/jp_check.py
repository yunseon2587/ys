"""3단계: 한국·미국에서 뜬 쇼츠가 일본에도 있는지 확인하고 '선점 가능 / 차별화 필요 / 포화'로 판정한다."""
import json
import unicodedata
from datetime import datetime, timezone

from . import youtube
from .claude_ai import ask_json
from .config import SEARCH_TTL
from .db import connect
from .trending import enrich, search_ids

LANG = {"KR": "ko", "US": "en", "JP": "ja"}
JP_SEARCH_UNITS = 102  # 일본 검색 1회(100) + 영상·채널 정보(2)


# ---------- 1) 원본 후보 모으기 ----------

def popular_candidates(region, limit):
    """그 나라 '인기 급상승' 차트에서 쇼츠만 골라낸다. 50개당 1유닛이라 저렴하다."""
    ids, token = [], None
    for _ in range(4):  # 최대 200개 훑기
        p = dict(part="id", chart="mostPopular", regionCode=region, maxResults=50)
        if token:
            p["pageToken"] = token
        data = youtube.get("videos", ttl=SEARCH_TTL, **p)
        ids += [it["id"] for it in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token:
            break
    rows = enrich(ids)  # 3분 넘는 영상은 여기서 빠진다
    rows.sort(key=lambda r: r["views_per_hour"], reverse=True)
    return rows[:limit]


def keyword_candidates(region, keywords, days, limit):
    """그 나라에서 키워드로 검색 (키워드당 100유닛)."""
    ids = []
    for kw in keywords:
        ids += search_ids(kw, days, 1, region=region, lang=LANG.get(region, "en"))
    rows = enrich(ids)
    rows.sort(key=lambda r: (r["outlier"] or 0, r["views_per_hour"]), reverse=True)
    return rows[:limit]


def title_candidates(titles):
    return [{"video_id": None, "title": t, "views": None, "url": "", "thumbnail": ""} for t in titles]


# ---------- 2) Claude: 일본어 검색어로 바꾸기 ----------

TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "topic_ko": {"type": "string"},
                    "jp_query": {"type": "string"},
                },
                "required": ["index", "topic_ko", "jp_query"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def to_jp_queries(titles):
    """제목 목록 → [(한국어 요약, 일본어 검색어)]. 한 번의 요청으로 모두 처리한다."""
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    prompt = f"""아래는 한국이나 미국에서 인기를 끈 유튜브 쇼츠 제목들이다.
일본 유튜브에 같은 소재의 쇼츠가 이미 있는지 검색하려고 한다.

각 제목마다:
- topic_ko: 영상이 어떤 소재인지 한국어로 15자 안팎 요약 (예: "케첩을 거꾸로 짜는 실험")
- jp_query: 일본 유튜브 검색창에 넣을 일본어 검색어. 일본 사람이 실제로 쓸 법한 단어 2~4개를 띄어쓰기로 구분.
  직역하지 말고 소재의 핵심만 담는다. 해시태그, 이모지, 채널명, 인물 이름(일본에서도 유명한 경우 제외)은 빼고,
  일본에서 통하는 표현으로 바꾼다 (예: 먹방 → 大食い / モッパン, 몰래카메라 → ドッキリ).

index는 제목 앞의 번호를 그대로 쓴다.

제목:
{numbered}"""
    data = ask_json("translate", prompt, TRANSLATE_SCHEMA)
    by_idx = {it["index"]: it for it in data["items"]}
    out = []
    for i, t in enumerate(titles):
        it = by_idx.get(i)
        out.append((it["topic_ko"], it["jp_query"]) if it else ("", t))
    return out


# ---------- 3) 일본 검색 + Claude로 '같은 소재'만 골라내기 ----------

SIMILAR_SCHEMA = {
    "type": "object",
    "properties": {"similar": {"type": "array", "items": {"type": "integer"}}},
    "required": ["similar"],
    "additionalProperties": False,
}


def pick_similar(source_title, topic_ko, jp_rows):
    """유튜브 검색은 관련 없는 영상도 섞여 나오므로, 정말 같은 소재인 것만 Claude가 고른다."""
    if not jp_rows:
        return []
    numbered = "\n".join(f"{i}. {r['title']}" for i, r in enumerate(jp_rows))
    prompt = f"""원본 쇼츠: "{source_title}"
소재: {topic_ko}

아래는 일본 유튜브에서 검색된 쇼츠 제목들이다.
원본과 '같은 소재·같은 아이디어'인 영상의 번호만 similar에 넣어라.
단어 하나만 겹치거나 분야만 같은 영상은 제외한다. 없으면 빈 배열.

{numbered}"""
    idx = ask_json("similar", prompt, SIMILAR_SCHEMA)["similar"]
    return [jp_rows[i] for i in sorted(set(idx)) if 0 <= i < len(jp_rows)]


def judge(similar, hit_views):
    """판정 규칙: 같은 소재 중 조회수 hit_views 이상인 '성공작'이 몇 개인지로 판단한다."""
    hits = [r for r in similar if r["views"] >= hit_views]
    base = f"같은 소재 일본 쇼츠 {len(similar)}개, 그중 {hit_views:,}회 이상 {len(hits)}개"
    if not hits:
        extra = " → 아직 일본에서 뜬 영상이 없음" if similar else " → 일본에 거의 없음"
        return "선점 가능", base + extra, len(hits)
    if len(hits) <= 2:
        return "차별화 필요", base + " → 몇 개 떴으니 각도·편집을 다르게", len(hits)
    return "포화", base + " → 이미 여러 개가 성공함", len(hits)


# ---------- Claude 없이 (무료): 제목에 검색어가 모두 들어간 영상만 같은 소재로 본다 ----------

def _norm(text):
    # 전각/반각, 대소문자 차이를 없앤다 (ＡＢＣ → abc)
    return unicodedata.normalize("NFKC", text or "").lower()


def keyword_match(query, rows):
    """(같은 소재로 본 영상, 제외한 영상)을 돌려준다."""
    words = [_norm(w) for w in query.split() if w.strip()]
    similar, excluded = [], []
    for r in rows:
        title = _norm(r["title"])
        (similar if all(w in title for w in words) else excluded).append(r)
    return similar, excluded


def check_keywords(query, jp_days=365, hit_views=100_000, refresh=False):
    """일본어 검색어를 직접 넣어 확인 (Claude 사용 안 함, 약 102유닛)."""
    rows = enrich(search_ids(query, jp_days, 1, refresh, region="JP", lang="ja"), refresh)
    similar, excluded = keyword_match(query, rows)
    similar.sort(key=lambda r: r["views"], reverse=True)
    excluded.sort(key=lambda r: r["views"], reverse=True)
    verdict, reason, hit_count = judge(similar, hit_views)
    r = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "region": "직접입력",
        "source_video_id": None, "source_title": query, "source_views": None, "source_url": "",
        "thumbnail": "", "topic_ko": "", "jp_query": query,
        "verdict": verdict, "reason": reason, "similar_count": len(similar), "hit_count": hit_count,
        "similar": [{k: s[k] for k in ("title", "channel", "views", "url", "thumbnail")} for s in similar[:10]],
    }
    save_check(r)
    return r, similar, excluded


# ---------- 전체 흐름 ----------

def estimate_units(n_candidates, source):
    src = {"popular": 6, "keywords": 102, "titles": 0}[source]
    return src + n_candidates * JP_SEARCH_UNITS


def check_candidates(candidates, region, jp_days=365, hit_views=100_000, on_progress=None):
    if not candidates:
        return []
    queries = to_jp_queries([c["title"] for c in candidates])
    results = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for n, (c, (topic_ko, jp_query)) in enumerate(zip(candidates, queries), 1):
        if on_progress:
            on_progress(n, len(candidates), c["title"])
        jp_rows = enrich(search_ids(jp_query, jp_days, 1, region="JP", lang="ja"))
        similar = pick_similar(c["title"], topic_ko, jp_rows)
        similar.sort(key=lambda r: r["views"], reverse=True)
        verdict, reason, hit_count = judge(similar, hit_views)
        r = {
            "checked_at": now, "region": region,
            "source_video_id": c["video_id"], "source_title": c["title"], "source_views": c["views"],
            "source_url": c["url"], "thumbnail": c["thumbnail"],
            "topic_ko": topic_ko, "jp_query": jp_query,
            "verdict": verdict, "reason": reason,
            "similar_count": len(similar), "hit_count": hit_count,
            "similar": [{k: s[k] for k in ("title", "channel", "views", "url", "thumbnail")} for s in similar[:10]],
        }
        save_check(r)
        results.append(r)
    return results


def save_check(r):
    with connect() as con:
        con.execute("""
            INSERT INTO jp_checks(checked_at, region, source_video_id, source_title, source_views, source_url,
                                  thumbnail, topic_ko, jp_query, verdict, reason, similar_count, hit_count,
                                  similar_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (r["checked_at"], r["region"], r["source_video_id"], r["source_title"], r["source_views"],
              r["source_url"], r["thumbnail"], r["topic_ko"], r["jp_query"], r["verdict"], r["reason"],
              r["similar_count"], r["hit_count"], json.dumps(r["similar"], ensure_ascii=False)))
