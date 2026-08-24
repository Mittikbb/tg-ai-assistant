import asyncio
import logging
import sqlite3
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import web

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Переменные окружения (с дефолтными значениями для проверки)
BOT_TOKEN = os.getenv("BOT_TOKEN", "ТВОЙ_ТОКЕН_БОТА")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def is_whitelisted(user_id):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM whitelist WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def add_to_whitelist(user_id, username=""):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO whitelist (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def remove_from_whitelist(user_id):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM whitelist WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_whitelist():
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username FROM whitelist")
    rows = cursor.fetchall()
    conn.close()
    return rows

# --- ЛОГИКА ТЕЛЕГРАМ-БОТА ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if is_whitelisted(message.from_user.id):
        await message.answer("Привет! У тебя есть доступ к боту.")
    else:
        await message.answer(f"Доступ запрещен. Твой ID: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message()
async def handle_all_messages(message: types.Message):
    if not is_whitelisted(message.from_user.id):
        await message.answer("У вас нет доступа к боту.")
        return
    await message.answer("Сообщение получено!")

# --- ВЕБ-ПАНЕЛЬ АДМИНИСТРАТОРА (AIOHTTP) ---
HTML_LOGIN = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Вход в панель</title>
    <style>
        body { font-family: sans-serif; background: #1a1a1a; color: #fff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: #2a2a2a; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); width: 300px; }
        input[type="password"] { width: 100%; padding: 10px; margin: 10px 0; border-radius: 4px; border: 1px solid #444; background: #333; color: #fff; box-sizing: border-box; }
        button { width: 100%; padding: 10px; background: #28a745; border: none; color: #fff; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background: #218838; }
        .error { color: #ff6b6b; margin-top: 10px; text-align: center; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Админ-панель</h2>
        <form method="POST" action="/login">
            <input type="password" name="password" placeholder="Введите пароль" required>
            <button type="submit">Войти</button>
        </form>
        {error}
    </div>
</body>
</html>
"""

HTML_DASHBOARD = """
<!DOCTYPE html>
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
</html>
"""

async def handle_root(request):
    cookies = request.cookies
    if cookies.get("auth") == "true":
        users = get_whitelist()
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
            </tr>
            """
        if not rows:
            rows = "<tr><td colspan='3'>Список пуст</td></tr>"
        return web.Response(text=HTML_DASHBOARD.format(users_rows=rows), content_type="text/html")
    
    return web.Response(text=HTML_LOGIN.format(error=""), content_type="text/html")

async def handle_login(request):
    data = await request.post()
    if data.get("password") == ADMIN_PASSWORD:
        response = web.HTTPFound('/')
        response.set_cookie("auth", "true")
        return response
    return web.Response(text=HTML_LOGIN.format(error="<div class='error'>Неверный пароль</div>"), content_type="text/html")

async def handle_add(request):
    cookies = request.cookies
    if cookies.get("auth") != "true":
        return web.HTTPFound('/')
    data = await request.post()
    u_id = data.get("user_id")
    u_name = data.get("username", "").replace("@", "")
    if u_id and u_id.isdigit():
        add_to_whitelist(int(u_id), u_name)
    return web.HTTPFound('/')

async def handle_delete(request):
    cookies = request.cookies
    if cookies.get("auth") != "true":
        return web.HTTPFound('/')
    data = await request.post()
    u_id = data.get("user_id")
    if u_id and u_id.isdigit():
        remove_from_whitelist(int(u_id))
    return web.HTTPFound('/')

# --- ЗАПУСК ---
async def main():
    # Настройка веб-сервера
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
    
    logging.info("Запуск Telegram-бота...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())