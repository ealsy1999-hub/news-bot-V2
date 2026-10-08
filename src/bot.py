"""Telegram-бот News Bot: двуязычный дайджест новостей и сводка Мосбиржи."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import time as dtime
from datetime import timedelta, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import config
import llm
import market
import rss_parser
import summarizer
from formatting import esc, headline_block, pack, story_block

log = logging.getLogger(__name__)
MSK = timezone(timedelta(hours=3))

GROUP_TITLES = {"ru": "🇷🇺 Россия", "world": "🌍 Мир", "all": "🌐 Полный дайджест"}
_CACHE: dict[str, tuple[float, list[str]]] = {}


# ---------- меню ----------

def main_menu() -> InlineKeyboardMarkup:
    """Главное меню."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Россия", callback_data="digest_ru"),
         InlineKeyboardButton("🌍 Мир", callback_data="digest_world")],
        [InlineKeyboardButton("🌐 Всё сразу", callback_data="digest_all"),
         InlineKeyboardButton("📊 Мосбиржа", callback_data="market")],
        [InlineKeyboardButton("ℹ️ О боте", callback_data="about")],
    ])


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("← В меню", callback_data="menu")]])


# ---------- отправка ----------

async def send(bot, chat_id, text: str, **kwargs) -> None:
    """Отправка HTML-сообщения без превью ссылок."""
    await bot.send_message(
        chat_id=chat_id, text=text, parse_mode=ParseMode.HTML,
        disable_web_page_preview=True, **kwargs,
    )


async def notify_balance(bot, chat_id) -> None:
    """Сообщает, что закончился баланс OrcaRouter (в текущий чат и владельцу)."""
    text = "⚠️ <b>Закончился баланс OrcaRouter.</b> Пополни счёт — без этого саммари недоступны."
    await send(bot, chat_id, text)
    if config.MY_CHAT_ID and str(config.MY_CHAT_ID) != str(chat_id):
        try:
            await send(bot, config.MY_CHAT_ID, text)
        except Exception:
            log.exception("Не удалось уведомить владельца")


# ---------- дайджест ----------

async def build_digest_messages(group: str) -> tuple[list[str], bool]:
    """Собирает сообщения дайджеста. Второй элемент — удалось ли сделать AI-саммари."""
    sources = config.sources_for(group)
    items = await asyncio.to_thread(rss_parser.fetch_many, sources, config.FETCH_PER_SOURCE)
    if not items:
        return ["😔 Не удалось загрузить новости. Попробуй чуть позже."], False

    live = len({i["source"] for i in items})
    try:
        stories = await asyncio.to_thread(summarizer.build_digest, items, config.TOP_N[group])
    except llm.BalanceError:
        raise
    except (llm.LLMError, summarizer.SummarizeError) as exc:
        log.warning("AI-саммари недоступно: %s", exc)
        header = (f"⚠️ <b>Саммари временно недоступно</b> ({esc(exc)}). Вот свежие заголовки "
                  f"· источников: {live}/{len(sources)}")
        top = items[: config.TOP_N[group] * 3]
        return pack(header, [headline_block(i) for i in top], sep="\n"), False

    header = f"{GROUP_TITLES[group].split(' ', 1)[0]} <b>Дайджест</b> · историй: {len(stories)} · источников: {live}/{len(sources)}"
    return pack(header, [story_block(s) for s in stories]), True


async def get_digest(group: str) -> list[str]:
    """Дайджест с кэшем на CACHE_TTL секунд (кэшируются только удачные AI-дайджесты)."""
    cached = _CACHE.get(group)
    if cached and time.monotonic() - cached[0] < config.CACHE_TTL:
        return cached[1]
    messages, ok = await build_digest_messages(group)
    if ok:
        _CACHE[group] = (time.monotonic(), messages)
    return messages


async def deliver_digest(bot, chat_id, group: str) -> None:
    """Собирает и отправляет дайджест."""
    try:
        messages = await get_digest(group)
    except llm.BalanceError:
        await notify_balance(bot, chat_id)
        return
    except Exception:
        log.exception("Ошибка дайджеста")
        await send(bot, chat_id, "⚠️ Что-то пошло не так при сборке дайджеста. Попробуй ещё раз.")
        return
    for text in messages:
        await send(bot, chat_id, text)


async def deliver_market(bot, chat_id) -> None:
    """Сводка Мосбиржи + комментарий модели (EN + RU)."""
    snap = await asyncio.to_thread(market.fetch_snapshot)
    if snap.is_empty():
        await send(bot, chat_id, "😔 Данные Мосбиржи сейчас недоступны. Попробуй позже.")
        return
    await send(bot, chat_id, market.format_html(snap))
    try:
        comment = await asyncio.to_thread(summarizer.market_commentary, market.to_plain_text(snap))
    except llm.BalanceError:
        await notify_balance(bot, chat_id)
        return
    except (llm.LLMError, summarizer.SummarizeError) as exc:
        log.warning("Комментарий к рынку недоступен: %s", exc)
        return
    await send(bot, chat_id, f"💬 <b>Комментарий</b>\n🇬🇧 {esc(comment['en'])}\n🇷🇺 {esc(comment['ru'])}")


# ---------- хендлеры ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 <b>News Digest Bot</b>\n\n"
        "Главные новости из 20 изданий — на русском и английском, с пояснениями, "
        "плюс сводка Мосбиржи: индексы, курсы и 20 акций.\n\n"
        "Выбери раздел 👇"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu())


async def digest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📰 <b>News Digest Bot</b>\n\nВыбери раздел 👇",
                                    parse_mode=ParseMode.HTML, reply_markup=main_menu())


async def market_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await deliver_market(context.bot, update.message.chat_id)


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Your Chat ID: <code>{update.message.chat_id}</code>", parse_mode=ParseMode.HTML)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data, chat_id = query.data, query.message.chat_id

    if data == "menu":
        await query.edit_message_text("📰 <b>News Digest Bot</b>\n\nВыбери раздел 👇",
                                      parse_mode=ParseMode.HTML, reply_markup=main_menu())
    elif data == "about":
        names = ", ".join(s.name for s in config.SOURCES)
        text = (
            "ℹ️ <b>О боте</b>\n\n"
            f"📡 <b>Источники ({len(config.SOURCES)}):</b> {esc(names)}\n\n"
            f"🤖 <b>AI:</b> {esc(config.LLM_MODEL)} через OrcaRouter\n"
            "📊 <b>Рынок:</b> MOEX ISS (индексы, акции), курсы ЦБ РФ\n"
            f"⏰ <b>Рассылка:</b> каждое утро в {config.DAILY_HOUR_MSK}:00 МСК"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_menu())
    elif data.startswith("digest_"):
        group = data.removeprefix("digest_")
        if group not in config.TOP_N:
            return
        await query.edit_message_text(
            f"⏳ <b>{GROUP_TITLES[group]}</b>\n\nСобираю новости и делаю саммари — это 20–40 секунд.",
            parse_mode=ParseMode.HTML)
        await deliver_digest(context.bot, chat_id, group)
        await send(context.bot, chat_id, "✅ Готово. Что дальше?", reply_markup=main_menu())
    elif data == "market":
        await query.edit_message_text("⏳ <b>Мосбиржа</b>\n\nЗагружаю котировки…", parse_mode=ParseMode.HTML)
        await deliver_market(context.bot, chat_id)
        await send(context.bot, chat_id, "✅ Готово. Что дальше?", reply_markup=main_menu())


async def daily_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Утренняя рассылка: рынок + полный дайджест."""
    chat_id = config.MY_CHAT_ID
    if not chat_id:
        return
    await send(context.bot, chat_id, "🌅 <b>Доброе утро! Твой утренний дайджест</b>")
    await deliver_market(context.bot, chat_id)
    await deliver_digest(context.bot, chat_id, "all")
    await send(context.bot, chat_id, "✅ Утренний дайджест готов.", reply_markup=main_menu())


def main() -> None:
    """Запуск бота."""
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # иначе в лог попадает токен бота
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN не задан в .env")
    if not config.ORCAROUTER_API_KEY:
        log.warning("ORCAROUTER_API_KEY не задан — саммари работать не будут")

    app = Application.builder().token(config.TELEGRAM_TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("digest", digest_cmd))
    app.add_handler(CommandHandler("market", market_cmd))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CallbackQueryHandler(menu_callback))

    if app.job_queue:
        app.job_queue.run_daily(daily_job, time=dtime(config.DAILY_HOUR_MSK, 0, tzinfo=MSK), name="daily_digest")
    else:
        log.warning("JobQueue недоступен: pip install 'python-telegram-bot[job-queue]'")

    log.info("Бот запущен, утренняя рассылка в %d:00 МСК", config.DAILY_HOUR_MSK)
    app.run_polling()


if __name__ == "__main__":
    main()
