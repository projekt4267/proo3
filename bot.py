import os
import requests
from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def ask_ai(text):
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "openrouter/free",
            "messages": [
                {
                    "role": "system",
                    "content": "Ты дружелюбный AI-ассистент ZentraAI. Отвечай понятно на русском языке."
                },
                {
                    "role": "user",
                    "content": text
                }
            ]
        },
        timeout=60
    )

    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def send_message(chat_id, text):
    requests.post(
        TELEGRAM_URL,
        json={
            "chat_id": chat_id,
            "text": text
        },
        timeout=30
    )


@app.route("/")
def home():
    return "ZentraAI is running!"


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.json

    message = update.get("message")

    if not message:
        return "ok"

    text = message.get("text")
    chat_id = message["chat"]["id"]

    if not text:
        return "ok"

    try:
        answer = ask_ai(text)
        send_message(chat_id, answer)
    except Exception as e:
        print(e)
        send_message(chat_id, "Произошла ошибка 😔")

    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)