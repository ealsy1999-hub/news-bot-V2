"""Конфигурация News Bot: переменные окружения, источники новостей, тикеры Мосбиржи."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "false") -> bool:
    """Читает булев флаг из окружения."""
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# --- Telegram ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
MY_CHAT_ID = os.getenv("MY_CHAT_ID", "")

# --- OrcaRouter / LLM ---
ORCAROUTER_API_KEY = os.getenv("ORCAROUTER_API_KEY", "")
ORCAROUTER_URL = os.getenv("ORCAROUTER_URL", "https://api.orcarouter.ai/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash-free")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "").strip()
LLM_WEB_SEARCH = _flag("LLM_WEB_SEARCH", "false")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "90"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))

# --- Параметры дайджеста ---
FETCH_PER_SOURCE = 4      # сколько свежих новостей берём с каждого источника
TOP_N = {"ru": 7, "world": 7, "all": 10}  # сколько историй в дайджесте
MAX_AGE_HOURS = 48        # старше этого возраста новости отбрасываем
CACHE_TTL = 15 * 60       # кэш готового дайджеста, секунды
DAILY_HOUR_MSK = 6        # время утренней рассылки (МСК)


@dataclass(frozen=True)
class Source:
    """Источник новостей."""

    key: str
    name: str
    lang: str       # "ru" | "en"
    home: str       # главная страница
    rss: str        # RSS-лента ("" — сразу используем Google News)
    domain: str

    @property
    def google_rss(self) -> str:
        """Запасная лента: Google News, ограниченный доменом источника."""
        q = quote(f"site:{self.domain} when:2d")
        if self.lang == "ru":
            return f"https://news.google.com/rss/search?q={q}&hl=ru&gl=RU&ceid=RU:ru"
        return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


SOURCES: list[Source] = [
    # Русскоязычные
    Source("ria", "РИА Новости", "ru", "https://ria.ru/", "https://ria.ru/export/rss2/archive/index.xml", "ria.ru"),
    Source("rbc", "РБК", "ru", "https://www.rbc.ru/", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "rbc.ru"),
    Source("izvestia", "Известия", "ru", "https://iz.ru/", "https://iz.ru/xml/rss/all.xml", "iz.ru"),
    Source("kommersant", "Коммерсантъ", "ru", "https://www.kommersant.ru/", "https://www.kommersant.ru/RSS/news.xml", "kommersant.ru"),
    Source("vedomosti", "Ведомости", "ru", "https://www.vedomosti.ru/", "https://www.vedomosti.ru/rss/news", "vedomosti.ru"),
    Source("lenta", "Лента.ру", "ru", "https://lenta.ru/", "https://lenta.ru/rss/news", "lenta.ru"),
    Source("gazeta", "Газета.Ru", "ru", "https://www.gazeta.ru/", "https://www.gazeta.ru/export/rss/lenta.xml", "gazeta.ru"),
    Source("rt", "RT", "ru", "https://russian.rt.com/", "https://russian.rt.com/rss", "russian.rt.com"),
    Source("interfax", "Интерфакс", "ru", "https://www.interfax.ru/", "https://www.interfax.ru/rss.asp", "interfax.ru"),
    Source("tass", "ТАСС", "ru", "https://tass.ru/", "https://tass.ru/rss/v2.xml", "tass.ru"),
    # Иностранные
    Source("reuters", "Reuters", "en", "https://www.reuters.com/", "", "reuters.com"),
    Source("nyt", "NYT", "en", "https://www.nytimes.com/", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "nytimes.com"),
    Source("bbc", "BBC News", "en", "https://www.bbc.com/news", "https://feeds.bbci.co.uk/news/rss.xml", "bbc.com"),
    Source("cnn", "CNN", "en", "https://edition.cnn.com/", "http://rss.cnn.com/rss/edition.rss", "cnn.com"),
    Source("ap", "AP", "en", "https://apnews.com/", "", "apnews.com"),
    Source("ft", "Financial Times", "en", "https://www.ft.com/", "https://www.ft.com/rss/home", "ft.com"),
    Source("guardian", "The Guardian", "en", "https://www.theguardian.com/", "https://www.theguardian.com/world/rss", "theguardian.com"),
    Source("wapo", "Washington Post", "en", "https://www.washingtonpost.com/", "https://feeds.washingtonpost.com/rss/world", "washingtonpost.com"),
    Source("axios", "Axios", "en", "https://www.axios.com/", "https://api.axios.com/feed/", "axios.com"),
    Source("aljazeera", "Al Jazeera", "en", "https://www.aljazeera.com/", "https://www.aljazeera.com/xml/rss/all.xml", "aljazeera.com"),
]


def sources_for(group: str) -> list[Source]:
    """Источники для группы: ru, world или all."""
    if group == "ru":
        return [s for s in SOURCES if s.lang == "ru"]
    if group == "world":
        return [s for s in SOURCES if s.lang == "en"]
    return list(SOURCES)


# --- Мосбиржа ---
INDEX_TICKERS = ["IMOEX", "RTSI"]
CURRENCIES = ["USD", "EUR", "CNY"]  # официальные курсы ЦБ РФ

# (тикер на TQBR, короткое название)
STOCKS: list[tuple[str, str]] = [
    ("SBER", "Сбербанк"), ("GAZP", "Газпром"), ("LKOH", "ЛУКОЙЛ"), ("ROSN", "Роснефть"),
    ("NVTK", "Новатэк"), ("TATN", "Татнефть"), ("SNGS", "Сургут"), ("GMKN", "Норникель"),
    ("PLZL", "Полюс"), ("CHMF", "Северсталь"), ("NLMK", "НЛМК"), ("ALRS", "АЛРОСА"),
    ("MTSS", "МТС"), ("MGNT", "Магнит"), ("YDEX", "Яндекс"), ("MOEX", "Мосбиржа"),
    ("VTBR", "ВТБ"), ("AFLT", "Аэрофлот"), ("PHOR", "ФосАгро"), ("PIKK", "ПИК"),
]
