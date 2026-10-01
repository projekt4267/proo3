import os
import psycopg
import requests

from flask import Flask, request

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"


SYSTEM_PROMPT = """
Ты — ZentraAI, дружелюбный персональный AI-ассистент.

Характер:
- дружелюбный;
- спокойный;
- умный;
- отвечай естественно;
- объясняй сложное простыми словами;
- не используй слишком много эмодзи;
- отвечай на языке пользователя;
- учитывай контекст предыдущего разговора;
- не выдумывай информацию, если не уверен.

Ты работаешь внутри Telegram.
"""


# =========================
# DATABASE
# =========================

def db():
    return psycopg.connect(DATABASE_URL)


def init_db():
    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    memory TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        conn.commit()


def save_user(chat):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users
                    (chat_id, username, first_name)
                VALUES
                    (%s, %s, %s)
                ON CONFLICT (chat_id)
                DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_seen = CURRENT_TIMESTAMP
            """, (
                chat["id"],
                chat.get("username"),
                chat.get("first_name")
            ))

        conn.commit()


def save_message(chat_id, role, content):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO messages
                    (chat_id, role, content)
                VALUES
                    (%s, %s, %s)
            """, (chat_id, role, content))

        conn.commit()


def get_history(chat_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT role, content
                FROM messages
                WHERE chat_id = %s
                ORDER BY id DESC
                LIMIT 20
            """, (chat_id,))

            rows = cur.fetchall()

    rows.reverse()

    return [
        {
            "role": role,
            "content": content
        }
        for role, content in rows
    ]


def clear_history(chat_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM messages
                WHERE chat_id = %s
            """, (chat_id,))

        conn.commit()


def get_memories(chat_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT memory
                FROM memories
                WHERE chat_id = %s
                ORDER BY id DESC
                LIMIT 20
            """, (chat_id,))

            return [row[0] for row in cur.fetchall()]


def add_memory(chat_id, memory):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO memories
                    (chat_id, memory)
                VALUES
                    (%s, %s)
            """, (chat_id, memory))

        conn.commit()


def clear_memories(chat_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM memories
                WHERE chat_id = %s
            """, (chat_id,))

        conn.commit()


# =========================
# TELEGRAM
# =========================

def send_message(chat_id, text):
    # Разбиваем длинный ответ на части.
    while len(text) > 4000:

        split_at = text.rfind("\n", 0, 4000)

        if split_at < 1000:
            split_at = 4000

        part = text[:split_at]
        text = text[split_at:]

        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": part
            },
            timeout=30
        )

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text
        },
        timeout=30
    )


def typing(chat_id):
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
    memories = get_memories(chat_id)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    if memories:
        memory_text = "\n".join(
            f"- {memory}"
            for memory in memories
        )

        messages.append({
            "role": "system",
            "content": (
                "Важная информация о пользователе:\n"
                + memory_text
            )
        })

    messages.extend(history)

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

    return data["choices"][0]["message"]["content"]


# =========================
# COMMANDS
# =========================

def command(chat_id, text):

    cmd = text.lower().split("@")[0].split()[0]

    if cmd == "/start":

        send_message(
            chat_id,
            "👋 Привет! Я **ZentraAI**.\n\n"
            "Я могу общаться с тобой, помнить контекст "
            "разговора и сохранять важную информацию о тебе.\n\n"
            "🧠 Память включена\n"
            "💬 История сохраняется\n"
            "🤖 AI подключён\n\n"
            "Напиши мне что-нибудь!"
        )

        return True

    if cmd == "/help":

        send_message(
            chat_id,
            "🤖 **ZentraAI**\n\n"
            "/start — запустить бота\n"
            "/help — помощь\n"
            "/memory — что я помню о тебе\n"
            "/forget — забыть всё о тебе\n"
            "/reset — очистить текущий разговор\n"
            "/id — показать ID этого чата\n\n"
            "Просто напиши сообщение, чтобы поговорить со мной."
        )

        return True

    if cmd == "/id":

        send_message(
            chat_id,
            f"🆔 ID этого чата:\n`{chat_id}`"
        )

        return True

    if cmd == "/reset":

        clear_history(chat_id)

        send_message(
            chat_id,
            "🧹 История текущего разговора очищена."
        )

        return True

    if cmd == "/memory":

        memories = get_memories(chat_id)

        if not memories:

            send_message(
                chat_id,
                "🧠 Я пока ничего специально о тебе не запомнил."
            )

        else:

            text = "🧠 **Что я помню:**\n\n"

            for memory in memories:
                text += f"• {memory}\n"

            send_message(chat_id, text)

        return True

    if cmd == "/forget":

        clear_memories(chat_id)

        send_message(
            chat_id,
            "🧹 Я удалил сохранённую память о тебе."
        )

        return True

    return False


# =========================
# WEBHOOK
# =========================

@app.route("/")
def home():
    return "ZentraAI v2 is running! 🤖"


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

        save_user(chat)

        text = message.get("text")

        if not text:
            return "ok"

        if text.startswith("/"):
            if command(chat_id, text):
                return "ok"

        typing(chat_id)

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
                "⚠️ Произошла ошибка. Попробуй ещё раз."
            )

            return "ok"

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

try:
    init_db()
except Exception as error:
    print("Database initialization error:", error)


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
