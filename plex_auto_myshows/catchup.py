import logging
import time
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from plexapi.exceptions import NotFound
from plexapi.server import PlexServer
from plexapi.video import Episode

from .cache import Cache


log = logging.getLogger(__name__)

META_LAST_RUN = "last_catchup_ts"


class CatchUp:
    def __init__(
        self,
        baseurl: str,
        token: str,
        cache: Cache,
        on_watched: Callable[[Episode, str | None], bool],
        lookback_hours: int,
        username_filter: str | None = None,
        tz: str = "Europe/Belgrade",
        dry_run: bool = False,
    ):
        self.baseurl = baseurl
        self.token = token
        self.cache = cache
        self.on_watched = on_watched
        self.lookback_hours = lookback_hours
        self.username_filter = username_filter
        self.dry_run = dry_run
        try:
            self.tz = ZoneInfo(tz)
        except ZoneInfoNotFoundError:
            log.warning("Unknown timezone %r, falling back to Europe/Belgrade", tz)
            self.tz = ZoneInfo("Europe/Belgrade")

    def _mindate(self) -> datetime:
        last = self.cache.get_meta(META_LAST_RUN)
        if last:
            try:
                return datetime.fromtimestamp(float(last), self.tz)
            except ValueError:
                pass
        return datetime.now(self.tz) - timedelta(hours=self.lookback_hours)

    def run(self) -> None:
        mindate = self._mindate()
        log.info("Catch-up scan since %s", mindate.isoformat(timespec="seconds"))
        try:
            server = PlexServer(self.baseurl, self.token)
            history = server.history(maxresults=500, mindate=mindate)
        except Exception:
            log.exception("Catch-up: Plex request failed")
            return

        accounts: dict[int, str] = {}
        if self.username_filter:
            try:
                accounts = {int(a.id): a.name for a in server.systemAccounts() if a.name}
            except Exception:
                log.exception("Catch-up: failed to load systemAccounts; cannot apply username filter")
                return

        processed = 0
        skipped = 0
        failed = 0
        for h in history:
            if getattr(h, "type", None) != "episode":
                continue
            account_id = getattr(h, "accountID", None)
            try:
                username = accounts.get(int(account_id)) if account_id is not None else None
            except (TypeError, ValueError):
                username = None
            if self.username_filter and username != self.username_filter:
                log.debug(
                    "Catch-up: skipping accountID=%s (username=%s); filter=%s",
                    account_id,
                    username or "?",
                    self.username_filter,
                )
                skipped += 1
                continue
            rating_key = getattr(h, "ratingKey", None)
            if rating_key is None or self.cache.is_watched(str(rating_key)):
                continue
            try:
                item = server.fetchItem(int(rating_key))
            except NotFound:
                log.warning("Catch-up: ratingKey=%s not found, skipping", rating_key)
                continue
            except Exception:
                log.warning("Catch-up: failed to fetch ratingKey=%s (transient)", rating_key)
                failed += 1
                continue
            if not isinstance(item, Episode):
                continue
            log.info(
                "Catch-up: %s S%02dE%02d (%s)",
                item.grandparentTitle,
                item.seasonNumber or 0,
                item.index or 0,
                item.title,
            )
            try:
                if self.on_watched(item, username):
                    processed += 1
                else:
                    failed += 1
            except Exception:
                log.exception("Catch-up: on_watched failed for ratingKey=%s", rating_key)
                failed += 1

        if failed:
            log.warning(
                "Catch-up done, processed %d new item(s), %d failed; last-run timestamp not advanced",
                processed,
                failed,
            )
            return

        if self.dry_run:
            log.info(
                "Catch-up done (dry-run), processed %d item(s), skipped %d; "
                "last-run timestamp not advanced",
                processed,
                skipped,
            )
            return

        self.cache.set_meta(META_LAST_RUN, str(time.time()))
        log.info("Catch-up done, processed %d new item(s), skipped %d", processed, skipped)
