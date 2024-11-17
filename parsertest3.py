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
import requests

# Apply async policy for Windows compatibility
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Configure logging
logging.basicConfig(level=logging.INFO)

class DatabasePool:
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.connection = None

    @classmethod
    async def get_instance(cls, db_path="user_data.db"):
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
                await cls._instance.connect()
            return cls._instance

    async def connect(self):
        if self.connection is None:
            self.connection = await aiosqlite.connect(self.db_path)
            await self.connection.execute("PRAGMA foreign_keys = ON;")  # Включить поддержку внешних ключей

    async def close(self):
        if self.connection:
            await self.connection.close()
            self.connection = None

    async def execute(self, query: str, params=(), fetch: bool = False, fetchall: bool = False):
        cursor = await self.connection.execute(query, params)
        if fetch:
            result = await cursor.fetchone()
        elif fetchall:
            result = await cursor.fetchall()
        else:
            result = None
        await self.connection.commit()
        await cursor.close()
        return result

# Define states for ConversationHandler
(MAIN_MENU, FILTER_MENU, SET_MIN_PRICE, SET_MAX_PRICE, SET_ROOMS, 
 SET_METRO, SET_NEAR_METRO, RESET_MENU) = range(8)

async def init_db():
    db_pool = await DatabasePool.get_instance()  # Получаем экземпляр пула базы данных

    # Выполняем запросы для создания таблиц
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id INTEGER PRIMARY KEY
        )
    """)
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_filters (
            user_id INTEGER PRIMARY KEY,
            min_price INTEGER,
            max_price INTEGER,
            rooms INTEGER,
            metro TEXT,
            near_metro BOOLEAN
        )
    """)
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_listings (
            user_id INTEGER,
            title TEXT,
            price TEXT,
            metro TEXT,
            link TEXT,
            ad_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, link)
        )
    """)

    logging.info("Database initialized.")
    
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Используй меню для навигации.")
    return await show_main_menu(update, context)

def format_price(price):
    try:
        price_number = int(''.join(filter(str.isdigit, price)))
        rubles = price_number // 100
        kopecks = price_number % 100
        return f"{rubles:,},{kopecks:02}".replace(',', ' ').replace('.', ',')
    except ValueError:
        return price

async def execute_query(query, params=(), fetch=False, fetchall=False):
    db_pool = await DatabasePool.get_instance()
    return await db_pool.execute(query, params, fetch=fetch, fetchall=fetchall)

        
def filter_listings(listings, **criteria):
    def matches_criteria(listing):
        try:
            price = int(''.join(filter(str.isdigit, listing.get('price', '0'))))
            if criteria.get('min_price') and price < criteria['min_price'] * 100:
                return False
            if criteria.get('max_price') and price > criteria['max_price'] * 100:
                return False
            if criteria.get('rooms') and str(criteria['rooms']) not in listing.get('title', ''):
                return False
            if criteria.get('metro') and criteria['metro'].lower() not in listing.get('metro', '').lower():
                return False
        except Exception as e:
            logging.warning(f"Ошибка фильтрации: {e}, объявление: {listing}")
            return False
        return True

    return [listing for listing in listings if matches_criteria(listing)]

async def fetch_and_send_listings(user_id, context):
    listings = fetch_kufar_data_api(city='minsk')
    if not listings:
        logging.error("Failed to fetch listings.")
        return

    filters = await execute_query("SELECT min_price, max_price, rooms, metro FROM user_filters WHERE user_id = ?", (user_id,), fetch=True)
    if filters:
        min_price, max_price, rooms, metro = filters
        listings = filter_listings(listings, min_price=min_price, max_price=max_price, rooms=rooms, metro=metro)

    await check_and_save_listings(user_id, listings, context)

async def check_and_save_listings(user_id, listings, context):
    existing_ads = await execute_query("SELECT ad_id FROM user_listings WHERE user_id = ?", (user_id,), fetchall=True)
    existing_ad_ids = {row[0] for row in existing_ads}
    new_listings = [listing for listing in listings if listing['ad_id'] not in existing_ad_ids]

    if new_listings:
        await execute_query("""
            INSERT INTO user_listings (user_id, title, price, metro, link, ad_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [(user_id, l['title'], l['price'], l['metro'], l['link'], l['ad_id']) for l in new_listings])

        for listing in new_listings:
            message = (
                f"Новое объявление:\n"
                f"Название: {listing['title']}\n"
                f"Цена: {format_price(listing['price'])} BYN\n"
                f"Метро: {listing['metro']}\n"
                f"Ссылка: {listing['link']}\n"
            )
            await context.bot.send_message(chat_id=user_id, text=message)
    else:
        logging.info(f"No new listings for user {user_id}.")

# Функция для получения данных через API Kufar
def fetch_kufar_data_api(city='minsk', category='kvartiru-dolgosrochno', filter_type='bez-posrednikov'):
    url = "https://api.kufar.by/search-api/v2/search/rendered-paginated"
    params = {
        "lang": "ru",
        "size": 30,
        "cat": 1010,
        "cur": "BYR",
        "gtsy": f"country-belarus~province-minsk~locality-{city}",
        "rnt": 1,
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Referer': 'https://re.kufar.by/',
    }
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        return [
            {
                'ad_id': ad.get('ad_id', 'Нет ID'),
                'title': ad.get('subject', 'Нет заголовка'),
                'price': ad.get('price_byn', '0'),
                'metro': ad.get('location', {}).get('metro', 'Метро не указано'),
                'link': ad.get('ad_link', 'Ссылка отсутствует'),
            }
            for ad in data.get('ads', [])
        ]
    except requests.RequestException as e:
        logging.error(f"Ошибка при запросе: {e}")
        return []

from telegram.ext import Application, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    logging.info("Запуск регулярной задачи 'scheduled_check'.")

    # Очищаем старые объявления
    await execute_query("DELETE FROM user_listings WHERE timestamp < datetime('now', '-30 days')")
    logging.info("Удалены объявления старше 30 дней.")

    # Получаем список пользователей
    users = await execute_query("SELECT chat_id FROM subscribers", fetchall=True)
    for (user_id,) in users:
        await fetch_and_send_listings(user_id, context)

    logging.info("Регулярная задача 'scheduled_check' завершена.")

# Generic function for displaying a menu with a keyboard
async def show_menu(update: Update, text: str, options: list[list[str]], next_state: int) -> int:
    reply_markup = ReplyKeyboardMarkup(options, resize_keyboard=True)
    await update.message.reply_text(text, reply_markup=reply_markup)
    return next_state


# Example usage of show_menu function for main and filter menus
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    options = [["Подписаться", "Отписаться"], ["Установить фильтр", "Сбросить фильтр"], ["Показать текущие фильтры"]]
    return await show_menu(update, "Choose an action:", options, MAIN_MENU)

async def show_filter_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    options = [["Цена", "Комнаты"], ["Метро", "Близость к метро"], ["Назад"]]
    return await show_menu(update, "Choose a filter to set:", options, FILTER_MENU)

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        # Работа с базой данных через пул соединений
        db_pool = await DatabasePool.get_instance()
        await db_pool.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))

        # Подтверждение подписки
        await update.message.reply_text("Вы успешно подписались на уведомления!")
        logging.info(f"Новый подписчик: {chat_id}")
    except Exception as e:
        logging.error(f"Ошибка подписки для пользователя {chat_id}: {e}")
        await update.message.reply_text("Произошла ошибка при подписке.")
    return MAIN_MENU

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        # Работа с базой данных через пул соединений
        db_pool = await DatabasePool.get_instance()
        await db_pool.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))

        # Подтверждение отписки
        await update.message.reply_text("Вы успешно отписались от уведомлений.")
        logging.info(f"Пользователь отписался: {chat_id}")
    except Exception as e:
        logging.error(f"Ошибка отписки для пользователя {chat_id}: {e}")
        await update.message.reply_text("Произошла ошибка при отписке.")
    return MAIN_MENU


# Remaining code for filters, error handling, and improvements follows this refactored structure.

# Установка фильтров
async def set_price_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите минимальную цену в BYN:")
    return SET_MIN_PRICE

async def input_min_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка команды "Назад"
    if await check_back_command(update, context, show_filter_menu):
        return
    try:
        min_price = int(update.message.text.strip())
        context.user_data['min_price'] = min_price
        await update.message.reply_text("Введите максимальную цену в BYN:")
        return SET_MAX_PRICE
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число.")
        return SET_MIN_PRICE

async def input_max_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка команды "Назад"
    if await check_back_command(update, context, show_filter_menu):
        return

    try:
        # Получаем максимальную цену из сообщения
        max_price = int(update.message.text.strip())
        min_price = context.user_data.get('min_price')

        # Проверяем, что минимальная цена не больше максимальной
        if min_price and max_price and min_price > max_price:
            await update.message.reply_text("Минимальная цена не может быть больше максимальной. Попробуйте снова.")
            return SET_MIN_PRICE  # Возвращаем пользователя к вводу минимальной цены

        # Получаем ID пользователя
        chat_id = update.effective_chat.id

        # Работа с базой данных через пул соединений
        db_pool = await DatabasePool.get_instance()
        await db_pool.execute("""
            INSERT INTO user_filters (user_id, min_price, max_price)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                min_price=?,
                max_price=?
        """, (chat_id, min_price, max_price, min_price, max_price))

        # Подтверждаем установку фильтра
        await update.message.reply_text(f"Фильтр цены установлен: {min_price}-{max_price} BYN.")
        return await show_filter_menu(update, context)

    except ValueError:
        # Обработка некорректного ввода
        await update.message.reply_text("Пожалуйста, введите корректное число.")
        return SET_MAX_PRICE



async def set_rooms_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите количество комнат:")
    return SET_ROOMS

async def input_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка команды "Назад"
    if await check_back_command(update, context, show_filter_menu):
        return

    try:
        # Получаем количество комнат и ID чата
        rooms = int(update.message.text.strip())
        chat_id = update.effective_chat.id

        # Работа с базой данных через пул соединений
        db_pool = await DatabasePool.get_instance()
        await db_pool.execute("""
            INSERT INTO user_filters (user_id, rooms)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                rooms=?
        """, (chat_id, rooms, rooms))

        # Подтверждаем установку фильтра
        await update.message.reply_text(f"Фильтр количества комнат установлен: {rooms}")
        return await show_filter_menu(update, context)

    except ValueError:
        # Обработка некорректного ввода
        await update.message.reply_text("Пожалуйста, введите корректное число.")
        return SET_ROOMS


async def set_metro_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите название станции метро:")
    return SET_METRO

async def input_metro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка команды "Назад"
    if await check_back_command(update, context, show_filter_menu):
        return

    # Получение текста сообщения и ID пользователя
    metro = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Работа с базой данных через пул соединений
    db_pool = await DatabasePool.get_instance()
    await db_pool.execute("""
        INSERT INTO user_filters (user_id, metro)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            metro=?
    """, (chat_id, metro, metro))

    # Подтверждаем установку фильтра
    await update.message.reply_text(f"Фильтр по станции метро установлен: {metro}")
    return await show_filter_menu(update, context)


async def set_near_metro_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Рядом с метро", "Не важно"], ["Назад"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Выберите опцию:", reply_markup=reply_markup)
    return SET_NEAR_METRO

async def input_near_metro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка команды "Назад"
    if await check_back_command(update, context, show_filter_menu):
        return

    choice = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Определяем значение фильтра на основе выбора пользователя
    if choice == "Рядом с метро":
        near_metro = True
    elif choice == "Не важно":
        near_metro = False
    else:
        await update.message.reply_text("Пожалуйста, выберите опцию из меню.")
        return SET_NEAR_METRO

    # Работа с базой данных через пул соединений
    db_pool = await DatabasePool.get_instance()
    await db_pool.execute("""
        INSERT INTO user_filters (user_id, near_metro)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            near_metro=?
    """, (chat_id, near_metro, near_metro))

    # Подтверждаем установку фильтра
    await update.message.reply_text(f"Фильтр близости к метро установлен: {'Рядом с метро' if near_metro else 'Не важно'}")
    return await show_filter_menu(update, context)

# Показ текущих фильтров
async def show_current_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    db_pool = await DatabasePool.get_instance()  # Получаем экземпляр пула базы данных

    # Выполняем запрос на выборку фильтров
    filters = await db_pool.execute("""
        SELECT min_price, max_price, rooms, metro, near_metro
        FROM user_filters WHERE user_id = ?
    """, (chat_id,), fetch=True)

    # Формируем сообщение на основе полученных фильтров
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

    # Отправляем сообщение пользователю
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

    db_pool = await DatabasePool.get_instance()  # Получаем экземпляр пула базы данных

    if choice == "Сбросить цену":
        await db_pool.execute("""
            UPDATE user_filters SET min_price = NULL, max_price = NULL WHERE user_id = ?
        """, (chat_id,))
        await update.message.reply_text("Фильтр цены сброшен.")
    elif choice == "Сбросить количество комнат":
        await db_pool.execute("""
            UPDATE user_filters SET rooms = NULL WHERE user_id = ?
        """, (chat_id,))
        await update.message.reply_text("Фильтр количества комнат сброшен.")
    elif choice == "Сбросить метро":
        await db_pool.execute("""
            UPDATE user_filters SET metro = NULL WHERE user_id = ?
        """, (chat_id,))
        await update.message.reply_text("Фильтр по станции метро сброшен.")
    elif choice == "Сбросить близость к метро":
        await db_pool.execute("""
            UPDATE user_filters SET near_metro = NULL WHERE user_id = ?
        """, (chat_id,))
        await update.message.reply_text("Фильтр близости к метро сброшен.")
    elif choice == "Сбросить все фильтры":
        await db_pool.execute("DELETE FROM user_filters WHERE user_id = ?", (chat_id,))
        await update.message.reply_text("Все фильтры сброшены.")
        return await show_main_menu(update, context)
    elif choice == "Назад":
        return await show_main_menu(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите опцию из меню.")
        return RESET_MENU

    return await show_reset_menu(update, context)

async def check_back_command(update: Update, context: ContextTypes.DEFAULT_TYPE, previous_menu_func):
    """Проверяет, выбрал ли пользователь команду 'Назад'.
       Если выбрано 'Назад', возвращает пользователя в предыдущее меню.
       
       Параметры:
       - update: объект Update от Telegram.
       - context: объект Context от Telegram.
       - previous_menu_func: функция для возврата в предыдущее меню.
       
       Возвращает:
       - True, если выбрано 'Назад' и выполнен возврат.
       - False, если выбрана не команда 'Назад'.
    """
    if update.message.text.strip() == "Назад":
        await previous_menu_func(update, context)
        return True
    return False


async def main():
    load_dotenv()
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

    # Инициализация пула базы данных
    db_pool = await DatabasePool.get_instance()

    # Инициализация базы данных
    await init_db()

    # Создаем приложение
    app = ApplicationBuilder().token(TOKEN).build()

    # Обработчик состояний через ConversationHandler
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

    # Настраиваем планировщик
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_check, 'interval', seconds=int(os.getenv('CHECK_INTERVAL', 60)), args=[app])
    scheduler.start()

    # Запускаем приложение
    try:
        await app.run_polling()
    finally:
        await db_pool.close()
