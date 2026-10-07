"""A small local daily-digest scheduler; one process, outbox retries every minute."""

import logging
import time

from app.product.digests import daily_tick

if __name__ == "__main__":
    while True:
        try:
            daily_tick()
        except Exception as exc:
            logging.error("digest_tick_failed: %s", type(exc).__name__)
        time.sleep(60)
