import os
import psycopg
import requests

from flask import Flask, request

app = Flask(__name__)


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]


# =========================================================
# API
# =========================================================

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

DEEPSEEK_API = "https://api.deepseek.com/chat/completions"


# =========================================================
# SYSTEM PROMPT
# =========================================================

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


# =========================================================
# DATABASE
# =========================================================

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
            """, (
                chat_id,
                role,
                content
            ))

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

            rows = cur.fetchall()

    return [
        row[0]
        for row in rows
    ]


def add_memory(chat_id, memory):

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO memories
                    (chat_id, memory)
                VALUES
                    (%s, %s)
            """, (
                chat_id,
                memory
            ))

        conn.commit()


def clear_memories(chat_id):

    with db() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM memories
                WHERE chat_id = %s
            """, (chat_id,))

        conn.commit()


# =========================================================
# TELEGRAM
# =========================================================

def send_message(chat_id, text):

    if not text:
        return

    while len(text) > 4000:

        split_at = text.rfind("\n", 0, 4000)

        if split_at < 1000:
            split_at = 4000

        part = text[:split_at]
        text = text[split_at:]

        try:

            requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": part
                },
                timeout=30
            )

        except Exception as error:

            print(
                "Telegram send error:",
                error
            )

            return

    try:

        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text
            },
            timeout=30
        )

    except Exception as error:

        print(
            "Telegram send error:",
            error
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


# =========================================================
# DEEPSEEK AI
# =========================================================

def ask_ai(chat_id, user_text):

    history = get_history(chat_id)

    memories = get_memories(chat_id)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]


    # -----------------------------------------------------
    # MEMORY
    # -----------------------------------------------------

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


    # -----------------------------------------------------
    # HISTORY
    # -----------------------------------------------------

    messages.extend(history)


    # -----------------------------------------------------
    # CURRENT USER MESSAGE
    # -----------------------------------------------------

    messages.append({
        "role": "user",
        "content": user_text
    })


    # -----------------------------------------------------
    # DEBUG
    # -----------------------------------------------------

    print(
        "DeepSeek key exists:",
        bool(DEEPSEEK_API_KEY)
    )

    print(
        "DeepSeek key prefix:",
        DEEPSEEK_API_KEY[:10]
        if DEEPSEEK_API_KEY
        else "EMPTY"
    )


    # -----------------------------------------------------
    # REQUEST
    # -----------------------------------------------------

    response = requests.post(

        DEEPSEEK_API,

        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        },

        json={
            "model": "deepseek-flash",
            "messages": messages,
            "stream": False
        },

        timeout=90
    )


    # -----------------------------------------------------
    # DEBUG RESPONSE
    # -----------------------------------------------------

    print(
        "DeepSeek status:",
        response.status_code
    )

    print(
        "DeepSeek response:",
        response.text
    )


    # -----------------------------------------------------
    # CHECK HTTP
    # -----------------------------------------------------

    response.raise_for_status()


    # -----------------------------------------------------
    # PARSE JSON
    # -----------------------------------------------------

    data = response.json()


    # -----------------------------------------------------
    # CHECK CHOICES
    # -----------------------------------------------------

    if "choices" not in data:

        raise RuntimeError(
            f"DeepSeek не вернул choices: {data}"
        )


    if not data["choices"]:

        raise RuntimeError(
            f"DeepSeek вернул пустой choices: {data}"
        )


    # -----------------------------------------------------
    # GET ANSWER
    # -----------------------------------------------------

    answer = data["choices"][0]["message"]["content"]


    if not answer:

        raise RuntimeError(
            "DeepSeek вернул пустой ответ"
        )


    return answer


# =========================================================
# COMMANDS
# =========================================================

def command(chat_id, text):

    cmd = text.lower().split("@")[0].split()[0]


    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    if cmd == "/start":

        send_message(
            chat_id,

            "👋 Привет! Я ZentraAI.\n\n"
            "Я могу общаться с тобой, помнить контекст "
            "разговора и сохранять важную информацию о тебе.\n\n"
            "🧠 Память включена\n"
            "💬 История сохраняется\n"
            "🤖 AI подключён\n\n"
            "Напиши мне что-нибудь!"
        )

        return True


    # -----------------------------------------------------
    # HELP
    # -----------------------------------------------------

    if cmd == "/help":

        send_message(
            chat_id,

            "🤖 ZentraAI\n\n"
            "/start — запустить бота\n"
            "/help — помощь\n"
            "/memory — что я помню о тебе\n"
            "/forget — забыть всё о тебе\n"
            "/reset — очистить текущий разговор\n"
            "/id — показать ID этого чата\n\n"
            "Просто напиши сообщение, чтобы поговорить со мной."
        )

        return True


    # -----------------------------------------------------
    # ID
    # -----------------------------------------------------

    if cmd == "/id":

        send_message(
            chat_id,

            f"🆔 ID этого чата:\n{chat_id}"
        )

        return True


    # -----------------------------------------------------
    # RESET
    # -----------------------------------------------------

    if cmd == "/reset":

        clear_history(chat_id)

        send_message(
            chat_id,

            "🧹 История текущего разговора очищена."
        )

        return True


    # -----------------------------------------------------
    # MEMORY
    # -----------------------------------------------------

    if cmd == "/memory":

        memories = get_memories(chat_id)


        if not memories:

            send_message(
                chat_id,

                "🧠 Я пока ничего специально о тебе не запомнил."
            )

        else:

            text = "🧠 Что я помню:\n\n"

            for memory in memories:

                text += f"• {memory}\n"

            send_message(
                chat_id,
                text
            )

        return True


    # -----------------------------------------------------
    # FORGET
    # -----------------------------------------------------

    if cmd == "/forget":

        clear_memories(chat_id)

        send_message(
            chat_id,

            "🧹 Я удалил сохранённую память о тебе."
        )

        return True


    return False


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return "ZentraAI v2 is running! 🤖"


# =========================================================
# WEBHOOK
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        update = request.get_json(
            silent=True
        )


        if not update:

            return "ok"


        message = update.get(
            "message"
        )


        if not message:

            return "ok"


        chat = message.get(
            "chat"
        )


        if not chat:

            return "ok"


        chat_id = chat["id"]


        # -------------------------------------------------
        # SAVE USER
        # -------------------------------------------------

        save_user(chat)


        # -------------------------------------------------
        # GET TEXT
        # -------------------------------------------------

        text = message.get(
            "text"
        )


        if not text:

            return "ok"


        # -------------------------------------------------
        # COMMAND
        # -------------------------------------------------

        if text.startswith("/"):

            if command(
                chat_id,
                text
            ):

                return "ok"


        # -------------------------------------------------
        # TYPING
        # -------------------------------------------------

        typing(chat_id)


        # -------------------------------------------------
        # SAVE USER MESSAGE
        # -------------------------------------------------

        save_message(
            chat_id,
            "user",
            text
        )


        # =================================================
        # ASK AI
        # =================================================

        try:

            answer = ask_ai(
                chat_id,
                text
            )


        except requests.exceptions.Timeout as error:

            print(
                "DeepSeek timeout:",
                error
            )

            send_message(
                chat_id,

                "⏳ AI отвечает слишком долго. "
                "Попробуй ещё раз."
            )

            return "ok"


        except requests.exceptions.HTTPError as error:

            print(
                "DeepSeek HTTP error:",
                error
            )

            send_message(
                chat_id,

                "⚠️ DeepSeek отклонил запрос. "
                "Подробность есть в Render Logs."
            )

            return "ok"


        except requests.exceptions.RequestException as error:

            print(
                "DeepSeek connection error:",
                error
            )

            send_message(
                chat_id,

                "⚠️ Не удалось связаться с DeepSeek."
            )

            return "ok"


        except Exception as error:

            print(
                "AI error:",
                error
            )

            send_message(
                chat_id,

                "⚠️ Произошла ошибка AI. "
                "Проверь Render Logs."
            )

            return "ok"


        # -------------------------------------------------
        # SAVE AI MESSAGE
        # -------------------------------------------------

        save_message(
            chat_id,
            "assistant",
            answer
        )


        # -------------------------------------------------
        # SEND AI MESSAGE
        # -------------------------------------------------

        send_message(
            chat_id,
            answer
        )


        return "ok"


    except Exception as error:

        print(
            "Webhook error:",
            error
        )

        return "ok"


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

try:

    init_db()

except Exception as error:

    print(
        "Database initialization error:",
        error
    )


# =========================================================
# START SERVER
# =========================================================

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
