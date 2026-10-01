import os
import sqlite3
import requests

from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

DB_FILE = "memory.db"

SYSTEM_PROMPT = """
Ты — ZentraAI, дружелюбный и умный AI-ассистент.

Твой характер:
- отвечай естественно и по-человечески;
- будь дружелюбным, но не навязчивым;
- объясняй сложные вещи простыми словами;
- если пользователь просит подробный ответ — отвечай подробно;
- если вопрос простой — не растягивай ответ;
- используй русский язык, если пользователь пишет по-русски;
- не придумывай факты, если не уверен;
- можешь использовать эмодзи, но умеренно.

Ты находишься внутри Telegram-бота под названием ZentraAI.
"""


# =========================
# DATABASE
# =========================

def init_db():
    connection = sqlite3.connect(DB_FILE)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()


def get_history(chat_id):
    connection = sqlite3.connect(DB_FILE)

    rows = connection.execute(
        """
        SELECT role, content
        FROM messages
        WHERE chat_id = ?
        ORDER BY id ASC
        """,
        (str(chat_id),)
    ).fetchall()

    connection.close()

    return [
        {
            "role": role,
            "content": content
        }
        for role, content in rows
    ]


def save_message(chat_id, role, content):
    connection = sqlite3.connect(DB_FILE)

    connection.execute(
        """
        INSERT INTO messages (chat_id, role, content)
        VALUES (?, ?, ?)
        """,
        (str(chat_id), role, content)
    )

    connection.commit()
    connection.close()


def clear_history(chat_id):
    connection = sqlite3.connect(DB_FILE)

    connection.execute(
        "DELETE FROM messages WHERE chat_id = ?",
        (str(chat_id),)
    )

    connection.commit()
    connection.close()


# =========================
# TELEGRAM
# =========================

def send_message(chat_id, text):
    # Telegram имеет ограничение примерно 4096 символов.
    chunks = []

    while len(text) > 4000:
        split_at = text.rfind("\n", 0, 4000)

        if split_at < 1000:
            split_at = 4000

        chunks.append(text[:split_at])
        text = text[split_at:]

    chunks.append(text)

    for chunk in chunks:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk
            },
            timeout=30
        )


def send_typing(chat_id):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendChatAction",
            json={
                "chat_id": chat_id,
                "action": "typing"
            },
            timeout=10
        )
    except Exception:
        pass


# =========================
# AI
# =========================

def ask_ai(chat_id, user_text):

    history = get_history(chat_id)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    # Ограничиваем количество старых сообщений,
    # чтобы история не становилась бесконечной.
    messages.extend(history[-20:])

    messages.append({
        "role": "user",
        "content": user_text
    })

    response = requests.post(
        OPENROUTER_API,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "openrouter/free",
            "messages": messages
        },
        timeout=90
    )

    response.raise_for_status()

    data = response.json()

    answer = data["choices"][0]["message"]["content"]

    return answer


# =========================
# COMMANDS
# =========================

def handle_command(chat_id, command):

    command = command.lower().split("@")[0]

    if command == "/start":
        send_message(
            chat_id,
            "👋 Привет! Я **ZentraAI**.\n\n"
            "Я могу отвечать на вопросы, поддерживать разговор "
            "и помнить контекст нашей беседы.\n\n"
            "🧠 Память — включена\n"
            "🤖 AI — подключён\n\n"
            "Напиши мне что-нибудь!"
        )
        return True

    if command == "/help":
        send_message(
            chat_id,
            "🤖 **ZentraAI — команды**\n\n"
            "/start — запустить бота\n"
            "/help — показать помощь\n"
            "/reset — очистить память разговора\n"
            "/model — информация о модели\n\n"
            "Просто отправь сообщение, чтобы поговорить со мной."
        )
        return True

    if command == "/reset":
        clear_history(chat_id)

        send_message(
            chat_id,
            "🧹 Память этого разговора очищена.\n\n"
            "Начинаем с чистого листа!"
        )
        return True

    if command == "/model":
        send_message(
            chat_id,
            "🧠 **ZentraAI**\n\n"
            "Модель выбирается через OpenRouter.\n"
            "Сейчас используется бесплатный маршрутизатор OpenRouter."
        )
        return True

    return False


# =========================
# WEB SERVER
# =========================

@app.route("/")
def home():
    return "ZentraAI is running! 🤖"


@app.route("/webhook", methods=["POST"])
def webhook():

    try:
        update = request.get_json(silent=True)

        if not update:
            return "ok"

        message = update.get("message")

        if not message:
            return "ok"

        chat = message.get("chat")

        if not chat:
            return "ok"

        chat_id = chat["id"]

        text = message.get("text")

        if not text:
            return "ok"

        # Команды
        if text.startswith("/"):
            if handle_command(chat_id, text):
                return "ok"

        send_typing(chat_id)

        # Сохраняем вопрос пользователя
        save_message(
            chat_id,
            "user",
            text
        )

        try:
            answer = ask_ai(
                chat_id,
                text
            )

        except requests.exceptions.Timeout:

            send_message(
                chat_id,
                "⏳ AI отвечает слишком долго. Попробуй ещё раз."
            )

            return "ok"

        except requests.exceptions.RequestException as error:

            print("OpenRouter error:", error)

            send_message(
                chat_id,
                "⚠️ Не удалось связаться с AI. Попробуй через несколько секунд."
            )

            return "ok"

        except Exception as error:

            print("AI error:", error)

            send_message(
                chat_id,
                "⚠️ Произошла ошибка при обработке сообщения."
            )

            return "ok"

        # Сохраняем ответ AI
        save_message(
            chat_id,
            "assistant",
            answer
        )

        send_message(
            chat_id,
            answer
        )

        return "ok"

    except Exception as error:

        print("Webhook error:", error)

        return "ok"


# =========================
# START
# =========================

init_db()


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
