import asyncio
import os
import sqlite3
import http.server
import threading
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from google import genai

# --- Веб-заглушка для Render ---
def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = http.server.HTTPServer(("0.0.0.0", port), http.server.SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# --- Конфигурация ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_ID = int(os.environ.get("MY_TELEGRAM_ID", 0))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# --- Работа с Базой Данных (SQLite) ---
DB_NAME = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            user_id INTEGER PRIMARY KEY
        )
    """)
    # Автоматически добавляем админа при инициализации
    if ADMIN_ID != 0:
        cursor.execute("INSERT OR IGNORE INTO whitelist (user_id) VALUES (?)", (ADMIN_ID,))
    conn.commit()
    conn.close()

def get_allowed_users() -> set:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM whitelist")
    users = {row[0] for row in cursor.fetchall()}
    conn.close()
    return users

def add_to_whitelist(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO whitelist (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def remove_from_whitelist(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM whitelist WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# Инициализируем БД
init_db()

# Хранилище сессий ИИ в оперативной памяти
user_sessions = {}

def get_user_chat(user_id: int):
    if user_id not in user_sessions:
        user_sessions[user_id] = ai_client.chats.create(model="gemini-3.6-flash")
    return user_sessions[user_id]

# --- Клавиатуры (кнопки под сообщениями) ---
def get_main_keyboard(is_admin: bool):
    buttons = [
        [InlineKeyboardButton(text="🔄 Сбросить диалог", callback_data="reset_chat")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="📋 Белый список", callback_data="show_whitelist")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- Подсказки команд ---
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню и статус"),
        BotCommand(command="reset", description="Сбросить контекст диалога"),
        BotCommand(command="allow", description="[Admin] Добавить ID"),
        BotCommand(command="deny", description="[Admin] Удалить ID"),
        BotCommand(command="whitelist", description="[Admin] Список ID"),
    ]
    await bot.set_my_commands(commands)

# --- Обработчики команд ---
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

# --- Обработчик нажатий на Inline-кнопки ---
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

# --- Обработка обычных сообщений с эффектом печати ---
@dp.message(F.text)
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    allowed = get_allowed_users()
    
    if user_id not in allowed:
        await message.answer("⛔ У вас нет доступа к этому боту.")
        return

    # Отправляем индикатор печати "typing..."
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    try:
        user_chat = get_user_chat(user_id)
        response = user_chat.send_message(message.text)
        
        # Попытка разметки Markdown, если упадет — отправляем обычный текст
        try:
            await message.answer(response.text, parse_mode="Markdown")
        except Exception:
            await message.answer(response.text)
            
    except Exception as e:
        await message.answer(f"⚠️ Ошибка при запросе к ИИ: {e}")

# --- Запуск бота ---
async def main():
    await set_bot_commands(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())