"""가짜 Claude (키 없이 테스트용). 실제 응답 모양(content 블록, stop_reason)을 흉내 낸다."""
import json
import re
from types import SimpleNamespace

calls = []


def reply(data, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="thinking", thinking=""),
                                    SimpleNamespace(type="text", text=json.dumps(data, ensure_ascii=False))])


def fake_create(**kw):
    calls.append(kw)
    prompt = kw["messages"][0]["content"]
    if "jp_query" in prompt:  # 번역 요청: 번호마다 검색어를 만들어 준다
        n = len(re.findall(r"^\d+\. ", prompt.split("제목:")[-1], re.M))
        return reply({"items": [{"index": i, "topic_ko": f"소재{i}", "jp_query": f"検索{i}"} for i in range(n)]})
    # 비슷한 영상 고르기: 제목에 '猫' 또는 '神回'가 있으면 같은 소재로 본다
    lines = re.findall(r"^(\d+)\. (.*)$", prompt, re.M)
    return reply({"similar": [int(i) for i, t in lines if "猫" in t or "神回" in t]})


class FakeClient:
    def __init__(self, create=fake_create):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))
