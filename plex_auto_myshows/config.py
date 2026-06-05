import os
from dataclasses import dataclass


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(v: str | None, default: int) -> int:
    try:
        return int(v) if v else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    plex_url: str
    plex_token: str
    plex_username: str | None

    myshows_client_id: str
    myshows_client_secret: str
    myshows_login: str
    myshows_password: str

    log_level: str
    data_dir: str
    dry_run: bool
    timezone: str

    catchup_on_start: bool
    catchup_interval_hours: int
    catchup_lookback_hours: int

    @staticmethod
    def from_env() -> "Config":
        def req(name: str) -> str:
            val = os.environ.get(name, "").strip()
            if not val:
                raise RuntimeError(f"Missing required env var: {name}")
            return val

        username = os.environ.get("PLEX_USERNAME", "").strip() or None
        dry_run = _bool(os.environ.get("DRY_RUN"), default=True)

        return Config(
            plex_url=req("PLEX_URL"),
            plex_token=req("PLEX_TOKEN"),
            plex_username=username,
            myshows_client_id=os.environ.get("MYSHOWS_CLIENT_ID", "").strip() or "apidoc",
            myshows_client_secret=os.environ.get("MYSHOWS_CLIENT_SECRET", "").strip() or "apidoc",
            myshows_login=os.environ.get("MYSHOWS_LOGIN", "").strip(),
            myshows_password=os.environ.get("MYSHOWS_PASSWORD", "").strip(),
            log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
            data_dir=os.environ.get("DATA_DIR", "/data").strip(),
            dry_run=dry_run,
            timezone=os.environ.get("TZ", "").strip() or "Europe/Belgrade",
            catchup_on_start=_bool(os.environ.get("CATCHUP_ON_START"), default=True),
            catchup_interval_hours=max(1, _int(os.environ.get("CATCHUP_INTERVAL_HOURS"), 24)),
            catchup_lookback_hours=_int(os.environ.get("CATCHUP_LOOKBACK_HOURS"), 24),
        )
