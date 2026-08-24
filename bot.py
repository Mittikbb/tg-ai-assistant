import asyncio
import os
import http.server
import threading
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from google import genai
from aiogram.types import BotCommand

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

# Хранилище: белый список (set) и личные сессии Gemini (dict)
allowed_users = {ADMIN_ID}
user_sessions = {}

def get_user_chat(user_id: int):
    """Возвращает или создает отдельный чат Gemini для каждого пользователя."""
    if user_id not in user_sessions:
        user_sessions[user_id] = ai_client.chats.create(model="gemini-3.6-flash")
    return user_sessions[user_id]

# --- Админ-команды управления белым списком ---
@dp.message(Command("allow"))
async def allow_user(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: `/allow <telegram_id>`", parse_mode="Markdown")
        return

    target_id = int(args[1])
    allowed_users.add(target_id)
    await message.answer(f"Пользователь `{target_id}` добавлен в белый список.", parse_mode="Markdown")

@dp.message(Command("deny"))
async def deny_user(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: `/deny <telegram_id>`", parse_mode="Markdown")
        return

    target_id = int(args[1])
    if target_id == ADMIN_ID:
        await message.answer("Нельзя удалить себя из белого списка!")
        return

    allowed_users.discard(target_id)
    user_sessions.pop(target_id, None)
    await message.answer(f"Пользователь `{target_id}` удален из белого списка.", parse_mode="Markdown")

@dp.message(Command("whitelist"))
async def show_whitelist(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    users_list = "\n".join([f"• `{uid}`" for uid in allowed_users])
    await message.answer(f"**Белый список:**\n{users_list}", parse_mode="Markdown")

@dp.message(Command("reset"))
async def reset_context(message: types.Message):
    user_id = message.from_user.id
    if user_id not in allowed_users:
        return
    
    user_sessions.pop(user_id, None)
    await message.answer("Твой контекст общения с ИИ сброшен.")

# --- Обработка обычных сообщений ---
@dp.message(F.text)
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in allowed_users:
        await message.answer("У вас нет доступа к этому боту.")
        return

    try:
        user_chat = get_user_chat(user_id)
        response = user_chat.send_message(message.text)
        await message.answer(response.text)
    except Exception as e:
        await message.answer(f"Ошибка при запросе к ИИ: {e}")

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="reset", description="Сбросить диалог с ИИ"),
        BotCommand(command="allow", description="[Admin] Добавить ID в белый список"),
        BotCommand(command="deny", description="[Admin] Удалить ID из белого списка"),
        BotCommand(command="whitelist", description="[Admin] Показать белый список"),
    ]
    await bot.set_my_commands(commands)

async def main():
    await set_bot_commands(bot) # <-- Устанавливаем подсказки
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())