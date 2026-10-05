"""장르 비교 테스트: python -m unittest tests.test_genre -v"""
import os
import tempfile
import unittest
from unittest import mock

os.environ["SHORTS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["YT_API_KEY"] = "fake-key"

from shorts import genre  # noqa: E402
from tests.fake_youtube import fake_get  # noqa: E402

# 가짜 검색 결과 중 쇼츠: v1 200만(c1, x2) · v2 50만(c2, x100) · v3 15만(c3, x0.5) · v5 5만(c4, 구독자 비공개)


@mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
class GenreTest(unittest.TestCase):
    def test_summary_numbers(self, _):
        g = genre.compare(["idol"])[0]
        self.assertEqual(g["name"], "아이돌 자컨")
        self.assertEqual(g["count"], 4)                       # 10분 롱폼(v4)은 빠짐
        self.assertEqual(g["median_views"], 325_000)          # (50만 + 15만) / 2
        self.assertEqual((g["over_100k"], g["over_1m"]), (3, 1))
        self.assertEqual(g["median_outlier"], 2.0)            # [2, 100, 0.5] 의 중간 (비공개 제외)
        self.assertEqual(g["videos_for_goal"], 31)            # 1000만 / 32.5만 → 올림
        self.assertEqual(g["channels"][0]["channel_id"], "c1")
        self.assertEqual(g["videos"][0]["video_id"], "v1")

    def test_all_genres_and_custom(self, _):
        self.assertEqual([g["name"] for g in genre.compare()],
                         ["아이돌 자컨", "한국 예능", "미국 버라이어티", "일본판 국뽕(海外の反応)"])
        custom = genre.compare(keywords=["猫"])
        self.assertEqual(custom[0]["name"], "직접 입력")
        self.assertEqual(custom[0]["queries"], ["猫"])

    def test_empty_and_estimate(self, _):
        g = genre.summarize("빈 장르", ["x"], [])
        self.assertEqual((g["count"], g["median_views"], g["videos_for_goal"]), (0, 0, None))
        self.assertEqual(genre.estimate_units(list(genre.GENRES)), 12 * 102)
        self.assertEqual(genre.estimate_units([], ["a", "b"]), 204)


if __name__ == "__main__":
    unittest.main()
