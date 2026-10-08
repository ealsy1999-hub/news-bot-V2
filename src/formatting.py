"""Форматирование сообщений Telegram (HTML) для дайджеста."""
from __future__ import annotations

import html

from summarizer import Story

CATEGORY_EMOJI = {
    "energy": "⚡", "markets": "📈", "economy": "💼", "geopolitics": "🌍",
    "tech": "💻", "society": "📰", "other": "📰",
}
SEP = "\n\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
LIMIT = 3800


def esc(text: object) -> str:
    """Экранирует текст для HTML-режима Telegram."""
    return html.escape(str(text or ""), quote=False)


def _link(name: str, url: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{esc(name)}</a>'


def story_block(story: Story) -> str:
    """Один блок истории: заголовок, EN, RU, пояснение, ссылки."""
    parts = [
        f"{CATEGORY_EMOJI.get(story.category, '📰')} <b>{esc(story.title)}</b>",
        f"🇬🇧 {esc(story.en)}",
        f"🇷🇺 {esc(story.ru)}",
    ]
    if story.why:
        parts.append(f"💡 {esc(story.why)}")
    if story.links:
        parts.append("🔗 " + " · ".join(_link(n, u) for n, u in story.links))
    return "\n".join(parts)


def headline_block(item: dict) -> str:
    """Запасной вариант без AI: заголовок со ссылкой."""
    return f"• {_link(item['title'], item['link'])} — <i>{esc(item['source'])}</i>"


def pack(header: str, blocks: list[str], sep: str = SEP) -> list[str]:
    """Склеивает блоки в сообщения не длиннее лимита Telegram."""
    messages: list[str] = []
    current = header
    joiner = "\n\n" if header else ""  # после шапки — обычный отступ
    for block in blocks:
        if current and len(current) + len(sep) + len(block) > LIMIT:
            messages.append(current)
            current = block
        else:
            current = f"{current}{joiner}{block}" if current else block
        joiner = sep
    if current:
        messages.append(current)
    return messages
