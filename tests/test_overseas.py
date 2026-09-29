"""해외 터진 쇼츠 모으기 테스트: python -m unittest tests.test_overseas -v"""
import os
import tempfile
import unittest
from unittest import mock

os.environ["SHORTS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["YT_API_KEY"] = "fake-key"

from shorts import overseas, youtube  # noqa: E402
from shorts.db import connect  # noqa: E402
from tests import fake_youtube  # noqa: E402
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

    def test_only_fun_categories(self, _):
        with mock.patch.dict("tests.fake_youtube.CATEGORY", {"v2": "10", "v5": "1", "v1": "23"}):
            ids = [r["video_id"] for r in overseas.collect(["KR", "US"], min_views=0)]
            self.assertNotIn("v2", ids)   # 음악(뮤직비디오)
            self.assertNotIn("v5", ids)   # 영화·애니메이션(예고편)
            self.assertIn("v1", ids)      # 코미디
            ids = [r["video_id"] for r in overseas.collect(["KR", "US"], min_views=0, all_categories=True)]
            self.assertIn("v2", ids)

    def test_blocked_titles(self, _):
        videos = {**fake_youtube.VIDEOS, "v1": ("SQUID GAME 3 | Official Trailer", "c1", 10, "PT45S", 2_000_000),
                  "v2": ("Funny Indian wedding", "c2", 48, "PT30S", 500_000)}
        with mock.patch.dict("tests.fake_youtube.VIDEOS", videos):
            ids = [r["video_id"] for r in overseas.collect(["KR", "US"], min_views=0)]
        self.assertNotIn("v1", ids)
        self.assertNotIn("v2", ids)
        self.assertIsNone(overseas.BLOCKED_TITLE.search("Indiana Jones prank"))
        self.assertIsNone(overseas.BLOCKED_TITLE.search("The Office funniest moments"))

    def test_search_plan(self, _):
        plan = overseas.search_plan(["KR", "US", "GB"])
        self.assertEqual(len(plan), 8)                               # 한국 4 + 영어 4 (미국·영국 공통)
        self.assertEqual({r for _, _, r in plan}, {"KR", "US"})
        self.assertEqual(overseas.search_plan(["GB"], ["prank"]), [("prank", "en", "GB")])
        self.assertEqual(overseas.search_plan(["KR"], use_search=False), [])

    def test_short_horizontal_video_is_not_shorts(self, _):
        # 3분 이하라도 가로 영상(뮤직비디오 등)이면 쇼츠가 아님
        with mock.patch.dict("tests.fake_youtube.VIDEOS", {"v2": ("Funny clip", "c2", 48, "PT2M50S", 500_000)}), \
                mock.patch("tests.fake_youtube.HORIZONTAL", {"v2", "v4"}):
            rows = {r["video_id"]: r for r in overseas.collect(["KR", "US"], min_views=0)}
        self.assertEqual(rows["v2"]["kind"], "롱폼")
        self.assertEqual(rows["v2"]["url"], "https://youtube.com/watch?v=v2")
        self.assertEqual(rows["v1"]["kind"], "쇼츠")

    def test_filters_indian_videos(self, _):
        extra = {"v6": ("मजेदार वीडियो", "c4", 5, "PT30S", 3_000_000),   # 힌디어 제목
                 "v7": ("Funny prank video", "c4", 5, "PT30S", 3_000_000),  # 인도 영어
                 "v8": ("Epic fail compilation", "c4", 5, "PT30S", 3_000_000),  # 검색에서만, 정보 없음
                 "v9": ("Try not to laugh", "c4", 5, "PT30S", 3_000_000)}  # 검색에서만, 미국 영어
        videos = {**fake_youtube.VIDEOS, **extra}
        with mock.patch.dict("tests.fake_youtube.VIDEOS", videos), \
                mock.patch.dict("tests.fake_youtube.LANG", {"v7": "en-IN", "v9": "en"}), \
                mock.patch("tests.fake_youtube.CHART", {"v1", "v2", "v3", "v4", "v5"}):
            rows = {r["video_id"]: r["country"] for r in overseas.collect(["US"], min_views=0)}
        self.assertNotIn("v6", rows)          # 힌디어 제목
        self.assertNotIn("v7", rows)          # 언어 en-IN
        self.assertNotIn("v8", rows)          # 검색 결과 + 국가·언어 정보 없음
        self.assertEqual(rows["v9"], "US")    # 검색 결과지만 언어가 영어라 남김
        self.assertEqual(rows["v5"], "US")    # 국가 정보 없지만 미국 인기 차트에 있음

    def test_estimate(self, _):
        self.assertEqual(overseas.estimate_units(["KR", "US", "GB"]), 3 * 15 + 8 * 102)
        self.assertEqual(overseas.estimate_units(["KR"], use_search=False), 15)
        self.assertEqual(overseas.estimate_units(["US", "GB"], ["a", "b"]), 30 + 204)

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
