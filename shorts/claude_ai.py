"""Claude API 호출. 같은 질문은 SQLite에 캐시해서 비용을 아낀다."""
import hashlib
import json
import time

import anthropic

from .config import CLAUDE_MODEL, anthropic_key
from .db import connect


class ClaudeError(Exception):
    pass


_client = None


def client():
    global _client
    if _client is None:
        if not anthropic_key():
            raise ClaudeError(".env 파일에 ANTHROPIC_API_KEY가 없어요. README의 'Claude API 키' 부분을 참고하세요.\n"
                              "   결제 없이 하려면 일본어 검색어를 직접 넣는 check 명령을 쓰세요:\n"
                              '   python jp_shorts_finder.py check --keywords "ドッキリ リアクション"')
        _client = anthropic.Anthropic(api_key=anthropic_key())
    return _client


def ask_json(kind, prompt, schema, max_tokens=8000):
    """Claude에게 묻고 schema 모양의 JSON을 돌려받는다. 같은 kind+prompt는 캐시에서 꺼낸다."""
    key = hashlib.sha256(f"{CLAUDE_MODEL}|{kind}|{prompt}".encode()).hexdigest()
    with connect() as con:
        row = con.execute("SELECT response FROM llm_cache WHERE cache_key = ?", (key,)).fetchone()
    if row:
        return json.loads(row[0])

    try:
        resp = client().beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            # 안전 필터가 거절하면 서버가 알아서 다른 모델로 다시 시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "low",  # 번역·분류처럼 단순한 작업이라 낮게 (빠르고 저렴)
                "format": {"type": "json_schema", "schema": schema},
            },
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise ClaudeError(".env의 ANTHROPIC_API_KEY가 올바르지 않아요. 키를 다시 복사해 붙여넣어 주세요.")
    except anthropic.PermissionDeniedError:
        raise ClaudeError("이 Anthropic API 키로는 사용 권한이 없어요. 콘솔에서 키 상태를 확인하세요.")
    except anthropic.RateLimitError:
        raise ClaudeError("Claude API 사용량 한도에 걸렸어요. 잠시 뒤 다시 시도하세요.")
    except anthropic.BadRequestError as e:
        if "credit" in str(e).lower():
            raise ClaudeError("Anthropic 계정 크레딧이 부족해요. console.anthropic.com → Billing에서 충전하세요.")
        raise ClaudeError(f"Claude 요청 오류: {e.message}")
    except anthropic.APIConnectionError:
        raise ClaudeError("Claude API에 연결할 수 없어요. 인터넷 연결을 확인하세요.")
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Claude API 오류 ({e.status_code}). 잠시 뒤 다시 시도하세요.")

    if resp.stop_reason == "refusal":
        raise ClaudeError("Claude가 이 요청을 거절했어요. 제목 내용을 확인해 주세요.")
    if resp.stop_reason == "max_tokens":
        raise ClaudeError("Claude 응답이 너무 길어서 잘렸어요. 한 번에 확인하는 개수(--limit)를 줄여 주세요.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    data = json.loads(text)

    with connect() as con:
        con.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?)",
                    (key, json.dumps(data, ensure_ascii=False), time.time()))
    return data
