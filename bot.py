import os
import json
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from google import genai
from google.genai import types
import redis

# ── 클라이언트 초기화 ──────────────────────────────
app = App(token=os.environ["SLACK_BOT_TOKEN"])
client_gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

r = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    password=os.environ.get("REDIS_PASSWORD", None),
    decode_responses=True
)

TTL = 60 * 60 * 3  # 3시간 후 자동 만료

# ── Redis 유틸 함수 ────────────────────────────────
def get_history(thread_ts: str) -> list:
    """Redis에서 히스토리를 불러와 Gemini types.Content 리스트로 반환"""
    try:
        data = r.get(thread_ts)
        if not data:
            return []
        raw = json.loads(data)
        return [
            types.Content(
                role=item["role"],
                parts=[types.Part(text=p) for p in item["parts"]]
            )
            for item in raw
        ]
    except Exception as e:
        print(f"[Redis] get 오류: {e}")
        return []

def save_history(thread_ts: str, history: list):
    """Gemini types.Content 리스트를 JSON으로 직렬화해 Redis에 저장"""
    try:
        raw = [
            {
                "role": item.role,
                "parts": [p.text for p in item.parts]
            }
            for item in history
        ]
        r.setex(thread_ts, TTL, json.dumps(raw, ensure_ascii=False))
    except Exception as e:
        print(f"[Redis] save 오류: {e}")

def call_gemini(history: list) -> str:
    """Gemini API 호출 후 응답 텍스트 반환"""
    response = client_gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=history,
        config=types.GenerateContentConfig(
            system_instruction="당신은 친절한 Slack 어시스턴트입니다.",
            max_output_tokens=1024,
        )
    )
    return response.text

# ── /ask 슬래시 커맨드 ─────────────────────────────
@app.command("/ask")
def handle_ask(ack, respond, command, client):
    ack()

    user_input = command["text"]
    user_id    = command["user_id"]
    channel_id = command["channel_id"]

    if not user_input:
        respond("질문을 입력해주세요. 예: `/ask 안녕!`")
        return

    # 첫 메시지 전송 → thread_ts 획득
    result = client.chat_postMessage(
        channel=channel_id,
        text=f"*<@{user_id}>의 질문:* {user_input}"
    )
    thread_ts = result["ts"]

    history = get_history(thread_ts)
    history.append(
        types.Content(role="user", parts=[types.Part(text=user_input)])
    )

    answer = call_gemini(history)

    history.append(
        types.Content(role="model", parts=[types.Part(text=answer)])
    )
    save_history(thread_ts, history)

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f"*Gemini:* {answer}"
    )

# ── 멘션 이벤트 ───────────────────────────────────
@app.event("app_mention")
def handle_mention(event, client, say):
    thread_ts  = event.get("thread_ts") or event["ts"]
    user_input = event["text"].split(">", 1)[-1].strip()
    channel_id = event["channel"]

    if not user_input:
        say(text="질문을 입력해주세요!", thread_ts=thread_ts)
        return

    history = get_history(thread_ts)
    history.append(
        types.Content(role="user", parts=[types.Part(text=user_input)])
    )

    answer = call_gemini(history)

    history.append(
        types.Content(role="model", parts=[types.Part(text=answer)])
    )
    save_history(thread_ts, history)

    say(text=f"*Gemini:* {answer}", thread_ts=thread_ts)

# ── 실행 ──────────────────────────────────────────
if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
