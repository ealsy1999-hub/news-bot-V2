"""Клиент OrcaRouter (chat/completions) с повторами, fallback-моделью и обработкой ошибок."""
from __future__ import annotations

import logging
import random
import re
import time

import requests

import config

log = logging.getLogger(__name__)

_BALANCE_MARKERS = ("insufficient", "balance", "no credits", "out of credits", "payment required", "billing")


class LLMError(Exception):
    """Общая ошибка обращения к модели."""


class LLMTimeout(LLMError):
    """Модель не ответила за отведённое время."""


class BalanceError(LLMError):
    """На балансе OrcaRouter закончились средства."""


def _is_balance_error(resp: requests.Response) -> bool:
    """Похож ли ответ на ошибку баланса."""
    if resp.status_code not in (400, 402, 403, 429):
        return False
    if resp.status_code == 402:
        return True
    low = resp.text.lower()
    return any(m in low for m in _BALANCE_MARKERS)


def _extract_text(resp: requests.Response) -> str:
    """Достаёт текст ответа из JSON."""
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise LLMError(f"Неожиданный формат ответа: {resp.text[:200]}") from exc
    content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()
    if not content:
        raise LLMError("Пустой ответ модели")
    return content


def _call_model(model: str, messages: list[dict], max_tokens: int, temperature: float) -> str:
    """Один вызов модели с повторами при 429 и 5xx."""
    use_web = config.LLM_WEB_SEARCH
    headers = {
        "Authorization": f"Bearer {config.ORCAROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, config.LLM_MAX_RETRIES + 1):
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if use_web:
            payload["web_search"] = True
        try:
            resp = requests.post(config.ORCAROUTER_URL, json=payload, headers=headers, timeout=config.LLM_TIMEOUT)
        except requests.Timeout as exc:
            raise LLMTimeout(f"Таймаут модели {model}") from exc
        except requests.RequestException as exc:
            raise LLMError(f"Сетевая ошибка: {type(exc).__name__}") from exc

        code = resp.status_code
        if code == 200:
            return _extract_text(resp)
        if _is_balance_error(resp):
            raise BalanceError("Закончился баланс OrcaRouter")
        if code == 429:
            pause = random.uniform(5, 10)
            log.warning("429 от %s, повтор через %.1f с (попытка %d)", model, pause, attempt)
            time.sleep(pause)
            continue
        if code in (400, 422) and use_web:
            log.warning("web_search не принят (HTTP %d), повторяю без него", code)
            use_web = False
            continue
        if code >= 500:
            log.warning("HTTP %d от %s, повтор (попытка %d)", code, model, attempt)
            time.sleep(3)
            continue
        raise LLMError(f"HTTP {code}: {resp.text[:200]}")
    raise LLMError(f"Исчерпаны попытки обращения к {model}")


def chat(messages: list[dict], max_tokens: int = 2000, temperature: float = 0.3) -> str:
    """Запрос к модели. При таймауте или ошибке пробует LLM_FALLBACK_MODEL, если она задана."""
    if not config.ORCAROUTER_API_KEY:
        raise LLMError("ORCAROUTER_API_KEY не задан в .env")
    models = [config.LLM_MODEL]
    if config.LLM_FALLBACK_MODEL and config.LLM_FALLBACK_MODEL != config.LLM_MODEL:
        models.append(config.LLM_FALLBACK_MODEL)

    last_error: LLMError | None = None
    for model in models:
        try:
            return _call_model(model, messages, max_tokens, temperature)
        except BalanceError:
            raise
        except LLMError as exc:
            log.warning("Модель %s не сработала: %s", model, exc)
            last_error = exc
    assert last_error is not None
    raise last_error
