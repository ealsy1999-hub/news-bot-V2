"""Загрузка новостей из RSS (с запасным вариантом через Google News)."""
from __future__ import annotations

import calendar
import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests

import config
from config import Source

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _clean(text: str, limit: int = 300) -> str:
    """Убирает HTML-теги и лишние пробелы."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit]


def _timestamp(entry) -> float | None:
    """Время публикации записи (unix) или None."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return float(calendar.timegm(parsed)) if parsed else None


def _load(url: str, src: Source, google: bool, limit: int) -> list[dict]:
    """Скачивает и разбирает одну ленту."""
    resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items = []
    for entry in feed.entries:
        title = _clean(entry.get("title", ""), 250)
        link = entry.get("link", "")
        if not title or not link:
            continue
        if google:
            title = title.rsplit(" - ", 1)[0]
            summary = ""
        else:
            summary = _clean(entry.get("summary", "") or entry.get("description", ""))
        items.append({
            "source": src.name,
            "lang": src.lang,
            "title": title,
            "summary": summary,
            "link": link,
            "ts": _timestamp(entry),
            "via": "google" if google else "rss",
        })
    items.sort(key=lambda i: i["ts"] or 0, reverse=True)
    fresh_after = time.time() - config.MAX_AGE_HOURS * 3600
    fresh = [i for i in items if i["ts"] is None or i["ts"] >= fresh_after]
    return (fresh or items)[:limit]


def fetch_source(src: Source, limit: int) -> list[dict]:
    """Новости одного источника: сначала свой RSS, затем Google News."""
    attempts: list[tuple[str, bool]] = []
    if src.rss:
        attempts.append((src.rss, False))
    attempts.append((src.google_rss, True))
    for url, google in attempts:
        try:
            items = _load(url, src, google, limit)
            if items:
                return items
        except Exception as exc:  # источник может быть недоступен или отдавать мусор
            log.warning("%s (%s): %s", src.name, "google" if google else "rss", type(exc).__name__)
    return []


def fetch_many(sources: list[Source], limit: int) -> list[dict]:
    """Параллельно загружает новости со списка источников."""
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda s: fetch_source(s, limit), sources))
    seen: set[str] = set()
    items: list[dict] = []
    for chunk in results:
        for item in chunk:
            key = item["title"].lower()
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items


def main() -> None:
    """Проверка источников: python src/rss_parser.py"""
    logging.basicConfig(level=logging.WARNING)
    print("=== Проверка источников ===")
    ok = 0
    for src in config.SOURCES:
        items = fetch_source(src, config.FETCH_PER_SOURCE)
        via = items[0]["via"] if items else "-"
        ok += bool(items)
        print(f"{'✓' if items else '✗'} {src.name:<18} {len(items)} шт. ({via})")
    print(f"\nРаботают: {ok}/{len(config.SOURCES)}")


if __name__ == "__main__":
    main()
