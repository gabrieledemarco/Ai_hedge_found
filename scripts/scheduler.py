"""
APScheduler-based trading scheduler for Render deployment.

Replicates the GitHub Actions cron schedule:
  06:15 UTC  → morning session
  15:15 UTC  → afternoon session
  20:30 UTC  → evening session

Also keeps the IB Gateway session alive with a tickle every 60 seconds,
and exposes a /health endpoint so Render can check liveness.
"""

import os
import sys
import threading
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session label mapping (mirrors GitHub Actions logic)
# ---------------------------------------------------------------------------

def _session_label(hour: int) -> str:
    if hour < 10:
        return "mattina"
    if hour < 18:
        return "pomeriggio"
    return "sera"


# ---------------------------------------------------------------------------
# Pipeline runner (lazy import to avoid loading heavy models at startup)
# ---------------------------------------------------------------------------

_last_run: dict = {"ts": None, "result": None, "error": None}


def _run_session(hour: int) -> None:
    from main_pipeline import run_pipeline
    label = _session_label(hour)
    log.info(f"=== Session start: {label} (hour={hour}) ===")
    try:
        result = run_pipeline(label)
        _last_run["ts"] = datetime.now(timezone.utc).isoformat()
        _last_run["result"] = result
        _last_run["error"] = None
        log.info(f"=== Session complete: {label} ===")
    except Exception as e:
        _last_run["error"] = str(e)
        log.exception(f"Session {label} failed: {e}")


# ---------------------------------------------------------------------------
# IB Gateway keepalive
# ---------------------------------------------------------------------------

def _ib_tickle() -> None:
    try:
        from ib_broker import get_broker
        broker = get_broker()
        if broker.is_available():
            broker.tickle()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Flask health endpoint
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "last_run": _last_run["ts"],
        "last_error": _last_run["error"],
        "utc": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/")
def index():
    return jsonify({"service": "AI Hedge Fund Scheduler", "status": "running"})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    scheduler = BackgroundScheduler(timezone="UTC")

    # Trading sessions — Mon–Fri only
    scheduler.add_job(
        lambda: _run_session(6),
        CronTrigger(hour=6, minute=15, day_of_week="mon-fri"),
        id="morning",
        name="Morning session (06:15 UTC)",
    )
    scheduler.add_job(
        lambda: _run_session(15),
        CronTrigger(hour=15, minute=15, day_of_week="mon-fri"),
        id="afternoon",
        name="Afternoon session (15:15 UTC)",
    )
    scheduler.add_job(
        lambda: _run_session(20),
        CronTrigger(hour=20, minute=30, day_of_week="mon-fri"),
        id="evening",
        name="Evening session (20:30 UTC)",
    )

    # IB Gateway keepalive — every 60 seconds
    scheduler.add_job(
        _ib_tickle,
        "interval",
        seconds=60,
        id="ib_tickle",
        name="IB Gateway tickle",
    )

    scheduler.start()
    log.info("Scheduler started — sessions: 06:15, 15:15, 20:30 UTC (Mon-Fri)")

    # List next scheduled runs
    for job in scheduler.get_jobs():
        nf = job.next_run_time
        log.info(f"  {job.name}: next run at {nf}")

    # Run Flask in the main thread
    port = int(os.environ.get("PORT", 8080))
    log.info(f"Health endpoint: http://0.0.0.0:{port}/health")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
