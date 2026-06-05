import logging
import time
from typing import Callable

from plexapi.server import PlexServer


log = logging.getLogger(__name__)


class PlexListener:
    def __init__(
        self,
        baseurl: str,
        token: str,
        handler: Callable[[dict], None],
        on_server: Callable[[PlexServer], None] | None = None,
    ):
        self.baseurl = baseurl
        self.token = token
        self.handler = handler
        self.on_server = on_server
        self._listener_thread = None

    def is_alive(self) -> bool:
        return bool(self._listener_thread and self._listener_thread.is_alive())

    def run_forever(self) -> None:
        while True:
            try:
                log.info("Connecting to Plex at %s", self.baseurl)
                server = PlexServer(self.baseurl, self.token)
                log.info("Connected to Plex: %s (%s)", server.friendlyName, server.version)
                if self.on_server:
                    self.on_server(server)
                self._listener_thread = server.startAlertListener(self.handler)
                while self._listener_thread.is_alive():
                    time.sleep(5)
                log.warning("Plex alert listener stopped, reconnecting in 10s")
            except Exception:
                log.exception("Plex listener crashed, retrying in 10s")
            time.sleep(10)
