"""1단계 테스트: python -m unittest tests.test_step1 -v"""
import os
import tempfile
import unittest
from unittest import mock

# 테스트는 임시 DB와 가짜 키를 사용한다 (실제 data/shorts.db는 건드리지 않음)
os.environ["SHORTS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["YT_API_KEY"] = "fake-key"

from shorts import youtube  # noqa: E402
from shorts.db import connect  # noqa: E402
from shorts.trending import collect  # noqa: E402
from tests.fake_youtube import error, fake_get  # noqa: E402


class Step1Test(unittest.TestCase):
    def setUp(self):
        with connect() as con:
            con.execute("DELETE FROM api_cache")
            con.execute("DELETE FROM quota_log")
        youtube.stats.update(api_calls=0, cache_hits=0, units=0)

    @mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
    def test_trend_sort_and_filter(self, _):
        rows = collect(["神回"], days=7, min_views=100_000)
        ids = [r["video_id"] for r in rows]
        self.assertNotIn("v4", ids)  # 10분짜리는 쇼츠가 아니라 제외
        self.assertNotIn("v5", ids)  # 최소 조회수 미달 제외
        self.assertEqual(ids[0], "v2")  # 구독자 5천에 50만회 = x100 → 1위
        self.assertEqual(rows[0]["outlier"], 100.0)
        # 게시 48시간, 50만회 → 시간당 약 10,416
        self.assertAlmostEqual(rows[0]["views_per_hour"], 10416, delta=5)

    @mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
    def test_cache_saves_quota(self, req):
        collect(["神回"])
        self.assertEqual(youtube.used_today(), 102)  # 검색 100 + 영상 1 + 채널 1
        calls = req.call_count
        collect(["神回"])  # 같은 검색 반복 → 전부 캐시
        self.assertEqual(req.call_count, calls)
        self.assertEqual(youtube.used_today(), 102)
        self.assertEqual(youtube.stats["cache_hits"], 3)
        collect(["神回"], refresh=True)  # 강제 새로고침은 다시 사용
        self.assertEqual(youtube.used_today(), 204)

    @mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
    def test_videos_saved_to_db(self, _):
        collect(["神回"], min_views=0)
        with connect() as con:
            n = con.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        self.assertEqual(n, 4)  # 쇼츠 4개 저장 (긴 영상 제외)

    def test_blocks_when_quota_low(self):
        with connect() as con:
            con.execute("INSERT INTO quota_log(day, endpoint, units, at) VALUES (?,?,?,0)",
                        (youtube.quota_day(), "search", 9950))
        with mock.patch("shorts.youtube.requests.get") as req:
            with self.assertRaises(youtube.QuotaError):
                collect(["神回"])
            req.assert_not_called()  # 남은 50유닛으로는 검색(100) 불가 → 호출 자체를 안 함

    def test_friendly_errors(self):
        with mock.patch("shorts.youtube.requests.get", return_value=error("quotaExceeded")):
            with self.assertRaisesRegex(youtube.QuotaError, "할당량"):
                youtube.get("search", q="x")
        with mock.patch("shorts.youtube.requests.get",
                        return_value=error("badRequest", 400, "API key not valid.")):
            with self.assertRaisesRegex(youtube.YouTubeError, "YT_API_KEY"):
                youtube.get("search", q="x")

    def test_missing_key(self):
        with mock.patch("shorts.youtube.yt_key", return_value=""):
            with self.assertRaisesRegex(youtube.YouTubeError, ".env"):
                youtube.get("search", q="x")


if __name__ == "__main__":
    unittest.main()
