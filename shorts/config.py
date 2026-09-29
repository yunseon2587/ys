"""설정값: .env 파일에서 API 키 등을 읽어온다."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.environ.get("SHORTS_DB") or ROOT / "data" / "shorts.db")
OUTPUT_DIR = ROOT / "output"
DAILY_QUOTA = int(os.environ.get("YT_DAILY_QUOTA") or 10000)

# 캐시 유지 시간(초): 같은 검색은 12시간, 조회수·구독자 정보는 1시간 동안 재사용
SEARCH_TTL = 12 * 3600
STATS_TTL = 3600


def yt_key():
    return (os.environ.get("YT_API_KEY") or "").strip()
