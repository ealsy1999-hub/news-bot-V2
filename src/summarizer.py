"""Двуязычное (EN + RU) саммари новостей через OrcaRouter."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import llm

log = logging.getLogger(__name__)

MAX_ITEMS_IN_PROMPT = 100
SNIPPET_LEN = 250
MAX_LINKS_PER_STORY = 5
CATEGORIES = {"energy", "markets", "economy", "geopolitics", "tech", "society", "other"}


class SummarizeError(Exception):
    """Не удалось получить корректное саммари."""


@dataclass
class Story:
    """Одна история дайджеста."""

    title: str
    category: str
    en: str
    ru: str
    why: str
    links: list[tuple[str, str]] = field(default_factory=list)  # (источник, url)


def _extract_json(text: str, open_ch: str, close_ch: str):
    """Достаёт JSON из ответа модели (убирает ```-обёртки и лишний текст)."""
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find(open_ch), text.rfind(close_ch)
    if start == -1 or end <= start:
        raise ValueError("JSON не найден")
    return json.loads(text[start:end + 1])


SYSTEM_PROMPT = """You are a senior news editor for a business-focused reader (energy, markets, geopolitics, Russia and the world).
You get a numbered list of fresh headlines from different outlets. Pick the {n} most important stories
(merge items about the same story from different outlets into one story).
For each story return a JSON object with keys:
  "ids": array of item numbers that cover this story,
  "category": one of energy, markets, economy, geopolitics, tech, society, other,
  "title": short headline in Russian,
  "en": 2-3 sentence summary in English,
  "ru": 2-3 sentence summary in Russian,
  "why": one sentence in Russian explaining why it matters or what it may lead to.
Rules: use ONLY facts from the provided list, never invent numbers, names or quotes.
If the text is thin, say what is known from the headline. Order stories by importance.
Return ONLY a JSON array, no commentary."""


def build_digest(items: list[dict], top_n: int) -> list[Story]:
    """Выбирает главные истории и пишет саммари EN + RU."""
    numbered = items[:MAX_ITEMS_IN_PROMPT]
    lines = []
    for i, it in enumerate(numbered, 1):
        line = f"[{i}] {it['source']} | {it['title']}"
        if it.get("summary"):
            line += f" | {it['summary'][:SNIPPET_LEN]}"
        lines.append(line)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(n=top_n)},
        {"role": "user", "content": "\n".join(lines)},
    ]

    data = None
    for attempt in (1, 2):
        text = llm.chat(messages, max_tokens=3500, temperature=0.3)
        try:
            data = _extract_json(text, "[", "]")
            break
        except (ValueError, json.JSONDecodeError):
            log.warning("Модель вернула невалидный JSON (попытка %d)", attempt)
    if not isinstance(data, list):
        raise SummarizeError("Модель не вернула корректный JSON")

    stories: list[Story] = []
    for obj in data:
        if not isinstance(obj, dict):
            continue
        ids = [int(x) for x in obj.get("ids", []) if str(x).isdigit() and 1 <= int(x) <= len(numbered)]
        if not ids:
            continue
        links, seen = [], set()
        for i in ids:
            it = numbered[i - 1]
            if it["link"] not in seen and len(links) < MAX_LINKS_PER_STORY:
                seen.add(it["link"])
                links.append((it["source"], it["link"]))
        category = obj.get("category", "other")
        stories.append(Story(
            title=str(obj.get("title") or numbered[ids[0] - 1]["title"]),
            category=category if category in CATEGORIES else "other",
            en=str(obj.get("en", "")).strip(),
            ru=str(obj.get("ru", "")).strip(),
            why=str(obj.get("why", "")).strip(),
            links=links,
        ))
    if not stories:
        raise SummarizeError("В ответе модели нет историй")
    return stories[:top_n]


MARKET_PROMPT = """You are a markets analyst. Below is a snapshot of the Moscow Exchange: indices, official CBR currency rates
and 20 large Russian stocks (price and % change vs previous close).
Write a short commentary: what moved most, what the picture looks like overall, what to keep an eye on.
Use ONLY the given numbers; do not invent causes, news or forecasts. This is not investment advice.
Return ONLY a JSON object: {"en": "2-3 sentences in English", "ru": "2-3 предложения по-русски"}."""


def market_commentary(snapshot_text: str) -> dict[str, str]:
    """Короткий комментарий к сводке рынка (EN + RU)."""
    messages = [
        {"role": "system", "content": MARKET_PROMPT},
        {"role": "user", "content": snapshot_text},
    ]
    text = llm.chat(messages, max_tokens=700, temperature=0.3)
    try:
        data = _extract_json(text, "{", "}")
    except (ValueError, json.JSONDecodeError) as exc:
        raise SummarizeError("Комментарий к рынку: невалидный JSON") from exc
    return {"en": str(data.get("en", "")).strip(), "ru": str(data.get("ru", "")).strip()}
