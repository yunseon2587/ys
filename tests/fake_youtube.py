"""실제 YouTube 응답 형식을 흉내 낸 가짜 API (키 없이 테스트용)."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

NOW = datetime.now(timezone.utc)

# video_id: (title, channel_id, 게시 몇 시간 전, 길이, 조회수)
VIDEOS = {
    "v1": ("【神回】ドッキリ大成功", "c1", 10, "PT45S", 2_000_000),
    "v2": ("猫が逆さまに歩く", "c2", 48, "PT30S", 500_000),
    "v3": ("バラエティ切り抜き", "c3", 100, "PT1M10S", 150_000),
    "v4": ("긴 영상(쇼츠 아님)", "c1", 5, "PT10M", 9_000_000),
    "v5": ("調味料チャレンジ", "c4", 3, "PT20S", 50_000),
}
HORIZONTAL = {"v4"}   # 가로 영상 (나머지는 세로)
CATEGORY = {}         # video_id → categoryId (없으면 "24" 엔터테인먼트)
LANG = {}             # video_id → defaultAudioLanguage (없으면 정보 없음)
CHART = None          # 인기 차트에 나오는 영상 (None이면 전부)
SUBS = {"c1": 1_000_000, "c2": 5_000, "c3": 300_000, "c4": 0}
COUNTRY = {"c1": "KR", "c2": "US", "c3": "JP", "c4": ""}


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.ok, self.text = data, status, status < 400, str(data)

    def json(self):
        return self._d


def error(reason, status=403, message=""):
    return Resp({"error": {"message": message, "errors": [{"reason": reason}]}}, status)


def fake_get(url, params=None, timeout=None):
    ep = urlparse(url).path.rsplit("/", 1)[-1]
    if ep == "search":
        return Resp({"items": [{"id": {"videoId": v}} for v in VIDEOS]})
    if ep == "videos" and "chart" in params:  # 인기 차트
        return Resp({"items": [{"id": v} for v in VIDEOS if CHART is None or v in CHART]})
    if ep == "videos":
        items = []
        for vid in params["id"].split(","):
            if vid not in VIDEOS:
                continue  # 실제 API도 없는 영상 ID는 결과에서 빼고 돌려준다
            title, ch, hrs, dur, views = VIDEOS[vid]
            items.append({
                "id": vid,
                "snippet": {"title": title, "channelId": ch, "channelTitle": f"チャンネル{ch}",
                            "categoryId": CATEGORY.get(vid, "24"),
                            **({"defaultAudioLanguage": LANG[vid]} if vid in LANG else {}),
                            "publishedAt": (NOW - timedelta(hours=hrs)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}}},
                "statistics": {"viewCount": str(views), "likeCount": str(views // 50)},
                "contentDetails": {"duration": dur},
                "player": {"embedWidth": "1138", "embedHeight": "640"} if vid in HORIZONTAL
                else {"embedWidth": "360", "embedHeight": "640"},
            })
        return Resp({"items": items})
    if ep == "channels":
        return Resp({"items": [{"id": c, "snippet": {"country": COUNTRY[c]} if COUNTRY[c] else {},
                                "statistics": {"subscriberCount": str(SUBS[c])}}
                               for c in params["id"].split(",")]})
    raise AssertionError(ep)
