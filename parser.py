import os
import sys
import logging
import asyncio
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import aiosqlite
from dotenv import load_dotenv
import nest_asyncio

nest_asyncio.apply()

# Настройка политики событийного цикла для Windows
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Определение состояний для ConversationHandler
(
    MAIN_MENU,
    FILTER_MENU,
    SET_MIN_PRICE,
    SET_MAX_PRICE,
    SET_ROOMS,
    SET_METRO,
    SET_NEAR_METRO,
    RESET_MENU,
) = range(8)

async def init_db(application):
    async with aiosqlite.connect('user_data.db') as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_filters (
                user_id INTEGER PRIMARY KEY,
                min_price INTEGER,
                max_price INTEGER,
                rooms INTEGER,
                metro TEXT,
                near_metro BOOLEAN
            )
        """)
        await db.commit()

# Функция приветствия
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Добро пожаловать! Используйте меню для навигации.")
    return await show_main_menu(update, context)

# Главное меню
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Подписаться", "Отписаться"],
        ["Установить фильтр", "Сбросить фильтр"],
        ["Показать текущие фильтры"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    return MAIN_MENU

# Меню фильтров
async def show_filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Цена", "Количество комнат"],
        ["Метро", "Близость к метро"],
        ["Назад"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите фильтр для настройки:", reply_markup=reply_markup)
    return FILTER_MENU

# Функции подписки и отписки
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with aiosqlite.connect('user_data.db') as db:
        await db.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
        await db.commit()
    await update.message.reply_text("Вы успешно подписались на уведомления!")
    logging.info(f"Новый подписчик: {chat_id}")
    return MAIN_MENU

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with aiosqlite.connect('user_data.db') as db:
        await db.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        await db.commit()
    await update.message.reply_text("Вы успешно отписались от уведомлений.")
    logging.info(f"Пользователь отписался: {chat_id}")
    return MAIN_MENU

# Установка фильтров
async def set_price_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите минимальную цену в BYN:")
    return SET_MIN_PRICE

async def input_min_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        min_price = int(update.message.text.strip())
        context.user_data['min_price'] = min_price
        await update.message.reply_text("Введите максимальную цену в BYN:")
        return SET_MAX_PRICE
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
        return SET_MIN_PRICE

async def input_max_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        max_price = int(update.message.text.strip())
        min_price = context.user_data.get('min_price')
        chat_id = update.effective_chat.id
        async with aiosqlite.connect('user_data.db') as db:
            await db.execute("""
                INSERT INTO user_filters (user_id, min_price, max_price)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    min_price=?,
                    max_price=?
            """, (chat_id, min_price, max_price, min_price, max_price))
            await db.commit()
        await update.message.reply_text(f"Фильтр цены установлен: {min_price}-{max_price} BYN.")
        return await show_filter_menu(update, context)
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
        return SET_MAX_PRICE

async def set_rooms_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите количество комнат:")
    return SET_ROOMS

async def input_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rooms = int(update.message.text.strip())
        chat_id = update.effective_chat.id
        async with aiosqlite.connect('user_data.db') as db:
            await db.execute("""
                INSERT INTO user_filters (user_id, rooms)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    rooms=?
            """, (chat_id, rooms, rooms))
            await db.commit()
        await update.message.reply_text(f"Фильтр количества комнат установлен: {rooms}")
        return await show_filter_menu(update, context)
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
        return SET_ROOMS

async def set_metro_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите название станции метро:")
    return SET_METRO

async def input_metro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    metro = update.message.text.strip()
    chat_id = update.effective_chat.id
    async with aiosqlite.connect('user_data.db') as db:
        await db.execute("""
            INSERT INTO user_filters (user_id, metro)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                metro=?
        """, (chat_id, metro, metro))
        await db.commit()
    await update.message.reply_text(f"Фильтр по станции метро установлен: {metro}")
    return await show_filter_menu(update, context)

async def set_near_metro_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Рядом с метро", "Не важно"], ["Назад"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Выберите опцию:", reply_markup=reply_markup)
    return SET_NEAR_METRO

async def input_near_metro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    chat_id = update.effective_chat.id
    if choice == "Рядом с метро":
        near_metro = True
    elif choice == "Не важно":
        near_metro = False
    elif choice == "Назад":
        return await show_filter_menu(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите опцию из меню.")
        return SET_NEAR_METRO

    async with aiosqlite.connect('user_data.db') as db:
        await db.execute("""
            INSERT INTO user_filters (user_id, near_metro)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                near_metro=?
        """, (chat_id, near_metro, near_metro))
        await db.commit()
    await update.message.reply_text(f"Фильтр близости к метро установлен: {choice}")
    return await show_filter_menu(update, context)

# Показ текущих фильтров
async def show_current_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with aiosqlite.connect('user_data.db') as db:
        cursor = await db.execute("""
            SELECT min_price, max_price, rooms, metro, near_metro
            FROM user_filters WHERE user_id = ?
        """, (chat_id,))
        filters = await cursor.fetchone()
    if filters:
        min_price, max_price, rooms, metro, near_metro = filters
        message = (
            f"Текущие фильтры:\n"
            f"Минимальная цена: {min_price or 'Не установлена'}\n"
            f"Максимальная цена: {max_price or 'Не установлена'}\n"
            f"Количество комнат: {rooms or 'Не установлено'}\n"
            f"Станция метро: {metro or 'Не установлена'}\n"
            f"Близость к метро: {('Рядом с метро' if near_metro else 'Не важно') if near_metro is not None else 'Не установлена'}"
        )
    else:
        message = "Фильтры не установлены."
    await update.message.reply_text(message)
    return MAIN_MENU

# Меню сброса фильтров
async def show_reset_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Сбросить цену", "Сбросить количество комнат"],
        ["Сбросить метро", "Сбросить близость к метро"],
        ["Сбросить все фильтры", "Назад"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите фильтр для сброса:", reply_markup=reply_markup)
    return RESET_MENU

# Сброс фильтров
async def reset_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    chat_id = update.effective_chat.id
    async with aiosqlite.connect('user_data.db') as db:
        if choice == "Сбросить цену":
            await db.execute("""
                UPDATE user_filters SET min_price = NULL, max_price = NULL WHERE user_id = ?
            """, (chat_id,))
            await update.message.reply_text("Фильтр цены сброшен.")
        elif choice == "Сбросить количество комнат":
            await db.execute("""
                UPDATE user_filters SET rooms = NULL WHERE user_id = ?
            """, (chat_id,))
            await update.message.reply_text("Фильтр количества комнат сброшен.")
        elif choice == "Сбросить метро":
            await db.execute("""
                UPDATE user_filters SET metro = NULL WHERE user_id = ?
            """, (chat_id,))
            await update.message.reply_text("Фильтр по станции метро сброшен.")
        elif choice == "Сбросить близость к метро":
            await db.execute("""
                UPDATE user_filters SET near_metro = NULL WHERE user_id = ?
            """, (chat_id,))
            await update.message.reply_text("Фильтр близости к метро сброшен.")
        elif choice == "Сбросить все фильтры":
            await db.execute("DELETE FROM user_filters WHERE user_id = ?", (chat_id,))
            await update.message.reply_text("Все фильтры сброшены.")
            return await show_main_menu(update, context)
        elif choice == "Назад":
            return await show_main_menu(update, context)
        else:
            await update.message.reply_text("Пожалуйста, выберите опцию из меню.")
            return RESET_MENU
        await db.commit()
    return await show_reset_menu(update, context)

# Асинхронная функция main
async def main():
    load_dotenv()
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

    app = ApplicationBuilder().token(TOKEN).post_init(init_db).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.Regex("^Подписаться$"), subscribe),
                MessageHandler(filters.Regex("^Отписаться$"), unsubscribe),
                MessageHandler(filters.Regex("^Установить фильтр$"), show_filter_menu),
                MessageHandler(filters.Regex("^Сбросить фильтр$"), show_reset_menu),
                MessageHandler(filters.Regex("^Показать текущие фильтры$"), show_current_filters),
            ],
            FILTER_MENU: [
                MessageHandler(filters.Regex("^Цена$"), set_price_filter),
                MessageHandler(filters.Regex("^Количество комнат$"), set_rooms_filter),
                MessageHandler(filters.Regex("^Метро$"), set_metro_filter),
                MessageHandler(filters.Regex("^Близость к метро$"), set_near_metro_filter),
                MessageHandler(filters.Regex("^Назад$"), show_main_menu),
            ],
            SET_MIN_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_min_price)],
            SET_MAX_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_max_price)],
            SET_ROOMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_rooms)],
            SET_METRO: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_metro)],
            SET_NEAR_METRO: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_near_metro)],
            RESET_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, reset_filter)],
        },
        fallbacks=[CommandHandler('start', start)],
    )

    app.add_handler(conv_handler)

    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
