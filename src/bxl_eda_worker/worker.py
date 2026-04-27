import logging
import signal
import sys
from types import FrameType

log = logging.getLogger(__name__)


def handle_event(event: dict) -> None:
    log.info("received event: %s", event)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    stopping = False

    def _stop(signum: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        log.info("signal %s received, shutting down", signum)
        stopping = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info("bxl_eda_worker starting")
    while not stopping:
        # TODO: pull events from your source (queue, broker, stream)
        #       and dispatch with handle_event(event).
        signal.pause() if hasattr(signal, "pause") else _sleep_briefly()
    log.info("bxl_eda_worker stopped")
    sys.exit(0)


def _sleep_briefly() -> None:
    import time

    time.sleep(1)
