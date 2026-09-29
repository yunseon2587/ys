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
SUBS = {"c1": 1_000_000, "c2": 5_000, "c3": 300_000, "c4": 0}


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
    if ep == "videos":
        items = []
        for vid in params["id"].split(","):
            title, ch, hrs, dur, views = VIDEOS[vid]
            items.append({
                "id": vid,
                "snippet": {"title": title, "channelId": ch, "channelTitle": f"チャンネル{ch}",
                            "publishedAt": (NOW - timedelta(hours=hrs)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}}},
                "statistics": {"viewCount": str(views), "likeCount": str(views // 50)},
                "contentDetails": {"duration": dur},
            })
        return Resp({"items": items})
    if ep == "channels":
        return Resp({"items": [{"id": c, "statistics": {"subscriberCount": str(SUBS[c])}}
                               for c in params["id"].split(",")]})
    raise AssertionError(ep)
