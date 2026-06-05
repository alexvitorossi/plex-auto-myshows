import logging
from collections import OrderedDict
from typing import Callable

from plexapi.server import PlexServer
from plexapi.video import Episode


log = logging.getLogger(__name__)

WATCHED_THRESHOLD = 0.90
USER_CACHE_MAX = 100


class PlayingHandler:
    def __init__(
        self,
        on_watched: Callable[[Episode, str | None], bool],
        username_filter: str | None = None,
        server: PlexServer | None = None,
    ):
        self.server = server
        self.on_watched = on_watched
        self.username_filter = username_filter
        self._users: "OrderedDict[str, str]" = OrderedDict()

    def set_server(self, server: PlexServer) -> None:
        self.server = server

    def handle(self, msg: dict) -> None:
        if msg.get("type") != "playing":
            return
        for note in msg.get("PlaySessionStateNotification", []):
            try:
                self._on_note(note)
            except Exception:
                log.exception("Failed to handle playing note: %s", note)

    def _remember_user(self, machine_id: str, username: str) -> None:
        self._users[machine_id] = username
        self._users.move_to_end(machine_id)
        while len(self._users) > USER_CACHE_MAX:
            self._users.popitem(last=False)

    def _resolve_username(self, machine_id: str | None) -> str | None:
        if not machine_id or self.server is None:
            return self._users.get(machine_id) if machine_id else None
        try:
            for s in self.server.sessions():
                for p in getattr(s, "players", []) or []:
                    if getattr(p, "machineIdentifier", None) == machine_id:
                        users = getattr(s, "usernames", None) or []
                        if users:
                            self._remember_user(machine_id, users[0])
                            return users[0]
        except Exception:
            log.exception("Failed to resolve username for machine_id=%s", machine_id)
        return self._users.get(machine_id)

    def _on_note(self, note: dict) -> None:
        state = note.get("state")
        rating_key = note.get("ratingKey")
        machine_id = note.get("clientIdentifier")
        view_offset = note.get("viewOffset", 0)
        if not rating_key:
            return

        # Resolve username while the session is active; it can disappear by stopped.
        if state == "playing" and machine_id:
            self._resolve_username(machine_id)
            return

        if state not in ("stopped", "paused"):
            return

        username = self._resolve_username(machine_id)

        if self.username_filter:
            if username != self.username_filter:
                log.debug(
                    "Skipping ratingKey=%s for username=%s; filter=%s",
                    rating_key,
                    username or "?",
                    self.username_filter,
                )
                return

        try:
            item = self.server.fetchItem(int(rating_key))
        except Exception:
            log.exception("Failed to fetch item ratingKey=%s", rating_key)
            return

        if not isinstance(item, Episode):
            return

        duration = getattr(item, "duration", 0) or 0
        progress = (view_offset / duration) if duration else 0.0
        view_count = getattr(item, "viewCount", 0) or 0
        if not (view_count > 0 or progress >= WATCHED_THRESHOLD):
            return

        log.info(
            "Watched by %s: %s S%02dE%02d (%s) progress=%.0f%% viewCount=%d",
            username or "?",
            item.grandparentTitle,
            item.seasonNumber or 0,
            item.index or 0,
            item.title,
            progress * 100,
            view_count,
        )
        if not self.on_watched(item, username):
            log.warning(
                "MyShows mark failed, leaving for catch-up: %s S%02dE%02d",
                item.grandparentTitle,
                item.seasonNumber or 0,
                item.index or 0,
            )
