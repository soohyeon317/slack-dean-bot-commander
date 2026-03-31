import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import anthropic
from google import genai
from google.genai import types

app = App(token=os.environ["SLACK_BOT_TOKEN"])
claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
client_gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# 대화 히스토리 저장소 (thread_ts → messages 리스트)
# 실서비스에서는 Redis나 DB로 교체 권장
conversation_history = {}

###############
# Claude 연동 (대화 히스토리 저장하지 않는 버전)
###############
# @app.command("/ask")
# def handle_ask(ack, respond, command):
#     ack()  # Slack에 즉시 응답 (3초 이내 필수)
#
#     user_input = command["text"]
#     if not user_input:
#         respond("질문을 입력해주세요. 예: `/ask 오늘 날씨 어때?`")
#         return
#
#     # Claude API 호출
#     message = claude.messages.create(
#         model="claude-sonnet-4-20250514",
#         max_tokens=1024,
#         messages=[{"role": "user", "content": user_input}]
#     )
#
#     answer = message.content[0].text
#     respond(f"*질문:* {user_input}\n\n*Claude:* {answer}")

###############
# Claude 연동 (대화 히스토리 저장하는 버전)
###############
# @app.command("/ask")
# def handle_ask(ack, respond, command, client):
#     ack()
#
#     user_input = command["text"]
#     user_id = command["user_id"]
#     channel_id = command["channel_id"]
#
#     if not user_input:
#         respond("질문을 입력해주세요. 예: `/ask 안녕!`")
#         return
#
#     # 첫 메시지 전송 → thread_ts 획득
#     result = client.chat_postMessage(
#         channel=channel_id,
#         text=f"*<@{user_id}>의 질문:* {user_input}"
#     )
#     thread_ts = result["ts"]  # 스레드 키로 사용
#
#     # 히스토리 초기화 (새 대화)
#     if thread_ts not in conversation_history:
#         conversation_history[thread_ts] = []
#
#     # 유저 메시지 추가
#     conversation_history[thread_ts].append({
#         "role": "user",
#         "content": user_input
#     })
#
#     # Claude API 호출 (전체 히스토리 전달)
#     response = claude.messages.create(
#         model="claude-sonnet-4-20250514",
#         max_tokens=1024,
#         system="당신은 친절한 Slack 어시스턴트입니다.",
#         messages=conversation_history[thread_ts]
#     )
#
#     answer = response.content[0].text
#
#     # 어시스턴트 응답 히스토리에 추가
#     conversation_history[thread_ts].append({
#         "role": "assistant",
#         "content": answer
#     })
#
#     # 스레드에 Claude 응답 달기
#     client.chat_postMessage(
#         channel=channel_id,
#         thread_ts=thread_ts,
#         text=f"*Claude:* {answer}"
#     )

###############
# Gemini 연동 (대화 히스토리 저장하지 않는 버전)
###############
@app.command("/ask")
def handle_ask(ack, respond, command, client):
    ack()

    user_input = command["text"]
    user_id = command["user_id"]
    channel_id = command["channel_id"]

    if not user_input:
        respond("질문을 입력해주세요. 예: `/ask 안녕!`")
        return

    result = client.chat_postMessage(
        channel=channel_id,
        text=f"*<@{user_id}>의 질문:* {user_input}"
    )
    thread_ts = result["ts"]

    if thread_ts not in conversation_history:
        conversation_history[thread_ts] = []

    # Gemini 형식으로 히스토리 추가 (role: user/model)
    conversation_history[thread_ts].append(
        types.Content(role="user", parts=[types.Part(text=user_input)])
    )

    # Gemini API 호출
    response = client_gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=conversation_history[thread_ts],
        config=types.GenerateContentConfig(
            system_instruction="당신은 친절한 Slack 어시스턴트입니다.",
            max_output_tokens=1024,
        )
    )

    answer = response.text

    # Gemini 응답 히스토리 추가 (role: model)
    conversation_history[thread_ts].append(
        types.Content(role="model", parts=[types.Part(text=answer)])
    )

    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=f"*Gemini:* {answer}"
    )

###############
# Claude 연동
###############
# @app.event("app_mention")
# def handle_mention(event, client, say):
#     thread_ts = event.get("thread_ts") or event["ts"]
#     user_input = event["text"].split(">", 1)[-1].strip()  # 멘션 제거
#     channel_id = event["channel"]
#
#     # 기존 히스토리 가져오기 (없으면 빈 리스트)
#     history = conversation_history.get(thread_ts, [])
#
#     history.append({"role": "user", "content": user_input})
#
#     response = claude.messages.create(
#         model="claude-sonnet-4-20250514",
#         max_tokens=1024,
#         system="당신은 친절한 Slack 어시스턴트입니다.",
#         messages=history
#     )
#
#     answer = response.content[0].text
#     history.append({"role": "assistant", "content": answer})
#
#     conversation_history[thread_ts] = history
#
#     say(text=answer, thread_ts=thread_ts)

###############
# Gemini 연동
###############
@app.event("app_mention")
def handle_mention(event, client, say):
    thread_ts = event.get("thread_ts") or event["ts"]
    user_input = event["text"].split(">", 1)[-1].strip()  # 멘션(@봇) 제거
    channel_id = event["channel"]

    if not user_input:
        say(text="질문을 입력해주세요!", thread_ts=thread_ts)
        return

    # 기존 히스토리 가져오기
    history = conversation_history.get(thread_ts, [])

    # Gemini 형식으로 유저 메시지 추가
    history.append(
        types.Content(role="user", parts=[types.Part(text=user_input)])
    )

    # Gemini API 호출
    response = client_gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=history,
        config=types.GenerateContentConfig(
            system_instruction="당신은 친절한 Slack 어시스턴트입니다.",
            max_output_tokens=1024,
        )
    )

    answer = response.text

    # Gemini 응답 히스토리 추가
    history.append(
        types.Content(role="model", parts=[types.Part(text=answer)])
    )

    # 히스토리 저장
    conversation_history[thread_ts] = history

    say(text=f"*Gemini:* {answer}", thread_ts=thread_ts)

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()