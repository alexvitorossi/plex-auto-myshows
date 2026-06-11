import itertools
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__


log = logging.getLogger(__name__)

TOKEN_URL = "https://myshows.me/oauth/token"
RPC_URL = "https://api.myshows.me/v2/rpc/"
AUTH_BACKOFF_SECONDS = 60


@dataclass
class Episode:
    id: int
    season: int
    number: int


class MyShowsError(RuntimeError):
    pass


class MyShowsTransientError(MyShowsError):
    """A retryable failure (network, timeout, 5xx, rate-limit, rejected token).

    Unlike a plain MyShowsError it must not be swallowed as "not found": the
    caller should retry later rather than caching the item as processed.
    """


class MyShowsClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        login: str,
        password: str,
        session_path: str | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.login = login
        self.password = password
        self.token_path = Path(session_path) if session_path else None

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._last_auth_failure: float = 0.0
        self._loaded = False
        # The client is shared between the alert listener and the catch-up
        # scheduler threads, so guard all token state behind one lock.
        # Reentrant because _rpc -> _ensure_token -> authenticate all take it.
        self._lock = threading.RLock()
        self._request_lock = threading.Lock()

        self.s = requests.Session()
        self.s.headers["User-Agent"] = f"plex-auto-myshows/{__version__}"
        self._rpc_id = itertools.count(1)

    def authenticate(self) -> None:
        with self._lock:
            if not self._loaded:
                self._load_token()
                self._loaded = True
            if self._access_token and time.time() < self._expires_at:
                return

            wait = AUTH_BACKOFF_SECONDS - (time.time() - self._last_auth_failure)
            if wait > 0:
                raise MyShowsError(f"MyShows auth backoff: {wait:.0f}s after previous failure")

            try:
                if self._refresh_token and self._fetch_token_by_refresh():
                    self._last_auth_failure = 0
                    return
                self._fetch_token_by_password()
                self._last_auth_failure = 0
            except Exception:
                self._last_auth_failure = time.time()
                raise

    def _ensure_token(self) -> None:
        if not self._access_token or time.time() >= self._expires_at:
            self.authenticate()

    def _load_token(self) -> bool:
        if not self.token_path or not self.token_path.exists():
            return False
        try:
            self.token_path.chmod(0o600)
            data = json.loads(self.token_path.read_text())
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._expires_at = float(data.get("expires_at", 0))
            return bool(self._refresh_token)
        except Exception:
            log.exception("Failed to load MyShows token")
            return False

    def _save_token(self) -> None:
        if not self.token_path:
            return
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at,
        })
        tmp_path = self.token_path.with_name(f".{self.token_path.name}.tmp")
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.token_path)
        self.token_path.chmod(0o600)

    def _apply_token_response(self, data: dict) -> None:
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
        self._save_token()

    def _post_token(self, data: dict) -> requests.Response:
        for attempt in range(5):
            try:
                with self._request_lock:
                    r = self.s.post(TOKEN_URL, data=data, timeout=15)
            except requests.RequestException as e:
                log.warning("token endpoint request failed (attempt %d/5): %s", attempt + 1, e)
                time.sleep(2 + attempt * 2)
                continue
            if r.status_code == 200 or r.status_code in (400, 401, 403):
                return r
            log.warning("token endpoint HTTP %s (attempt %d/5)", r.status_code, attempt + 1)
            time.sleep(2 + attempt * 2)
        raise MyShowsError("MyShows token endpoint unreachable after 5 attempts")

    def _fetch_token_by_password(self) -> None:
        if not self.login or not self.password:
            raise MyShowsError("MyShows login/password are required for initial auth")
        r = self._post_token({
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "username": self.login,
            "password": self.password,
        })
        if r.status_code != 200:
            raise MyShowsError(f"MyShows password auth failed: HTTP {r.status_code} {r.text[:200]}")
        self._apply_token_response(r.json())
        log.info("MyShows: authenticated by password as %s", self.login)

    def _fetch_token_by_refresh(self) -> bool:
        if not self._refresh_token:
            return False
        try:
            r = self._post_token({
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self._refresh_token,
            })
        except MyShowsError as e:
            log.warning("MyShows refresh request failed: %s", e)
            return False
        if r.status_code != 200:
            log.warning("MyShows refresh failed: HTTP %s %s", r.status_code, r.text[:200])
            return False
        self._apply_token_response(r.json())
        log.info("MyShows: refreshed access token")
        return True

    def _rpc(self, method: str, params: dict | None = None, retry_on_401: bool = True) -> dict:
        with self._lock:
            try:
                self._ensure_token()
            except MyShowsTransientError:
                raise
            except MyShowsError as e:
                raise MyShowsTransientError(f"RPC {method} auth failed: {e}") from e
            token = self._access_token
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": next(self._rpc_id),
        }
        try:
            with self._request_lock:
                r = self.s.post(
                    RPC_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=20,
                )
        except requests.RequestException as e:
            raise MyShowsTransientError(f"RPC {method} request failed: {e}") from e
        if r.status_code == 401 and retry_on_401:
            with self._lock:
                # Only invalidate if no other thread already refreshed it.
                if self._access_token == token:
                    self._access_token = None
                    self._expires_at = 0
            return self._rpc(method, params, retry_on_401=False)
        if r.status_code == 401:
            raise MyShowsTransientError(f"RPC {method} still unauthorized after token refresh")
        if r.status_code == 429 or r.status_code >= 500:
            raise MyShowsTransientError(f"RPC {method} HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code != 200:
            raise MyShowsError(f"RPC {method} HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if "error" in data:
            raise MyShowsError(f"RPC {method} error: {data['error']}")
        return data.get("result")

    def find_show_by_external_id(
        self, *, tvdb: int | None = None, imdb: str | None = None
    ) -> int | None:
        attempts: list[tuple[str, str]] = []
        if tvdb:
            attempts.append(("thetvdb", str(tvdb)))
        if imdb:
            imdb_id = imdb if imdb.startswith("tt") else f"tt{imdb}"
            attempts.append(("imdb", imdb_id))
        for source, value in attempts:
            try:
                result = self._rpc("shows.GetByExternalId", {"id": value, "source": source})
            except MyShowsTransientError:
                raise
            except MyShowsError as e:
                log.debug("GetByExternalId(%s=%s) failed: %s", source, value, e)
                continue
            if result and isinstance(result, dict) and result.get("id"):
                return int(result["id"])
        return None

    def find_show_by_title(
        self, title: str, *, tvdb: int | None = None, imdb: str | None = None
    ) -> int | None:
        found = self.find_show_by_external_id(tvdb=tvdb, imdb=imdb)
        if found is not None:
            return found
        try:
            result = self._rpc("shows.Search", {"query": title})
        except MyShowsTransientError:
            raise
        except MyShowsError as e:
            log.debug("shows.Search failed: %s", e)
            return None
        if not result:
            return None
        title_l = title.lower().strip()
        for it in result:
            if str(it.get("title", "")).lower().strip() == title_l:
                return int(it["id"])
            if str(it.get("titleOriginal", "")).lower().strip() == title_l:
                return int(it["id"])
        return None

    def find_episode(self, show_id: int, season: int, number: int) -> Episode | None:
        try:
            result = self._rpc("shows.GetById", {"showId": show_id, "withEpisodes": True})
        except MyShowsTransientError:
            raise
        except MyShowsError as e:
            log.warning("GetById(%s) failed: %s", show_id, e)
            return None
        for ep in result.get("episodes", []) or []:
            if int(ep.get("seasonNumber", -1)) == season and int(ep.get("episodeNumber", -1)) == number:
                return Episode(id=int(ep["id"]), season=season, number=number)
        return None

    def check_episode(self, episode_id: int) -> None:
        self._rpc("manage.CheckEpisode", {"id": episode_id})
