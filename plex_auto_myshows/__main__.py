import logging
import sys

from plexapi.video import Episode

from . import __version__
from .alerts.playing import PlayingHandler
from .cache import Cache
from .catchup import CatchUp
from .config import Config
from .healthcheck import start_healthcheck
from .matcher import Matcher
from .myshows import MyShowsClient
from .plex_listener import PlexListener
from .scheduler import schedule_periodic


def main() -> int:
    cfg = Config.from_env()
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("plex-auto-myshows")
    log.info("Starting plex-auto-myshows v%s (dry_run=%s)", __version__, cfg.dry_run)

    cache = Cache(cfg.data_dir)
    myshows = MyShowsClient(
        cfg.myshows_client_id,
        cfg.myshows_client_secret,
        cfg.myshows_login,
        cfg.myshows_password,
        session_path=f"{cfg.data_dir}/myshows_token.json",
    )
    matcher = Matcher(myshows, cache)

    try:
        myshows.authenticate()
    except Exception:
        log.exception("MyShows authentication failed (will retry lazily on first event)")

    def on_watched(episode: Episode, username: str | None = None) -> bool:
        rating_key = str(episode.ratingKey)
        if cache.is_watched(rating_key):
            return True

        if cfg.dry_run:
            log.info(
                "[DRY-RUN] would mark watched: %s S%02dE%02d (by %s)",
                episode.grandparentTitle,
                episode.seasonNumber or 0,
                episode.index or 0,
                username or "?",
            )
            return True

        try:
            episode_id = matcher.resolve_episode_id(episode)
        except Exception:
            log.exception("Failed to resolve MyShows episode id (transient)")
            return False

        if episode_id is None:
            log.warning(
                "No MyShows match for %s S%02dE%02d, skipping",
                episode.grandparentTitle,
                episode.seasonNumber or 0,
                episode.index or 0,
            )
            cache.mark_watched(rating_key, None)
            return True

        try:
            myshows.check_episode(episode_id)
        except Exception:
            log.exception("Failed to mark episode %s in MyShows", episode_id)
            return False

        cache.mark_watched(rating_key, episode_id)
        log.info("Marked watched on MyShows: episode_id=%s", episode_id)
        return True

    catchup = CatchUp(
        cfg.plex_url, cfg.plex_token, cache, on_watched,
        lookback_hours=cfg.catchup_lookback_hours,
        username_filter=cfg.plex_username,
        tz=cfg.timezone,
        dry_run=cfg.dry_run,
    )

    if cfg.catchup_on_start:
        try:
            catchup.run()
        except Exception:
            log.exception("Initial catch-up failed (continuing)")

    schedule_periodic("catchup", cfg.catchup_interval_hours * 3600, catchup.run)

    playing_handler = PlayingHandler(
        on_watched=on_watched,
        username_filter=cfg.plex_username,
    )

    listener = PlexListener(
        baseurl=cfg.plex_url,
        token=cfg.plex_token,
        handler=playing_handler.handle,
        on_server=playing_handler.set_server,
    )

    start_healthcheck(listener.is_alive, listener.is_alive)

    listener.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
