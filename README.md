# plex-auto-myshows

English · [Русский](README.ru.md)

A small docker service that watches Plex over websocket and automatically marks watched TV episodes on [myshows.me](https://myshows.me/).

## How it works

1. Connects to Plex with your token and subscribes to alert notifications.
2. When an episode is watched (`state=stopped` with progress ≥90%, or `viewCount > 0`), the event hits the handler.
3. The show is matched to MyShows by external id (tvdb/imdb) via `shows.GetByExternalId`; the mapping is cached in SQLite.
4. The episode is marked on MyShows via `manage.CheckEpisode` (v2 JSON-RPC API).

In parallel, a catch-up scan runs on startup and daily: episodes watched while the container was down get marked on the next run via `Plex.history()`.

**Existing marks are never touched.** The service only sets "watched"; it cannot unset.

## Configuration

Copy `.env.example` to `.env` and fill it in:

```
PLEX_URL=http://<plex-ip>:32400
PLEX_TOKEN=<plex token>
PLEX_USERNAME=                # empty = react to all sessions

MYSHOWS_LOGIN=<myshows.me login>
MYSHOWS_PASSWORD=<password>

DRY_RUN=false                 # true = log only, do not call MyShows API
```

Plex token — see [the official guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

Optional env (with defaults):

```
CATCHUP_ON_START=true
CATCHUP_INTERVAL_HOURS=24
CATCHUP_LOOKBACK_HOURS=24
```

## Run

```sh
docker compose up --build -d
docker compose logs -f
```

`./data` is a volume for the SQLite cache (show mappings, watched episodes, catch-up last-run timestamp) and the OAuth refresh token. It survives container rebuilds.
