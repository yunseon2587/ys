"""3단계 테스트: python -m unittest tests.test_step3 -v"""
import os
import tempfile
import unittest
from unittest import mock

os.environ["SHORTS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["YT_API_KEY"] = "fake-key"

from shorts import claude_ai, jp_check, youtube  # noqa: E402
from shorts.db import connect  # noqa: E402
from tests import fake_claude  # noqa: E402
from tests.fake_youtube import fake_get  # noqa: E402


def row(views):
    return {"views": views}


@mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
@mock.patch("shorts.claude_ai.client", return_value=fake_claude.FakeClient())
class Step3Test(unittest.TestCase):
    def setUp(self):
        with connect() as con:
            for t in ("api_cache", "quota_log", "videos", "snapshots", "llm_cache", "jp_checks"):
                con.execute(f"DELETE FROM {t}")
        fake_claude.calls.clear()

    def test_popular_candidates_only_shorts_cheap(self, *_):
        used = youtube.used_today()
        cands = jp_check.popular_candidates("KR", limit=10)
        self.assertNotIn("v4", [c["video_id"] for c in cands])   # 10분 영상 제외
        self.assertEqual(len(cands), 4)
        self.assertEqual(youtube.used_today() - used, 3)          # 차트 1 + 영상 1 + 채널 1

    def test_full_flow_and_saved(self, *_):
        cands = jp_check.title_candidates(["케첩 거꾸로 짜기", "고양이 역주행"])
        rows = jp_check.check_candidates(cands, "직접입력", hit_views=100_000)
        self.assertEqual([r["jp_query"] for r in rows], ["検索0", "検索1"])
        # 가짜 일본 검색 결과 중 같은 소재 = 猫(50만), 神回(200만) → 10만 이상 2개 → 차별화 필요
        self.assertEqual(rows[0]["similar_count"], 2)
        self.assertEqual(rows[0]["verdict"], "차별화 필요")
        self.assertEqual(rows[0]["similar"][0]["views"], 2_000_000)  # 조회수 순 정렬
        with connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM jp_checks").fetchone()[0], 2)
        # 번역은 한 번에 1회 + 비슷한 영상 고르기 2회
        self.assertEqual(len(fake_claude.calls), 3)
        kw = fake_claude.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")

    def test_claude_answers_are_cached(self, *_):
        cands = jp_check.title_candidates(["케첩 거꾸로 짜기"])
        jp_check.check_candidates(cands, "직접입력")
        n = len(fake_claude.calls)
        jp_check.check_candidates(cands, "직접입력")
        self.assertEqual(len(fake_claude.calls), n)  # 같은 질문은 다시 안 물어봄 (비용 0)

    def test_judge_rules(self, *_):
        self.assertEqual(jp_check.judge([], 100_000)[0], "선점 가능")
        self.assertEqual(jp_check.judge([row(5_000), row(90_000)], 100_000)[0], "선점 가능")
        self.assertEqual(jp_check.judge([row(150_000)], 100_000)[0], "차별화 필요")
        self.assertEqual(jp_check.judge([row(2e5), row(3e5)], 100_000)[0], "차별화 필요")
        self.assertEqual(jp_check.judge([row(2e5), row(3e5), row(4e5)], 100_000)[0], "포화")

    def test_refusal(self, client, _):
        client.return_value = fake_claude.FakeClient(lambda **kw: fake_claude.reply({}, "refusal"))
        with self.assertRaisesRegex(claude_ai.ClaudeError, "거절"):
            claude_ai.ask_json("x", "unique prompt", {})


class MissingKeyTest(unittest.TestCase):
    def test_missing_anthropic_key(self):
        with mock.patch.object(claude_ai, "_client", None), \
                mock.patch("shorts.claude_ai.anthropic_key", return_value=""):
            with self.assertRaisesRegex(claude_ai.ClaudeError, "ANTHROPIC_API_KEY"):
                claude_ai.ask_json("x", "never asked before", {})


if __name__ == "__main__":
    unittest.main()


@mock.patch("shorts.youtube.requests.get", side_effect=fake_get)
class FreeCheckTest(unittest.TestCase):
    def test_keyword_match_all_words_and_width(self, _):
        rows = [{"title": "【神回】ドッキリ大成功"}, {"title": "ドッキリ集"}, {"title": "ＳＨＯＲＴＳ 神回 ドッキリ"}]
        similar, excluded = jp_check.keyword_match("神回 ドッキリ", rows)
        self.assertEqual([r["title"] for r in similar], ["【神回】ドッキリ大成功", "ＳＨＯＲＴＳ 神回 ドッキリ"])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(len(jp_check.keyword_match("shorts", rows)[0]), 1)  # 전각 ＳＨＯＲＴＳ도 찾음

    def test_check_keywords_no_claude(self, _):
        with mock.patch("shorts.claude_ai.client") as claude:
            r, similar, excluded = jp_check.check_keywords("猫")
            claude.assert_not_called()                     # Claude를 전혀 안 씀
        self.assertEqual([s["video_id"] for s in similar], ["v2"])  # '猫'가 제목에 있는 영상만
        self.assertEqual(len(excluded), 3)
        self.assertEqual(r["verdict"], "차별화 필요")        # 50만회 1개
        self.assertEqual(jp_check.check_keywords("存在しない")[0]["verdict"], "선점 가능")

    def test_check_keywords_with_long_form(self, _):
        _, similar, excluded = jp_check.check_keywords("쇼츠", include_long=True)
        self.assertEqual([s["video_id"] for s in similar], ["v4"])  # 롱폼도 찾음
        self.assertEqual(similar[0]["kind"], "롱폼")
        _, similar, _ = jp_check.check_keywords("쇼츠")               # 기본(쇼츠만)이면 안 나옴
        self.assertEqual(similar, [])
