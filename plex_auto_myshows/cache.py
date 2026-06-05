import sqlite3
import threading
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS show_map (
    plex_guid     TEXT PRIMARY KEY,
    myshows_id    INTEGER NOT NULL,
    title         TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watched (
    plex_rating_key TEXT PRIMARY KEY,
    myshows_episode_id INTEGER,
    marked_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Cache:
    def __init__(self, data_dir: str):
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(
            str(Path(data_dir) / "plex-auto-myshows.db"),
            check_same_thread=False,
        )
        self._lock = threading.Lock()
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def get_show_mapping(self, plex_guid: str) -> tuple[int, int] | None:
        """Return (myshows_id, age_seconds) for a cached mapping, or None."""
        with self._lock:
            row = self.conn.execute(
                "SELECT myshows_id, "
                "CAST((julianday('now') - julianday(created_at)) * 86400 AS INTEGER) "
                "FROM show_map WHERE plex_guid = ?",
                (plex_guid,),
            ).fetchone()
        return (row[0], row[1]) if row else None

    def set_show_mapping(self, plex_guid: str, myshows_id: int, title: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO show_map (plex_guid, myshows_id, title) VALUES (?, ?, ?)",
                (plex_guid, myshows_id, title),
            )
            self.conn.commit()

    def is_watched(self, plex_rating_key: str) -> bool:
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM watched WHERE plex_rating_key = ?", (plex_rating_key,)
            ).fetchone()
        return row is not None

    def mark_watched(self, plex_rating_key: str, myshows_episode_id: int | None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO watched (plex_rating_key, myshows_episode_id) VALUES (?, ?)",
                (plex_rating_key, myshows_episode_id),
            )
            self.conn.commit()

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
            )
            self.conn.commit()
