"""영상 지표 계산: 길이 변환, outlier 배수, 시간당 조회수."""
import re
from datetime import datetime, timezone

MAX_SHORT_SEC = 180  # 현재 쇼츠 최대 길이 기준


def iso_to_sec(d):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def outlier(views, subs):
    """구독자 대비 조회수 배수. 구독자 수 비공개면 None."""
    return round(views / subs, 1) if subs else None


def views_per_hour(views, published_at, now=None):
    now = now or datetime.now(timezone.utc)
    pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    hours = max((now - pub).total_seconds() / 3600, 1)
    return int(views / hours)
