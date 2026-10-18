
import json
import logging
import math
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from threading import Lock

from fastapi import FastAPI, Query, Request
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI()

EMAIL = "24f2009140@ds.study.iitm.ac.in"
START_TIME = time.monotonic()

REQUEST_COUNTER = Counter(
    "http_requests_total",
    "Total HTTP requests received",
)

LOG_LIMIT = 1000
logs = deque(maxlen=LOG_LIMIT)
logs_lock = Lock()


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": getattr(record, "request_path", "-"),
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        })


logger = logging.getLogger("service")
logger.setLevel(logging.INFO)
logger.propagate = False

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    path = request.url.path
    start = time.perf_counter()

    REQUEST_COUNTER.inc()

    try:
        response = await call_next(request)
    except Exception:
        logger.error(
            "request failed",
            extra={"request_path": path, "request_id": request_id},
        )
        raise

    elapsed = time.perf_counter() - start

    entry = {
        "level": "INFO",
        "ts": datetime.now(timezone.utc).isoformat(),
        "path": path,
        "request_id": request_id,
        "method": request.method,
        "status_code": response.status_code,
        "duration_s": round(elapsed, 6),
    }

    with logs_lock:
        logs.append(entry)

    logger.info(
        "request completed",
        extra={"request_path": path, "request_id": request_id},
    )

    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/work")
def work(n: int = Query(..., ge=0, le=1000000)):
    # Perform deterministic CPU work proportional to n.
    done = 0
    for _ in range(n):
        done += 1

    return {"email": EMAIL, "done": done}


@app.get("/healthz")
def healthz():
    uptime = max(0.0, time.monotonic() - START_TIME)
    return {"status": "ok", "uptime_s": float(uptime)}


@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/logs/tail")
def logs_tail(limit: int = Query(100, ge=1, le=1000)):
    with logs_lock:
        entries = list(logs)[-limit:]
    return entries
