"""Perception-Orchestrator.

Verantwortlichkeiten:
- Inbox-Aufnahme (POST /api/inbox/ingest)
- Job-Status (GET /api/jobs/{id}, GET /api/jobs/stats)
- Health/Heartbeat
- Dispatch an Nano laeuft als Background-Task (Phase 2 implementiert)
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response

from app import health
from app.auth import Principal, current_user
from app.config import settings
from app.inbox import ingest
from app.logging_config import configure_logging, get_logger
from app.mqtt import publisher
from app.nano_client import NanoClient
from app.queue import JobQueue

configure_logging()
log = get_logger(__name__)

INBOX_ROOT = Path(settings.inbox_root)
ORIGINALS_ROOT = Path(settings.originals_root)
RESULTS_ROOT = Path(settings.results_root)
QUEUE_DB = Path(settings.queue_db)

queue = JobQueue(QUEUE_DB)
nano = NanoClient(settings.nano_base_url, settings.nano_token)
_dispatch_lock = asyncio.Semaphore(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("orchestrator.startup", inbox=str(INBOX_ROOT), nano=settings.nano_base_url)
    for d in (INBOX_ROOT, ORIGINALS_ROOT, RESULTS_ROOT):
        d.mkdir(parents=True, exist_ok=True)
    try:
        publisher.connect()
    except Exception as exc:
        log.warning("mqtt.connect_failed", error=str(exc))
    task = asyncio.create_task(_dispatcher_loop())
    yield
    task.cancel()
    publisher.disconnect()
    log.info("orchestrator.shutdown")


app = FastAPI(
    title=settings.service_name,
    version=settings.service_version,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)


# Readiness-Check aus der env verdrahten: HEALTH_DB_PATH gesetzt -> DB-Probe.
if settings.health_db_path:
    health.register_check("db", health.sqlite_check(settings.health_db_path))


@app.get("/health")
async def health_endpoint(response: Response) -> dict:
    healthy, checks = await health.run_checks(timeout=settings.health_check_timeout)
    body = {
        "status": "ok" if healthy else "degraded",
        "service": settings.service_name,
        "version": settings.service_version,
        "time": datetime.now(timezone.utc).isoformat(),
        "queue": queue.stats(),
    }
    if checks:
        body["checks"] = checks
    if not healthy:
        response.status_code = 503
    return body


@app.post("/api/inbox/ingest")
async def api_ingest(path: str, _: Principal = Depends(current_user)) -> dict:
    src = Path(path)
    try:
        job_id = ingest(
            src, inbox_root=INBOX_ROOT, originals_root=ORIGINALS_ROOT, queue=queue
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job_id}


@app.get("/api/jobs/stats")
async def api_stats(_: Principal = Depends(current_user)) -> dict[str, int]:
    return queue.stats()


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str, _: Principal = Depends(current_user)) -> dict:
    job = queue.get(job_id)
    if not job:
        raise HTTPException(status_code=404)
    return job


# --- Dispatcher ---


async def _dispatcher_loop() -> None:
    log.info("dispatcher.start")
    while True:
        try:
            await _dispatch_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("dispatcher.tick_failed", error=str(exc))
        await asyncio.sleep(settings.dispatch_poll_seconds)


async def _dispatch_once() -> None:
    job = queue.claim_next()
    if not job:
        return
    async with _dispatch_lock:
        log.info("dispatcher.job_start", job_id=job["id"], kind=job["kind"])
        try:
            envelope = await nano.analyze(
                kind=job["kind"], file_path=Path(job["source_path"]), job_id=job["id"]
            )
            result_path = _persist_result(envelope, job)
            queue.mark_done(job["id"], str(result_path))
            log.info(
                "dispatcher.job_done",
                job_id=job["id"],
                exec_ms=envelope.exec.exec_ms,
                review_required=envelope.review_required,
            )
        except Exception as exc:
            queue.mark_failed(job["id"], str(exc))
            log.warning("dispatcher.job_failed", job_id=job["id"], error=str(exc))


def _persist_result(envelope, job: dict) -> Path:
    today = datetime.now(timezone.utc)
    out_dir = RESULTS_ROOT / "json" / f"{today.year:04d}" / f"{today.month:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{job['sha256']}.json"
    out.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    return out
