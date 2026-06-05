import logging
from dataclasses import dataclass

from plexapi.video import Episode

from .cache import Cache
from .myshows import MyShowsClient


log = logging.getLogger(__name__)

# A show missing from MyShows is cached as id 0; re-check it after a week in
# case it gets added there later.
MISS_TTL_SECONDS = 7 * 24 * 3600


@dataclass
class ExternalIds:
    tvdb: int | None = None
    imdb: str | None = None
    tmdb: int | None = None


def extract_external_ids(episode: Episode) -> ExternalIds:
    show = episode.show()
    ids = ExternalIds()
    for g in getattr(show, "guids", []) or []:
        guid = g.id if hasattr(g, "id") else str(g)
        if guid.startswith("tvdb://"):
            try:
                ids.tvdb = int(guid.removeprefix("tvdb://").split("?")[0])
            except ValueError:
                pass
        elif guid.startswith("imdb://"):
            ids.imdb = guid.removeprefix("imdb://").split("?")[0]
        elif guid.startswith("tmdb://"):
            try:
                ids.tmdb = int(guid.removeprefix("tmdb://").split("?")[0])
            except ValueError:
                pass
    return ids


class Matcher:
    def __init__(self, client: MyShowsClient, cache: Cache):
        self.client = client
        self.cache = cache

    def resolve_episode_id(self, episode: Episode) -> int | None:
        show = episode.show()
        cached = self.cache.get_show_mapping(show.guid)

        myshows_show_id = None
        if cached is not None:
            cached_id, age = cached
            if cached_id == 0:
                # Negative cache: honour it until the TTL expires, then re-resolve.
                if age < MISS_TTL_SECONDS:
                    return None
            else:
                myshows_show_id = cached_id

        if myshows_show_id is None:
            ids = extract_external_ids(episode)
            myshows_show_id = self.client.find_show_by_title(show.title, tvdb=ids.tvdb, imdb=ids.imdb)
            if myshows_show_id is None:
                log.warning("No MyShows match for show %s (%s); caching as miss", show.title, ids)
                self.cache.set_show_mapping(show.guid, 0, show.title)
                return None
            self.cache.set_show_mapping(show.guid, myshows_show_id, show.title)

        ep = self.client.find_episode(myshows_show_id, episode.seasonNumber or 0, episode.index or 0)
        return ep.id if ep else None
