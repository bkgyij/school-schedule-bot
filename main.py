#!/usr/bin/env python3
"""
Telegram-бот расписания МБОУ СШ №6 (г. Гуково)
Запуск: python main.py
"""

import subprocess
import sys

def install_dependencies():
    packages = {
        "telegram": "python-telegram-bot",
        "requests": "requests",
    }
    for module_name, pip_name in packages.items():
        try:
            __import__(module_name)
        except ImportError:
            print(f"📦 Устанавливаю {pip_name}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
    print("✅ Все зависимости установлены\n")

install_dependencies()

import re
import os
import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ─── Настройки ───────────────────────────────────────────────────────────────

BOT_TOKEN = "8624847761:AAFZX_g8q3pqgYjM41Qptgx_IB5y_fDfGXg"

SCHEDULE_URL = "https://raspisanie.nikasoft.ru/15312761.html"
CHECK_URL = "https://raspisanie.nikasoft.ru/check/15312761.html"
DATA_BASE_URL = "https://raspisanie.nikasoft.ru/static/public/"

MSK = timezone(timedelta(hours=3))
CHECK_INTERVAL = 60

DATA_DIR = Path("data")
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
STATE_FILE = DATA_DIR / "state.json"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Хранилище ───────────────────────────────────────────────────────────────


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_subscribers() -> set:
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_subscribers(subs: set):
    _ensure_data_dir()
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subs), f)


def add_subscriber(chat_id: int):
    subs = load_subscribers()
    subs.add(chat_id)
    save_subscribers(subs)


def remove_subscriber(chat_id: int):
    subs = load_subscribers()
    subs.discard(chat_id)
    save_subscribers(subs)


def load_last_schedule_id():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f).get("last_schedule_id")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_last_schedule_id(schedule_id: str):
    _ensure_data_dir()
    with open(STATE_FILE, "w") as f:
        json.dump({"last_schedule_id": schedule_id}, f)


# ─── Inline-клавиатуры ──────────────────────────────────────────────────────

MAIN_INLINE = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔄 Последнее обновление", callback_data="check_update")],
    [InlineKeyboardButton("📋 Расписание (сайт)", url=SCHEDULE_URL)],
    [InlineKeyboardButton("ℹ️ О боте", callback_data="about")],
])

ABOUT_INLINE = InlineKeyboardMarkup([
    [InlineKeyboardButton("👤 Создатель: @hawkuy", url="https://t.me/hawkuy")],
    [InlineKeyboardButton("💰 Поддержать проект", url="https://www.donationalerts.com/r/kaktusik_crypa228")],
    [InlineKeyboardButton("🌐 Расписание на сайте", url=SCHEDULE_URL)],
    [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
])

REFRESH_INLINE = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔄 Обновить", callback_data="refresh")],
    [InlineKeyboardButton("🌐 Открыть расписание", url=SCHEDULE_URL)],
    [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
])

# ─── Парсинг ─────────────────────────────────────────────────────────────────


def get_schedule_info():
    resp = requests.get(CHECK_URL, timeout=10)
    resp.raise_for_status()
    schedule_id = resp.text.strip()
    js_url = DATA_BASE_URL + schedule_id
    resp = requests.get(js_url, timeout=10)
    resp.raise_for_status()
    text = resp.text
    date_match = re.search(r'"EXPORT_DATE"\s*:\s*"([^"]+)"', text)
    time_match = re.search(r'"EXPORT_TIME"\s*:\s*"([^"]+)"', text)
    school_match = re.search(r'"SCHOOL_NAME"\s*:\s*"([^"]+)"', text)
    city_match = re.search(r'"CITY_NAME"\s*:\s*"([^"]+)"', text)
    return {
        "export_date": date_match.group(1) if date_match else None,
        "export_time": time_match.group(1) if time_match else None,
        "school_name": school_match.group(1) if school_match else "Школа",
        "city_name": city_match.group(1) if city_match else "",
        "schedule_id": schedule_id,
    }


def format_update_message(info):
    if not info.get("export_date") or not info.get("export_time"):
        return "❌ Не удалось получить информацию об обновлении."
    export_date = info["export_date"]
    export_time_full = info["export_time"]
    export_time_short = export_time_full[:5]
    try:
        dt = datetime.strptime(f"{export_date} {export_time_full}", "%d.%m.%Y %H:%M:%S")
        dt = dt.replace(tzinfo=MSK)
        now = datetime.now(MSK)
        today = now.date()
        export_day = dt.date()
        if export_day == today:
            relative = f"сегодня в {export_time_short}"
        elif export_day == today - timedelta(days=1):
            relative = f"вчера в {export_time_short}"
        else:
            relative = f"{export_date} в {export_time_short}"
    except ValueError:
        relative = f"{export_date} в {export_time_short}"
    school = info.get("school_name", "")
    city = info.get("city_name", "")
    header = f"{school}" + (f" ({city})" if city else "")
    return (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏫  <b>{header}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅  Обновлено <b>{relative}</b>\n\n"
        f"🗓  Дата:  <code>{export_date}</code>\n"
        f"🕐  Время:  <code>{export_time_full}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


START_TEXT = (
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📚  <b>Бот расписания</b>\n"
    "🏫  МБОУ СШ №6 (г. Гуково)\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "👋 Привет! Я помогу тебе следить\n"
    "за обновлениями расписания.\n\n"
    "🔔 Ты <b>подписан</b> на уведомления —\n"
    "я пришлю сообщение, когда\n"
    "расписание обновится.\n\n"
    "👇 Выбери действие:"
)

ABOUT_TEXT = (
    "━━━━━━━━━━━━━━━━━━━━\n"
    "ℹ️  <b>О боте</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "📚 Бот расписания <b>МБОУ СШ №6</b>\n"
    "📍 г. Гуково, Ростовская область\n\n"
    "🔹 Показывает время последнего\n"
    "    обновления расписания\n"
    "🔹 Автоматически уведомляет\n"
    "    при обновлении расписания\n"
    "🔹 Удобные кнопки для навигации\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "👨‍💻 <b>Создатель:</b> @hawkuy\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "Нравится бот? Поддержи\n"
    "разработчика 💙"
)


# ─── Обработчики ─────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_subscriber(update.effective_chat.id)
    await update.message.reply_text(START_TEXT, reply_markup=MAIN_INLINE, parse_mode="HTML")


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_TEXT, reply_markup=ABOUT_INLINE, parse_mode="HTML")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📖  <b>Справка</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>Команды:</b>\n\n"
        "  /start — подписаться\n"
        "  /update — проверить обновление\n"
        "  /stop — отписаться\n"
        "  /help — эта справка\n"
        "  /about — о боте\n\n"
        "🔔 Бот автоматически пришлёт\n"
        "уведомление при обновлении\n"
        "расписания.\n"
        "━━━━━━━━━━━━━━━━━━━━",
        reply_markup=MAIN_INLINE,
        parse_mode="HTML",
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remove_subscriber(update.effective_chat.id)
    await update.message.reply_text(
        "🔕 Ты <b>отписался</b> от уведомлений.\n\n"
        "Чтобы подписаться снова → /start",
        parse_mode="HTML",
    )


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Проверяю...")
    try:
        info = get_schedule_info()
        text = format_update_message(info)
    except Exception as e:
        logger.error("Error: %s", e)
        text = f"❌ Ошибка при получении данных:\n<code>{e}</code>"
    await msg.edit_text(text, reply_markup=REFRESH_INLINE, parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT, reply_markup=MAIN_INLINE, parse_mode="HTML")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "check_update" or data == "refresh":
        await query.answer("⏳ Проверяю...")
        try:
            info = get_schedule_info()
            text = format_update_message(info)
        except Exception as e:
            logger.error("Error: %s", e)
            text = f"❌ Ошибка при получении данных:\n<code>{e}</code>"
        await query.edit_message_text(text, reply_markup=REFRESH_INLINE, parse_mode="HTML")

    elif data == "about":
        await query.answer()
        await query.edit_message_text(ABOUT_TEXT, reply_markup=ABOUT_INLINE, parse_mode="HTML")

    elif data == "back_main":
        await query.answer()
        await query.edit_message_text(START_TEXT, reply_markup=MAIN_INLINE, parse_mode="HTML")


# ─── Фоновая проверка обновлений ────────────────────────────────────────────


async def check_for_updates(app):
    last_id = load_last_schedule_id()
    if not last_id:
        try:
            info = get_schedule_info()
            last_id = info["schedule_id"]
            save_last_schedule_id(last_id)
            logger.info("Начальный schedule_id: %s", last_id)
        except Exception as e:
            logger.error("Ошибка: %s", e)

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            info = get_schedule_info()
            current_id = info["schedule_id"]
            if current_id != last_id:
                last_id = current_id
                save_last_schedule_id(current_id)
                logger.info("Расписание обновлено! ID: %s", current_id)
                text = (
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "🔔  <b>Расписание обновлено!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    + format_update_message(info)
                    + f"\n\n🌐 <a href=\"{SCHEDULE_URL}\">Открыть расписание</a>"
                )
                for chat_id in load_subscribers():
                    try:
                        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                    except Exception as e:
                        logger.warning("Не удалось отправить %s: %s", chat_id, e)
        except Exception as e:
            logger.error("Ошибка проверки: %s", e)


# ─── Запуск ──────────────────────────────────────────────────────────────────


async def post_init(app):
    _ensure_data_dir()
    asyncio.create_task(check_for_updates(app))
    logger.info("Проверка обновлений запущена (каждые %d сек)", CHECK_INTERVAL)


def run_bot():
    print("🤖 Запускаю бота расписания МБОУ СШ №6...")
    print(f"📡 Проверка обновлений каждые {CHECK_INTERVAL} сек")
    print("🛑 Для остановки нажми Ctrl+C\n")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_bot()
