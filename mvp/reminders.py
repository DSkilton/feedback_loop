"""Run review reminders as a separate worker (no background thread in the web API).

Use the same explicitly configured database as the web server. Default: one run.
For a long-running worker, use --interval-seconds 3600 under a service manager.
"""
import argparse
import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .notifications import due_review_reminders


def main():
    parser = argparse.ArgumentParser(description="Run due Feedback Loop tutor-review reminders.")
    parser.add_argument("--after-hours", type=int, default=24)
    parser.add_argument("--interval-seconds", type=int, default=0)
    args = parser.parse_args()
    if args.after_hours < 1 or args.interval_seconds < 0 or (0 < args.interval_seconds < 60):
        parser.error("Use at least one hour of review age and a zero or >=60 second interval.")
    url = os.getenv("FEEDBACK_LOOP_DB_URL")
    if not url:
        parser.error("Explicitly configure FEEDBACK_LOOP_DB_URL to match the application database.")
    from .api import Enrollment, Feedback, StructuredFeedbackEvent
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = create_engine(url)
    try:
        while True:
            try:
                with Session(engine) as db:
                    count = due_review_reminders(db, Feedback, Enrollment, StructuredFeedbackEvent,
                                                 now=datetime.now(timezone.utc), after_hours=args.after_hours)
                    db.commit()
                logging.info("Review reminder run completed: %s created", count)
            except Exception:
                logging.exception("Review reminder run failed")
                if not args.interval_seconds:
                    raise
            if not args.interval_seconds:
                return
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        logging.info("Review reminder worker stopped")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
