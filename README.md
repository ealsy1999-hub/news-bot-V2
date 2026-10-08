# News Bot

Telegram-бот: дайджест главных новостей из 20 изданий (RU + мировые) с саммари на английском и русском
и сводка Мосбиржи (индексы, курсы ЦБ, 20 акций). Модель — DeepSeek через OrcaRouter.

## Запуск
```bash
pip install -r requirements.txt
cp .env.example .env      # впиши TELEGRAM_TOKEN, MY_CHAT_ID, ORCAROUTER_API_KEY
python app.py             # или: python src/bot.py
```

## Проверка
```bash
python src/rss_parser.py  # какие источники отвечают
python src/market.py      # данные Мосбиржи
```

## Команды
`/start`, `/digest`, `/market`, `/myid`

## Настройки (src/config.py)
Источники `SOURCES`, акции `STOCKS`, число историй `TOP_N`, время рассылки `DAILY_HOUR_MSK`.
