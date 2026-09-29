"""2단계 테스트: python -m unittest tests.test_step2 -v"""
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ["SHORTS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["YT_API_KEY"] = "fake-key"

from shorts import rising, schedule, youtube  # noqa: E402
from shorts.db import connect  # noqa: E402
from shorts.trending import collect  # noqa: E402
from tests import fake_youtube  # noqa: E402
from tests.fake_youtube import fake_get  # noqa: E402

HOUR = 3600


class Step2Test(unittest.TestCase):
    def setUp(self):
        with connect() as con:
            for t in ("api_cache", "quota_log", "videos", "snapshots"):
                con.execute(f"DELETE FROM {t}")
        self.orig = dict(fake_youtube.VIDEOS)

    def tearDown(self):
        fake_youtube.VIDEOS.clear()
        fake_youtube.VIDEOS.update(self.orig)

    def shift_snapshots(self, hours):
        """기록 시각을 과거로 밀어서 시간이 흐른 것처럼 만든다."""
        with connect() as con:
            con.execute("UPDATE snapshots SET taken_at = taken_at - ?", (hours * HOUR,))

    def bump(self, vid, views):
        t = list(fake_youtube.VIDEOS[vid])
        t[4] = views
        fake_youtube.VIDEOS[vid] = tuple(t)

    @mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
    def test_trend_records_baseline_once(self, _):
        collect(["神回"], min_views=0)
        collect(["神回"], min_views=0, refresh=True)  # 1시간 안에 다시 해도 중복 기록 안 함
        with connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 4)

    @mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
    def test_snapshot_and_rising(self, _):
        collect(["神回"], min_views=0)             # 기준 기록 (v1=200만, v2=50만, v3=15만, v5=5만)
        self.shift_snapshots(4)                    # 4시간 지남
        self.bump("v2", 900_000)                   # +40만
        self.bump("v5", 250_000)                   # +20만
        self.bump("v1", 2_100_000)                 # +10만
        used = youtube.used_today()
        saved, total = rising.take_snapshot()
        self.assertEqual((saved, total), (4, 4))
        self.assertEqual(youtube.used_today() - used, 1)  # 4개 → 1유닛

        rows = rising.find_rising(hours=24)
        self.assertEqual([r["video_id"] for r in rows[:3]], ["v2", "v5", "v1"])
        top = rows[0]
        self.assertEqual(top["gain"], 400_000)
        self.assertAlmostEqual(top["span_hours"], 4, delta=0.1)
        self.assertAlmostEqual(top["gain_per_hour"], 100_000, delta=100)
        self.assertEqual(top["growth_pct"], 80.0)
        self.assertEqual(rows[-1]["gain"], 0)      # 안 오른 v3는 맨 뒤
        self.assertEqual(len(rising.find_rising(hours=24, min_gain=150_000)), 2)

    def test_window_uses_snapshot_before_cutoff(self):
        now = time.time()
        with connect() as con:
            con.execute("INSERT INTO videos(video_id, title, published_at) VALUES ('a','A','2026-01-01T00:00:00Z')")
            for h, views in [(48, 100), (30, 1_000), (20, 5_000), (0, 10_000)]:
                con.execute("INSERT INTO snapshots VALUES ('a', ?, ?, 0)", (now - h * HOUR, views))
        r = rising.find_rising(hours=24)[0]
        # 24시간 전보다 앞선 기록 중 가장 최근 = 30시간 전(1,000) → +9,000 / 30h
        self.assertEqual(r["gain"], 9_000)
        self.assertEqual(r["span_hours"], 30.0)
        self.assertEqual(rising.find_rising(hours=6)[0]["gain"], 5_000)  # 20시간 전 기준

    def test_skips_too_short_and_stale(self):
        now = time.time()
        with connect() as con:
            con.execute("INSERT INTO videos(video_id, title) VALUES ('new','N'), ('old','O')")
            con.executemany("INSERT INTO snapshots VALUES (?,?,?,0)", [
                ("new", now - 600, 100), ("new", now, 200),              # 10분 간격 → 계산 안 함
                ("old", now - 80 * HOUR, 1), ("old", now - 50 * HOUR, 9),  # 최근 기록 없음
            ])
        self.assertEqual(rising.find_rising(hours=24), [])

    def test_snapshot_only_tracks_recent_videos(self):
        with connect() as con:
            con.execute("INSERT INTO videos(video_id, published_at) VALUES ('old','2020-01-01T00:00:00Z')")
        with mock.patch("shorts.youtube.requests.get") as req:
            self.assertEqual(rising.take_snapshot(max_age_days=14), (0, 0))
            req.assert_not_called()

    def test_windows_schedule_command(self):
        with mock.patch("shorts.schedule.subprocess.run") as run:
            schedule.windows_create(3)
        args = run.call_args[0][0]
        self.assertEqual(args[:5], ["schtasks", "/Create", "/F", "/TN", "JPShortsSnapshot"])
        self.assertIn("/MO", args)
        self.assertEqual(args[args.index("/MO") + 1], "3")
        bat = schedule.BAT_PATH.read_text(encoding="utf-8")
        self.assertIn("jp_shorts_finder.py snapshot", bat)
        schedule.BAT_PATH.unlink()


if __name__ == "__main__":
    unittest.main()
