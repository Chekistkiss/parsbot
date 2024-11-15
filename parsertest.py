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
from bs4 import BeautifulSoup

# Apply async policy for Windows compatibility
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Configure logging
logging.basicConfig(level=logging.INFO)

# Define states for ConversationHandler
(MAIN_MENU, FILTER_MENU, SET_MIN_PRICE, SET_MAX_PRICE, SET_ROOMS, 
 SET_METRO, SET_NEAR_METRO, RESET_MENU) = range(8)

async def init_db():
        async with aiosqlite.connect('user_data.db') as db:
            # Таблица для подписчиков
            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY
                )
            """)
            
            # Таблица для фильтров пользователей
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
            
            # Таблица для хранения объявлений, чтобы отслеживать последние 6 объявлений
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_listings (
                    user_id INTEGER,
                    title TEXT,
                    price TEXT,
                    metro TEXT,
                    link TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, link)
                )
            """)
            
            await db.commit()
            logging.info("Database initialized.")
            
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use the menu to navigate.")
    # Add any other initialization or setup code here
    return await show_main_menu(update, context)


# Функция для получения данных с сайта Kufar
def fetch_kufar_data(city='minsk', category='kvartiru-dolgosrochno', filter_type='bez-posrednikov'):
    url = f'https://re.kufar.by/l/{city}/snyat/{category}/{filter_type}'
    cookies = {
        'lang': 'ru',
        'rl_page_init_referrer': 'RudderEncrypt%3AU2FsdGVkX1%2FH2seeI7%2Fq1wqbbuOeuJ3HY8LdlE3NJTP4gpKttw4qQr09YjQv%2BLEq',
    'rl_page_init_referring_domain': 'RudderEncrypt%3AU2FsdGVkX1%2FSPetx6YjG04R0qxtHY8J9XF4u%2FCQW1dE%3D',
    'fullscreen_cookie': '1',
    'kufar-test-variant-booking-search': '0',
    'web_push_banner_realty': '3',
    'kuf_SA_compare-button': '1',
    'kuf_agr': '{%22advertisements%22:true%2C%22advertisements-non-personalized%22:false%2C%22statistic%22:true%2C%22mindbox%22:true}',
    '_gcl_au': '1.1.902519878.1730451842',
    '_ym_uid': '1730451853158144029',
    '_ym_d': '1730451853',
    'tmr_lvid': 'a3a3930bd8f4af7a36bc7c105b965a24',
    'tmr_lvidTS': '1730451850548',
    '_ga': 'GA1.3.2138523172.1730451850',
    '_tt_enable_cookie': '1',
    '_ttp': '4At6uLewLHdeggidTQfbBkvmI8Y',
    '_fbp': 'fb.1.1730451852620.507304602837468435',
    'web_push_banner_listings': '3',
    '__ddg1_': 'KkObY1Yeec2uADGntUNT',
    'mindboxDeviceUUID': '1116e8f6-a258-477b-af66-e5ee042e0897',
    'directCrm-session': '%7B%22deviceGuid%22%3A%221116e8f6-a258-477b-af66-e5ee042e0897%22%7D',
    '_ga_D1TYH5F4Z4': 'GS1.1.1730564836.1.1.1730564867.29.0.0',
    '_ga_QJWHL6VBRT': 'GS1.1.1730564828.1.1.1730564869.19.0.0',
    '_hjSessionUser_1751529': 'eyJpZCI6IjlmMTNjZDc1LTgwZTYtNTYxOC1hMDcyLTg0YzhjMGUzMDM0YSIsImNyZWF0ZWQiOjE3MzA0NTE4NTMzNzQsImV4aXN0aW5nIjp0cnVlfQ==',
    'kuf_SA_subscribe_user_attention': '1',
    'default_ca': '7',
    'default_ya': '240',
    'kufar-test-variant-recs-for-paid-pro-ads': 'f0ddf860-6e9f-4c07-b8d5-c957e52ab2a0__1',
    '__eoi': 'ID=a29bd04e72b443e3:T=1730991667:RT=1730991667:S=AA-AfjYasl_AhnY7PYR-uKgvxPSr',
    '_ga_QTFZM0D0BE': 'GS1.1.1730991657.6.1.1730991964.60.0.0',
    'kufar_cart_id': '69a458ec-b449-4ecc-90f0-85cb1b9161d4',
    '_gid': 'GA1.2.790015324.1731174007',
    '_ga': 'GA1.1.2138523172.1730451850',
    '_gid': 'GA1.3.790015324.1731174007',
    '_ym_isad': '2',
    '_hjSession_1751529': 'eyJpZCI6ImQwMWVhZWY0LTEyOTQtNDllNy05OGNhLWJhOWEzYzNiMjI1ZSIsImMiOjE3MzExNzQwMzE2MjIsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjowLCJzcCI6MH0=',
    'domain_sid': 'J4HwtW05oF7uzL65FvO1K%3A1731174038867',
    '_ym_visorc': 'b',
    'rl_user_id': 'RudderEncrypt%3AU2FsdGVkX18GDB7PtM0eF9ijmKSLeKF0UHAhpcqgJRU%3D',
    'rl_trait': 'RudderEncrypt%3AU2FsdGVkX18dVVsfMGQrGW5XFV4M82LlB2MOkChIqIU%3D',
    'rl_group_id': 'RudderEncrypt%3AU2FsdGVkX19ifYHwQZ7%2FWC4KJwJnjC%2FWEDVA71L2IH4%3D',
    'rl_group_trait': 'RudderEncrypt%3AU2FsdGVkX19pTuxDGJRylzDHPcZ2kAMZDAXEsTl6ZRk%3D',
    'rl_anonymous_id': 'RudderEncrypt%3AU2FsdGVkX1%2BzyDlEsBT2Xxvwsgabh6dK%2Fa7aywPHqBdUP2MtIEwmpUgMxv2XNgmvS4L8%2FQ9DgN6%2BLC%2BJYtj3Lg%3D%3D',
    'rl_session': 'RudderEncrypt%3AU2FsdGVkX1%2B6dzRL1q7e2ogo7U5MUoHTTMuJOasIdT7OBZubasEv0eX1BrkuHjQWXFYBYILK97GzVJrTb5lq3Bitb1n2c5Cy7vUcBBvLDHleAXJVK%2BrqUw4Q31rq9%2BnuZNjwUceOn0RvClRfYSwncg%3D%3D',
    '_ga_SW9X2V65F0': 'GS1.1.1731174025.12.1.1731174164.6.0.0',
    '_ga_ESH3WRCK3J': 'GS1.1.1731174024.14.1.1731174166.4.0.0',
    'tmr_detect': '0%7C1731174191095',
}
        
    params = {'cur': 'BYR'}
    headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'ru,en;q=0.9,en-GB;q=0.8,en-US;q=0.7',
    'cache-control': 'max-age=0',
    # 'cookie': 'lang=ru; rl_page_init_referrer=RudderEncrypt%3AU2FsdGVkX1%2FH2seeI7%2Fq1wqbbuOeuJ3HY8LdlE3NJTP4gpKttw4qQr09YjQv%2BLEq; rl_page_init_referring_domain=RudderEncrypt%3AU2FsdGVkX1%2FSPetx6YjG04R0qxtHY8J9XF4u%2FCQW1dE%3D; fullscreen_cookie=1; kufar-test-variant-booking-search=0; web_push_banner_realty=3; kuf_SA_compare-button=1; kuf_agr={%22advertisements%22:true%2C%22advertisements-non-personalized%22:false%2C%22statistic%22:true%2C%22mindbox%22:true}; _gcl_au=1.1.902519878.1730451842; _ym_uid=1730451853158144029; _ym_d=1730451853; tmr_lvid=a3a3930bd8f4af7a36bc7c105b965a24; tmr_lvidTS=1730451850548; _ga=GA1.3.2138523172.1730451850; _tt_enable_cookie=1; _ttp=4At6uLewLHdeggidTQfbBkvmI8Y; _fbp=fb.1.1730451852620.507304602837468435; web_push_banner_listings=3; __ddg1_=KkObY1Yeec2uADGntUNT; mindboxDeviceUUID=1116e8f6-a258-477b-af66-e5ee042e0897; directCrm-session=%7B%22deviceGuid%22%3A%221116e8f6-a258-477b-af66-e5ee042e0897%22%7D; _ga_D1TYH5F4Z4=GS1.1.1730564836.1.1.1730564867.29.0.0; _ga_QJWHL6VBRT=GS1.1.1730564828.1.1.1730564869.19.0.0; _hjSessionUser_1751529=eyJpZCI6IjlmMTNjZDc1LTgwZTYtNTYxOC1hMDcyLTg0YzhjMGUzMDM0YSIsImNyZWF0ZWQiOjE3MzA0NTE4NTMzNzQsImV4aXN0aW5nIjp0cnVlfQ==; kuf_SA_subscribe_user_attention=1; default_ca=7; default_ya=240; kufar-test-variant-recs-for-paid-pro-ads=f0ddf860-6e9f-4c07-b8d5-c957e52ab2a0__1; __eoi=ID=a29bd04e72b443e3:T=1730991667:RT=1730991667:S=AA-AfjYasl_AhnY7PYR-uKgvxPSr; _ga_QTFZM0D0BE=GS1.1.1730991657.6.1.1730991964.60.0.0; kufar_cart_id=69a458ec-b449-4ecc-90f0-85cb1b9161d4; _gid=GA1.2.790015324.1731174007; _ga=GA1.1.2138523172.1730451850; _gid=GA1.3.790015324.1731174007; _ym_isad=2; _hjSession_1751529=eyJpZCI6ImQwMWVhZWY0LTEyOTQtNDllNy05OGNhLWJhOWEzYzNiMjI1ZSIsImMiOjE3MzExNzQwMzE2MjIsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjowLCJzcCI6MH0=; domain_sid=J4HwtW05oF7uzL65FvO1K%3A1731174038867; _ym_visorc=b; rl_user_id=RudderEncrypt%3AU2FsdGVkX18GDB7PtM0eF9ijmKSLeKF0UHAhpcqgJRU%3D; rl_trait=RudderEncrypt%3AU2FsdGVkX18dVVsfMGQrGW5XFV4M82LlB2MOkChIqIU%3D; rl_group_id=RudderEncrypt%3AU2FsdGVkX19ifYHwQZ7%2FWC4KJwJnjC%2FWEDVA71L2IH4%3D; rl_group_trait=RudderEncrypt%3AU2FsdGVkX19pTuxDGJRylzDHPcZ2kAMZDAXEsTl6ZRk%3D; rl_anonymous_id=RudderEncrypt%3AU2FsdGVkX1%2BzyDlEsBT2Xxvwsgabh6dK%2Fa7aywPHqBdUP2MtIEwmpUgMxv2XNgmvS4L8%2FQ9DgN6%2BLC%2BJYtj3Lg%3D%3D; rl_session=RudderEncrypt%3AU2FsdGVkX1%2B6dzRL1q7e2ogo7U5MUoHTTMuJOasIdT7OBZubasEv0eX1BrkuHjQWXFYBYILK97GzVJrTb5lq3Bitb1n2c5Cy7vUcBBvLDHleAXJVK%2BrqUw4Q31rq9%2BnuZNjwUceOn0RvClRfYSwncg%3D%3D; _ga_SW9X2V65F0=GS1.1.1731174025.12.1.1731174164.6.0.0; _ga_ESH3WRCK3J=GS1.1.1731174024.14.1.1731174166.4.0.0; tmr_detect=0%7C1731174191095',
    'priority': 'u=0, i',
    'sec-ch-ua': '"Chromium";v="130", "Microsoft Edge";v="130", "Not?A_Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'same-origin',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0',
}

    try:
        response = requests.get(url, params=params, cookies=cookies, headers=headers)
        if response.status_code == 200:
            return BeautifulSoup(response.text, 'html.parser')
        else:
            logging.error(f"Не удалось получить данные: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка запроса: {e}")
        return None

# Основная логика парсера
soup = fetch_kufar_data(city='minsk', category='kvartiru-dolgosrochno', filter_type='bez-posrednikov')

if soup:
    listings = soup.select('section div.styles_wrapper__Q06m9')  # Основной CSS-класс для списка объявлений
    for listing in listings:
        # Извлечение ссылки на объявление
        link_tag = listing.select_one('a.styles_wrapper__Q06m9')
        link = f"https://re.kufar.by{link_tag['href']}" if link_tag else 'Ссылка не указана'
        
        # Извлечение цены
        price_tag = listing.select_one('span.styles_price__byr__ILsfd')
        price = price_tag.get_text(strip=True) if price_tag else 'Цена не указана'
        
        # Извлечение названия или параметров объявления
        title_tag = listing.select_one('div.styles_parameters__7zKlL')
        title = title_tag.get_text(strip=True) if title_tag else 'Информация о комнатах и площади не указана'
        
        # Извлечение информации о метро
        metro_tag = listing.select_one('span.styles_wrapper__HKXX4')
        metro = metro_tag.get_text(strip=True) if metro_tag else 'Станция метро не указана'
        
        print(f"Заголовок: {title}, Цена: {price}, Метро: {metro}, Ссылка: {link}")
else:
    print("Не удалось получить данные.")


def parse_listings(html):
    soup = BeautifulSoup(html, 'html.parser')
    listings = []
    items = soup.select('section div.styles_wrapper__Q06m9')
    for item in items:
        link_tag = item.select_one('a.styles_wrapper__Q06m9')
        link = link_tag['href'] if link_tag else None
        price_tag = item.select_one('span.styles_price__byr__ILsfd')
        price = price_tag.get_text(strip=True) if price_tag else 'Цена не указана'
        title_tag = item.select_one('div.styles_parameters__7zKlL')
        title = title_tag.get_text(strip=True) if title_tag else 'Информация о комнатах и площади не указана'
        metro_tag = item.select_one('span.styles_wrapper__HKXX4')
        metro = metro_tag.get_text(strip=True) if metro_tag else 'Станция метро не указана'
        listings.append({
            'title': title,
            'price': price,
            'metro': metro,
            'link': f"https://re.kufar.by{link}" if link else 'Ссылка не указана'
        })
    return listings

async def check_and_save_listings(user_id, listings, context):
    async with aiosqlite.connect('user_data.db') as db:
        # Получаем ссылки на все объявления пользователя, которые уже в базе
        cursor = await db.execute("""
            SELECT link FROM user_listings WHERE user_id = ?
        """, (user_id,))
        existing_links = {row[0] for row in await cursor.fetchall()}

        # Отфильтровываем новые объявления
        new_listings = [listing for listing in listings if listing['link'] not in existing_links]
        logging.info(f"Новые объявления для сохранения: {len(new_listings)}")  # Логирование

        # Добавляем новые объявления в базу одним запросом
        await db.executemany("""
            INSERT INTO user_listings (user_id, title, price, metro, link)
            VALUES (?, ?, ?, ?, ?)
        """, [(user_id, listing['title'], listing['price'], listing['metro'], listing['link']) for listing in new_listings])

        # Ограничиваем до 10 последних объявлений
        await db.execute("""
            DELETE FROM user_listings WHERE user_id = ? 
            AND rowid NOT IN (
                SELECT rowid FROM user_listings 
                WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10
            )
        """, (user_id, user_id))
        
        await db.commit()

        # Отправляем новые объявления пользователю
        for listing in new_listings:
            message = (
                f"Новое объявление:\n"
                f"Название: {listing['title']}\n"
                f"Цена: {listing['price']}\n"
                f"Метро: {listing['metro']}\n"
                f"Ссылка: {listing['link']}\n"
            )
            await context.bot.send_message(chat_id=user_id, text=message)

            
def filter_listings(listings, min_price=None, max_price=None, rooms=None, metro=None):
    filtered = []

    for listing in listings:
        # Пример фильтрации по цене
        try:
            price = int(listing['price'].replace(' ', '').replace('р.', ''))
        except ValueError:
            # Пропускаем объявление, если не удается преобразовать цену в число
            logging.warning(f"Не удалось преобразовать цену '{listing['price']}' в число для объявления: {listing}")
            continue

        if min_price and price < min_price:
            continue
        if max_price and price > max_price:
            continue

        # Фильтрация по количеству комнат
        if rooms and rooms not in listing['title']:
            continue

        # Фильтрация по станции метро
        if metro and metro not in listing['metro']:
            continue

        filtered.append(listing)

    return filtered

async def fetch_and_send_listings(user_id, context):
    html = fetch_kufar_data(city='minsk', category='kvartiru-dolgosrochno', filter_type='bez-posrednikov')
    if not html:
        logging.error("Ошибка загрузки страницы")
        return
    listings = parse_listings(html)
    
    # Получение и применение фильтров пользователя
    async with aiosqlite.connect('user_data.db') as db:
        cursor = await db.execute("SELECT min_price, max_price, rooms, metro FROM user_filters WHERE user_id = ?", (user_id,))
        filters = await cursor.fetchone()
    if filters:
        min_price, max_price, rooms, metro = filters
        listings = filter_listings(listings, min_price, max_price, rooms, metro)
    
    # Сохранение и отправка новых объявлений
    await check_and_save_listings(user_id, listings, context)

from telegram.ext import Application, CallbackContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler

async def scheduled_check(context: CallbackContext):
    async with aiosqlite.connect('user_data.db') as db:
        cursor = await db.execute("SELECT chat_id FROM subscribers")  # Изменено с user_id на chat_id
        users = await cursor.fetchall()
        
    for (user_id,) in users:
        await fetch_and_send_listings(user_id, context)

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

# Subscribe/unsubscribe functions with error handling
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    try:
        async with aiosqlite.connect('user_data.db') as db:
            await db.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
            await db.commit()
        await update.message.reply_text("Successfully subscribed to notifications!")
        logging.info(f"New subscriber: {chat_id}")
    except Exception as e:
        logging.error(f"Failed to subscribe user {chat_id}: {e}")
        await update.message.reply_text("An error occurred while subscribing.")
    return MAIN_MENU

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with aiosqlite.connect('user_data.db') as db:
        await db.execute("DELETE FROM subscribers WHERE chat_id = ?", (chat_id,))
        await db.commit()
    await update.message.reply_text("Вы успешно отписались от уведомлений.")
    logging.info(f"Пользователь отписался: {chat_id}")
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
    # Проверка команды "Назад"
    if await check_back_command(update, context, show_filter_menu):
        return
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
    # Проверка команды "Назад"
    if await check_back_command(update, context, show_filter_menu):
        return
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
    # Проверка команды "Назад"
    if await check_back_command(update, context, show_filter_menu):
        return
    choice = update.message.text.strip()
    chat_id = update.effective_chat.id
    if choice == "Рядом с метро":
        near_metro = True
    elif choice == "Не важно":
        near_metro = False
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
    await update.message.reply_text(f"Фильтр близости к метро установлен: {'Рядом с метро' if near_metro else 'Не важно'}")
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


# Асинхронная функция main
async def main():
    load_dotenv()
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    # Инициализация базы данных
    await init_db()  # Теперь init_db вызывается отдельно


    app = ApplicationBuilder().token(TOKEN).build()

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
    application = Application.builder().token(TOKEN).build()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_check, 'interval', minutes=5, args=[application])
    scheduler.start()
   
    await app.run_polling()

if __name__ == '__main__':
    nest_asyncio.apply()
    asyncio.get_event_loop().run_until_complete(main())

