"""해외 터진 쇼츠 모으기 테스트: python -m unittest tests.test_overseas -v"""
import os
import tempfile
import unittest
from unittest import mock

os.environ["SHORTS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["YT_API_KEY"] = "fake-key"

from shorts import overseas, youtube  # noqa: E402
from shorts.db import connect  # noqa: E402
from tests.fake_youtube import fake_get  # noqa: E402

# 가짜 데이터의 채널 국가: c1=KR(v1, v4는 긴 영상), c2=US(v2), c3=JP(v3), c4=국가 없음(v5)


@mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
class OverseasTest(unittest.TestCase):
    def setUp(self):
        with connect() as con:
            for t in ("api_cache", "quota_log", "overseas_videos"):
                con.execute(f"DELETE FROM {t}")

    def test_country_filter_and_sort(self, _):
        rows = overseas.collect(["KR", "US", "GB"], min_views=0, kind="shorts")
        by_id = {r["video_id"]: r["country"] for r in rows}
        self.assertNotIn("v3", by_id)          # 일본 채널 제외
        self.assertNotIn("v4", by_id)          # 쇼츠만 볼 때 10분 영상 제외
        self.assertEqual(by_id["v1"], "KR")
        self.assertEqual(by_id["v2"], "US")    # 채널 국가 US
        self.assertEqual(by_id["v5"], "KR")    # 국가 없음 → 처음 찾은 지역(KR)
        self.assertEqual([r["video_id"] for r in rows], ["v1", "v2", "v5"])  # 조회수 순

    def test_long_form(self, _):
        rows = overseas.collect(["KR", "US"], min_views=0)  # 기본: 쇼츠+롱폼
        self.assertEqual(rows[0]["video_id"], "v4")          # 900만회 롱폼이 1위
        self.assertEqual(rows[0]["kind"], "롱폼")
        self.assertEqual(rows[0]["url"], "https://youtube.com/watch?v=v4")
        self.assertEqual(overseas.fmt_duration(rows[0]["sec"]), "10:00")
        only_long = overseas.collect(["KR", "US"], min_views=0, kind="long")
        self.assertEqual([r["video_id"] for r in only_long], ["v4"])

    def test_music_excluded_by_default(self, _):
        with mock.patch.dict("tests.fake_youtube.CATEGORY", {"v2": "10"}):
            ids = [r["video_id"] for r in overseas.collect(["KR", "US"], min_views=0)]
            self.assertNotIn("v2", ids)
            ids = [r["video_id"] for r in overseas.collect(["KR", "US"], min_views=0, include_music=True)]
            self.assertIn("v2", ids)

    def test_short_horizontal_video_is_not_shorts(self, _):
        # 3분 이하라도 가로 영상(뮤직비디오 등)이면 쇼츠가 아님
        with mock.patch.dict("tests.fake_youtube.VIDEOS", {"v2": ("MV", "c2", 48, "PT2M50S", 500_000)}), \
                mock.patch("tests.fake_youtube.HORIZONTAL", {"v2", "v4"}):
            rows = {r["video_id"]: r for r in overseas.collect(["KR", "US"], min_views=0)}
        self.assertEqual(rows["v2"]["kind"], "롱폼")
        self.assertEqual(rows["v2"]["url"], "https://youtube.com/watch?v=v2")
        self.assertEqual(rows["v1"]["kind"], "쇼츠")

    def test_estimate(self, _):
        self.assertEqual(overseas.estimate_units(3), 3 * 117)                      # 차트 + #shorts 검색
        self.assertEqual(overseas.estimate_units(3, kind="long"), 3 * 15)          # 롱폼은 차트만
        self.assertEqual(overseas.estimate_units(1, ["a", "b"], kind="long"), 15 + 204)

    def test_only_selected_regions_and_min_views(self, _):
        rows = overseas.collect(["US"], min_views=100_000)
        self.assertEqual([r["video_id"] for r in rows], ["v2"])  # KR 채널(v1) 제외, v5는 US로 분류되지만 5만회라 제외

    def test_quota_and_chart_only(self, _):
        overseas.collect(["KR"], use_search=False)
        self.assertEqual(youtube.used_today(), 3)  # 차트 1 + 영상 1 + 채널 1, 검색 안 함

    def test_translate_link_and_saved(self, _):
        rows = overseas.collect(["KR", "US"], min_views=0, sort="outlier")
        self.assertEqual(rows[0]["video_id"], "v2")  # 구독자 5천에 50만회 = x100
        self.assertIn("tl=ja", rows[0]["translate"])
        self.assertNotIn("%23", overseas.translate_link("고양이 #shorts #funny"))  # 해시태그 제거
        with connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM overseas_videos").fetchone()[0], 4)  # 쇼츠 3 + 롱폼 1


if __name__ == "__main__":
    unittest.main()
