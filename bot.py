import asyncio
import logging
import sqlite3
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
from google import genai

logging.basicConfig(level=logging.INFO)

# --- Конфигурация ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("MY_TELEGRAM_ID", 0))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# --- База Данных ---
DB_NAME = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
    if ADMIN_ID != 0:
        cursor.execute("INSERT OR REPLACE INTO whitelist (user_id, username) VALUES (?, ?)", (ADMIN_ID, "Admin"))
    conn.commit()
    conn.close()

def get_allowed_users() -> set:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM whitelist")
    users = {row[0] for row in cursor.fetchall()}
    conn.close()
    return users

def add_to_whitelist(user_id: int, username: str = ""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO whitelist (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def remove_from_whitelist(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM whitelist WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_whitelist_with_names():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username FROM whitelist")
    rows = cursor.fetchall()
    conn.close()
    return rows

init_db()

# --- Сессии ИИ ---
user_sessions = {}

def get_user_chat(user_id: int):
    if user_id not in user_sessions and ai_client:
        user_sessions[user_id] = ai_client.chats.create(model="gemini-2.5-flash")
    return user_sessions.get(user_id)

# --- Клавиатуры ---
def get_main_keyboard(is_admin: bool):
    buttons = [
        [InlineKeyboardButton(text="🔄 Сбросить диалог", callback_data="reset_chat")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="📋 Белый список", callback_data="show_whitelist")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню и статус"),
        BotCommand(command="reset", description="Сбросить контекст диалога"),
        BotCommand(command="allow", description="[Admin] Добавить ID"),
        BotCommand(command="deny", description="[Admin] Удалить ID"),
        BotCommand(command="whitelist", description="[Admin] Список ID"),
    ]
    await bot.set_my_commands(commands)

# --- Команды Telegram-бота ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user_id = message.from_user.id
    allowed = get_allowed_users()
    
    if user_id not in allowed:
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return

    is_admin = (user_id == ADMIN_ID)
    text = "👋 **Привет! Я твой ИИ-ассистент.**\n\nОтправь мне любое сообщение, и я отвечу!"
    await message.answer(text, reply_markup=get_main_keyboard(is_admin), parse_mode="Markdown")

@dp.message(Command("reset"))
async def reset_cmd(message: types.Message):
    user_id = message.from_user.id
    user_sessions.pop(user_id, None)
    await message.answer("🔄 Контекст вашего диалога сброшен!")

@dp.message(Command("allow"))
async def allow_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: `/allow <telegram_id>`", parse_mode="Markdown")
        return

    target_id = int(args[1])
    add_to_whitelist(target_id)
    await message.answer(f"✅ Пользователь `{target_id}` сохранен в базу данных и добавлен в белый список.", parse_mode="Markdown")

@dp.message(Command("deny"))
async def deny_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: `/deny <telegram_id>`", parse_mode="Markdown")
        return

    target_id = int(args[1])
    if target_id == ADMIN_ID:
        await message.answer("❌ Нельзя удалить себя из белого списка!")
        return

    remove_from_whitelist(target_id)
    user_sessions.pop(target_id, None)
    await message.answer(f"🚫 Пользователь `{target_id}` удален из базы данных и белого списка.", parse_mode="Markdown")

@dp.message(Command("whitelist"))
async def whitelist_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    users = get_allowed_users()
    users_list = "\n".join([f"• `{uid}`" for uid in users])
    await message.answer(f"📋 **Белый список (из БД):**\n{users_list}", parse_mode="Markdown")

# --- Callbacks ---
@dp.callback_query(F.data == "reset_chat")
async def cb_reset(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_sessions.pop(user_id, None)
    await callback.answer("Контекст очищен!")
    await callback.message.answer("🔄 Контекст общения сброшен.")

@dp.callback_query(F.data == "show_whitelist")
async def cb_whitelist(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    users = get_allowed_users()
    users_list = "\n".join([f"• `{uid}`" for uid in users])
    await callback.answer()
    await callback.message.answer(f"📋 **Белый список (из БД):**\n{users_list}", parse_mode="Markdown")

# --- Сообщения ---
@dp.message(F.text)
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    allowed = get_allowed_users()
    
    if user_id not in allowed:
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    try:
        user_chat = get_user_chat(user_id)
        if not user_chat:
            await message.answer("⚠️ Ошибка: GEMINI_API_KEY не задан.")
            return

        response = user_chat.send_message(message.text)
        try:
            await message.answer(response.text, parse_mode="Markdown")
        except Exception:
            await message.answer(response.text)
            
    except Exception as e:
        await message.answer(f"⚠️ Ошибка при запросе к ИИ: {e}")

# --- ВЕБ-АДМИНКА (aiohttp) ---
def get_login_html(error=""):
    error_block = f"<div class='error'>{error}</div>" if error else ""
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Вход в панель</title>
    <style>
        body {{ font-family: sans-serif; background: #1a1a1a; color: #fff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .card {{ background: #2a2a2a; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); width: 300px; }}
        input[type="password"] {{ width: 100%; padding: 10px; margin: 10px 0; border-radius: 4px; border: 1px solid #444; background: #333; color: #fff; box-sizing: border-box; }}
        button {{ width: 100%; padding: 10px; background: #28a745; border: none; color: #fff; border-radius: 4px; cursor: pointer; font-size: 16px; }}
        button:hover {{ background: #218838; }}
        .error {{ color: #ff6b6b; margin-top: 10px; text-align: center; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Админ-панель</h2>
        <form method="POST" action="/login">
            <input type="password" name="password" placeholder="Введите пароль" required>
            <button type="submit">Войти</button>
        </form>
        {error_block}
    </div>
</body>
</html>"""

def get_dashboard_html(users_rows):
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Управление ботом</title>
    <style>
        body {{ font-family: sans-serif; background: #181818; color: #e0e0e0; margin: 40px; }}
        h1 {{ color: #fff; }}
        .card {{ background: #242424; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        input[type="text"] {{ padding: 8px; border-radius: 4px; border: 1px solid #444; background: #333; color: #fff; width: 250px; }}
        button {{ padding: 8px 15px; background: #007bff; border: none; color: #fff; border-radius: 4px; cursor: pointer; }}
        button.del {{ background: #dc3545; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ background: #2c2c2c; }}
    </style>
</head>
<body>
    <h1>Панель управления Белым Списком</h1>
    <div class="card">
        <h3>Добавить пользователя</h3>
        <form method="POST" action="/add">
            <input type="text" name="user_id" placeholder="Telegram User ID" required>
            <input type="text" name="username" placeholder="Username (необязательно)">
            <button type="submit">Добавить</button>
        </form>
    </div>
    <div class="card">
        <h3>Разрешенные пользователи</h3>
        <table>
            <tr>
                <th>User ID</th>
                <th>Username</th>
                <th>Действие</th>
            </tr>
            {users_rows}
        </table>
    </div>
</body>
</html>"""

async def handle_root(request):
    if request.cookies.get("auth") == "true":
        users = get_whitelist_with_names()
        rows = ""
        for u_id, u_name in users:
            rows += f"""
            <tr>
                <td>{u_id}</td>
                <td>@{u_name if u_name else 'N/A'}</td>
                <td>
                    <form method="POST" action="/delete" style="margin:0;">
                        <input type="hidden" name="user_id" value="{u_id}">
                        <button type="submit" class="del">Удалить</button>
                    </form>
                </td>
            </tr>"""
        if not rows:
            rows = "<tr><td colspan='3'>Список пуст</td></tr>"
        return web.Response(text=get_dashboard_html(rows), content_type="text/html")
    return web.Response(text=get_login_html(), content_type="text/html")

async def handle_login(request):
    data = await request.post()
    if data.get("password") == ADMIN_PASSWORD:
        response = web.HTTPFound('/')
        response.set_cookie("auth", "true")
        return response
    return web.Response(text=get_login_html("Неверный пароль"), content_type="text/html")

async def handle_add(request):
    if request.cookies.get("auth") != "true":
        return web.HTTPFound('/')
    data = await request.post()
    u_id = data.get("user_id")
    u_name = data.get("username", "").replace("@", "")
    if u_id and u_id.isdigit():
        add_to_whitelist(int(u_id), u_name)
    return web.HTTPFound('/')

async def handle_delete(request):
    if request.cookies.get("auth") != "true":
        return web.HTTPFound('/')
    data = await request.post()
    u_id = data.get("user_id")
    if u_id and u_id.isdigit():
        remove_from_whitelist(int(u_id))
        user_sessions.pop(int(u_id), None)
    return web.HTTPFound('/')

# --- Запуск приложения ---
async def main():
    app = web.Application()
    app.router.add_get('/', handle_root)
    app.router.add_post('/login', handle_login)
    app.router.add_post('/add', handle_add)
    app.router.add_post('/delete', handle_delete)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    
    logging.info(f"Запуск веб-сервера на порту {PORT}...")
    await site.start()
    
    await set_bot_commands(bot)
    logging.info("Запуск Telegram-бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())