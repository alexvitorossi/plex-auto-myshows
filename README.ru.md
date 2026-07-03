# plex-auto-myshows

[English](README.md) · Русский

Лёгкий docker сервис, который слушает Plex по websocket и автоматически отмечает просмотренные эпизоды сериалов в [myshows.me](https://myshows.me/).

## Как это работает

1. Подключается к Plex с твоим токеном и подписывается на alert-уведомления.
2. Когда серия досмотрена (`state=stopped` с прогрессом ≥ `WATCHED_THRESHOLD_PERCENT`, по умолчанию 90%, или `viewCount > 0`), событие попадает в обработчик.
3. По внешним id (tvdb/imdb) сериал из Plex маппится на сериал в MyShows через `shows.GetByExternalId`; маппинг кэшируется в SQLite.
4. Эпизод отмечается в MyShows через `manage.CheckEpisode` (v2 JSON-RPC API).

Параллельно при старте и раз в сутки делается catch-up по `Plex.history()` — серии, досмотренные пока контейнер лежал, отметятся при ближайшем запуске.

**Существующие отметки не трогаются.** Сервис только ставит «просмотрено», снимать не умеет.

## Конфигурация

Скопируй `.env.example` в `.env` и заполни:

```
PLEX_URL=http://<ip-плекса>:32400
PLEX_TOKEN=<Plex-токен>
PLEX_USERNAME=                # пусто = реагируем на все события

MYSHOWS_LOGIN=<логин на myshows.me>
MYSHOWS_PASSWORD=<пароль>

DRY_RUN=false                 # true = только логи, в MyShows ничего не шлём
```

Plex-токен — см. [официальную инструкцию](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

Опциональные переменные (с дефолтами):

```
WATCHED_THRESHOLD_PERCENT=90
CATCHUP_ON_START=true
CATCHUP_INTERVAL_HOURS=24
CATCHUP_LOOKBACK_HOURS=24
```

## Запуск

```sh
docker compose up --build -d
docker compose logs -f
```

`./data` — volume для SQLite (маппинг сериалов, список отмеченных эпизодов, last-run для catch-up) и OAuth refresh-токена. Переживает пересоздание контейнера.
