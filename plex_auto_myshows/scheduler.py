import logging
import threading
import time
from typing import Callable


log = logging.getLogger(__name__)


def schedule_periodic(name: str, interval_seconds: int, fn: Callable[[], None]) -> threading.Thread:
    def loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                fn()
            except Exception:
                log.exception("Scheduled task '%s' raised", name)

    t = threading.Thread(target=loop, name=f"sched-{name}", daemon=True)
    t.start()
    log.info("Scheduler: '%s' every %ds", name, interval_seconds)
    return t
