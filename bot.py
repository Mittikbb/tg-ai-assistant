import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from google import genai
from dotenv import load_dotenv

# Загружаем ключи из скрытого файла .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MY_TELEGRAM_ID = int(os.getenv("MY_TELEGRAM_ID", 0))

# Проверка, что ключи на месте
if not BOT_TOKEN or not GEMINI_API_KEY or not MY_TELEGRAM_ID:
    print("❌ Ошибка: Проверь файл .env! Не найдены BOT_TOKEN, GEMINI_API_KEY или MY_TELEGRAM_ID.")
    exit(1)

# Настройка логов
logging.basicConfig(level=logging.INFO)

# Инициализация бота и клиента Gemini
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Создаем чат с историей (памятью) для Gemini
ai_chat = ai_client.chats.create(model="gemini-2.5-flash")

# Глобальный статус (по умолчанию - Обычный)
USER_STATUS = "default"

# --- Проверка прав (Белый список) ---
def is_admin(user_id: int) -> bool:
    return user_id == MY_TELEGRAM_ID


# --- Обработчик команды /start ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if not is_admin(message.from_user.id):
        return  # Игнорируем посторонних

    await message.answer(
        "👋 **ИИ-Ассистент запущен и помнит контекст!**\n\n"
        f"Текущий статус: `{USER_STATUS}`\n"
        "Пиши сюда — я на связи."
    )


# --- Обработчик команды /status ---
@dp.message(Command(commands=["status"]))
async def cmd_status(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    global USER_STATUS
    args = message.text.split(maxsplit=1)

    if len(args) > 1:
        new_status = args[1].lower()
        if new_status in ["default", "ignore", "sleep", "busy", "briefing"]:
            USER_STATUS = new_status
            await message.answer(f"✅ Статус успешно изменён на: `{USER_STATUS}`")
        else:
            await message.answer("❌ Неизвестный статус. Доступные: `default`, `ignore`, `sleep`, `busy`, `briefing`")
    else:
        await message.answer(f"Текущий статус: `{USER_STATUS}`")


# --- Основной обработчик сообщений с памятью ---
@dp.message()
async def handle_message(message: types.Message):
    if not is_admin(message.from_user.id):
        return

    # Отправляем в Telegram статус "печатает..."
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        # Метод send_message автоматически сохраняет предыдущий контекст диалога
        response = ai_chat.send_message(message.text)
        await message.answer(response.text, parse_mode="Markdown")

    except Exception as e:
        print(f"Ошибка: {e}")
        await message.answer("Произошла ошибка при обращении к ИИ.")


# --- Точка входа ---
async def main():
    print("Бот запущен с памятью!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())