"""Сводка Мосбиржи: индексы и акции (MOEX ISS) и официальные курсы ЦБ РФ."""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import requests

import config

log = logging.getLogger(__name__)

ISS = "https://iss.moex.com/iss"
CBR = "https://www.cbr-xml-daily.ru/daily_json.js"
HEADERS = {"User-Agent": "news-bot/1.0"}
MSK = timezone(timedelta(hours=3))


@dataclass
class Quote:
    """Котировка: цена и изменение в % к предыдущему закрытию."""

    code: str
    name: str
    price: float | None
    change_pct: float | None


@dataclass
class Snapshot:
    """Снимок рынка."""

    indices: list[Quote] = field(default_factory=list)
    currencies: list[Quote] = field(default_factory=list)
    stocks: list[Quote] = field(default_factory=list)
    updated: str = ""

    def is_empty(self) -> bool:
        return not (self.indices or self.currencies or self.stocks)


def _iss(path: str, params: dict) -> dict[str, list[dict]]:
    """Запрос к MOEX ISS; возвращает {блок: [строки-словари]}."""
    resp = requests.get(f"{ISS}{path}.json", params={"iss.meta": "off", **params}, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    out: dict[str, list[dict]] = {}
    for block, payload in resp.json().items():
        cols = payload.get("columns", [])
        out[block] = [dict(zip(cols, row)) for row in payload.get("data", [])]
    return out


def _num(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def fetch_indices() -> list[Quote]:
    """IMOEX и RTSI."""
    data = _iss(
        "/engines/stock/markets/index/boards/SNDX/securities",
        {
            "securities": ",".join(config.INDEX_TICKERS),
            "iss.only": "marketdata",
            "marketdata.columns": "SECID,CURRENTVALUE,LASTCHANGEPRC",
        },
    )
    rows = {r["SECID"]: r for r in data.get("marketdata", [])}
    return [
        Quote(t, t, _num(rows[t].get("CURRENTVALUE")), _num(rows[t].get("LASTCHANGEPRC")))
        for t in config.INDEX_TICKERS if t in rows
    ]


def fetch_stocks() -> list[Quote]:
    """Акции из config.STOCKS (режим TQBR)."""
    secids = [s for s, _ in config.STOCKS]
    data = _iss(
        "/engines/stock/markets/shares/boards/TQBR/securities",
        {
            "securities": ",".join(secids),
            "iss.only": "securities,marketdata",
            "securities.columns": "SECID,PREVPRICE",
            "marketdata.columns": "SECID,LAST,LCURRENTPRICE,LASTTOPREVPRICE",
        },
    )
    prev = {r["SECID"]: _num(r.get("PREVPRICE")) for r in data.get("securities", [])}
    market = {r["SECID"]: r for r in data.get("marketdata", [])}
    quotes = []
    for secid, name in config.STOCKS:
        row = market.get(secid)
        if row is None:
            continue
        price = _num(row.get("LAST")) or _num(row.get("LCURRENTPRICE")) or prev.get(secid)
        change = _num(row.get("LASTTOPREVPRICE"))
        if change is None and price and prev.get(secid):
            change = (price / prev[secid] - 1) * 100
        quotes.append(Quote(secid, name, price, change))
    return quotes


def fetch_currencies() -> list[Quote]:
    """Официальные курсы ЦБ РФ (USD, EUR, CNY)."""
    resp = requests.get(CBR, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    valute = resp.json()["Valute"]
    quotes = []
    for code in config.CURRENCIES:
        v = valute.get(code)
        if not v:
            continue
        nominal = v.get("Nominal") or 1
        price = v["Value"] / nominal
        prev = v["Previous"] / nominal
        quotes.append(Quote(code, code, price, (price / prev - 1) * 100 if prev else None))
    return quotes


def fetch_snapshot() -> Snapshot:
    """Собирает всё; недоступные части просто пропускаются."""
    snap = Snapshot(updated=datetime.now(MSK).strftime("%d.%m %H:%M МСК"))
    for attr, func in (("indices", fetch_indices), ("currencies", fetch_currencies), ("stocks", fetch_stocks)):
        try:
            setattr(snap, attr, func())
        except Exception as exc:
            log.warning("Мосбиржа/%s: %s", attr, exc)
    return snap


def _num_fmt(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:,.{digits}f}".replace(",", " ")


def _pct_fmt(p: float | None) -> str:
    return "—" if p is None else f"{p:+.2f}%"


def _icon(p: float | None) -> str:
    if p is None or p == 0:
        return "⚪"
    return "🟢" if p > 0 else "🔴"


def _rows(quotes: list[Quote], with_name: bool) -> str:
    lines = []
    for q in quotes:
        name = f"{q.name:<11} " if with_name else ""
        lines.append(f"{_icon(q.change_pct)} {q.code:<5} {name}{_num_fmt(q.price):>10} {_pct_fmt(q.change_pct):>8}")
    return html.escape("\n".join(lines))


def format_html(snap: Snapshot) -> str:
    """Сообщение для Telegram (HTML)."""
    parts = [f"📊 <b>Мосбиржа</b> · {html.escape(snap.updated)}"]
    if snap.indices:
        parts.append(f"<b>Индексы</b>\n<pre>{_rows(snap.indices, False)}</pre>")
    if snap.currencies:
        parts.append(f"<b>Курсы ЦБ РФ, ₽</b>\n<pre>{_rows(snap.currencies, False)}</pre>")
    if snap.stocks:
        parts.append(f"<b>Акции (TQBR), ₽</b>\n<pre>{_rows(snap.stocks, True)}</pre>")
    return "\n\n".join(parts)


def to_plain_text(snap: Snapshot) -> str:
    """Текстовый вид для передачи в модель."""
    lines = []
    for title, quotes in (("Indices", snap.indices), ("CBR rates (RUB)", snap.currencies), ("Stocks (RUB)", snap.stocks)):
        if quotes:
            lines.append(f"{title}:")
            lines += [f"{q.code} ({q.name}): {_num_fmt(q.price)} ({_pct_fmt(q.change_pct)})" for q in quotes]
    return "\n".join(lines)


def main() -> None:
    """Проверка: python src/market.py"""
    snap = fetch_snapshot()
    print(to_plain_text(snap) or "Данные недоступны")


if __name__ == "__main__":
    main()
