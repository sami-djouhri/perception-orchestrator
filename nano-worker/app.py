"""jetson-perception-worker — minimaler Worker fuer Phase 1.

Phase-1-Scope: /health, /models, /analyze/image (Tesseract-OCR + naive Bildtyp-Heuristik).
Schwere Modelle (TensorRT, ONNX) folgen in Phase 2/6.

Concurrency: hart auf 1 schweren Job (asyncio.Semaphore).
Tempfiles: pro Request ein Subdir unter TEMP_ROOT, try/finally Cleanup.
Logging: structlog optional, Fallback Standard-Logging — KEINE OCR-Volltexte.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("perception")

TOKEN = os.getenv("PERCEPTION_TOKEN", "").strip()
TEMP_ROOT = Path(os.getenv("PERCEPTION_TEMP", "/mnt/ssd/perception/tmp"))
HOST_LABEL = os.getenv("PERCEPTION_HOST", "jetson-nano")
SCHEMA_VERSION = "v1"

_heavy_lock = asyncio.Semaphore(1)
_started_at = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    if not TOKEN:
        log.warning("PERCEPTION_TOKEN nicht gesetzt - Auth deaktiviert (dev only)")
    yield
    # best effort cleanup
    for child in TEMP_ROOT.glob("*"):
        try:
            shutil.rmtree(child, ignore_errors=True)
        except Exception:
            pass


app = FastAPI(title="jetson-perception-worker", version="0.1.0", lifespan=lifespan)


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        return
    expected = f"Bearer {TOKEN}"
    if not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "uptime_s": int(time.time() - _started_at),
        "schema_version": SCHEMA_VERSION,
        "active_heavy": 1 - _heavy_lock._value,  # type: ignore[attr-defined]
    }


@app.get("/models", dependencies=[Depends(require_token)])
async def models() -> dict:
    return {
        "ocr": {"tesseract": _tesseract_version()},
        "image_classifier": "heuristic-v0",
        "schema_version": SCHEMA_VERSION,
    }


@app.post("/analyze/image", dependencies=[Depends(require_token)])
async def analyze_image(
    file: UploadFile = File(...),
    job_id: str = Form(default_factory=lambda: str(uuid.uuid4())),
) -> dict:
    if _heavy_lock.locked():
        raise HTTPException(status_code=429, detail="busy", headers={"Retry-After": "5"})
    async with _heavy_lock:
        return await _do_analyze_image(file, job_id)


# --- Implementation ---


async def _do_analyze_image(file: UploadFile, job_id: str) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.time()
    workdir = TEMP_ROOT / f"job-{job_id}"
    workdir.mkdir(parents=True, exist_ok=True)
    in_path = workdir / (file.filename or "input.bin")
    try:
        with in_path.open("wb") as f:
            chunk = await file.read(1 << 20)
            while chunk:
                f.write(chunk)
                chunk = await file.read(1 << 20)
        sha = _sha256(in_path)
        ocr_text, ocr_conf = _run_tesseract(in_path)
        kind, tags = _heuristic_image_kind(in_path, ocr_text)
        finished = datetime.now(timezone.utc)
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "image",
            "job_id": job_id,
            "sha256": sha,
            "source_path": str(in_path),
            "exec": {
                "host": HOST_LABEL,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "exec_ms": int((time.time() - t0) * 1000),
                "model_versions": {"ocr": _tesseract_version()},
            },
            "result": {
                "image_kind": kind,
                "tags": tags,
                "objects": [],
                "short_caption": "",
                "ocr": {
                    "text": ocr_text,
                    "lang": "deu+eng",
                    "confidence_avg": ocr_conf,
                    "page_count": 1,
                    "blocks": [],
                },
            },
            "warnings": [],
            "review_required": False,
            "review_reasons": [],
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tesseract_version() -> str:
    try:
        import subprocess
        out = subprocess.check_output(["tesseract", "--version"], stderr=subprocess.STDOUT)
        return out.decode().splitlines()[0].strip()
    except Exception:
        return "unavailable"


def _run_tesseract(path: Path) -> tuple[str, float]:
    """Best effort. Wenn tesseract fehlt -> leerer Text."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["tesseract", str(path), "-", "-l", "deu+eng", "--psm", "3"],
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        text = out.decode("utf-8", errors="replace")
        # Confidence-Schaetzung: Anteil druckbarer Zeichen
        if not text.strip():
            return "", 0.0
        printable = sum(1 for c in text if c.isprintable() or c.isspace())
        conf = min(1.0, printable / max(1, len(text)))
        return text, round(conf, 2)
    except Exception as exc:
        log.warning("tesseract_failed", extra={"err": str(exc)})
        return "", 0.0


def _heuristic_image_kind(path: Path, ocr_text: str) -> tuple[str, list[str]]:
    """Phase-1-Heuristik. Phase 2 ersetzt durch ONNX-Klassifikator."""
    name = path.suffix.lower()
    text_low = ocr_text.lower()
    tags: list[str] = []
    if any(k in text_low for k in ("error", "fehler", "exception", "traceback")):
        tags.append("error")
    if any(k in text_low for k in ("$", "€", "preis", "rabatt", "warenkorb")):
        tags.append("commerce")
    if name in {".png"} and len(ocr_text) > 200:
        return "diagram" if "→" in ocr_text else "other", tags + ["screenshot_candidate"]
    if name in {".jpg", ".jpeg", ".heic"}:
        return "photo", tags
    if name == ".pdf":
        return "other", tags + ["pdf"]
    return "other", tags
