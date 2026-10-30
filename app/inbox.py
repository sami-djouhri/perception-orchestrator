"""Inbox-Handling: Hash, Immutabilisieren, Job erzeugen.

Watcher (inotify) wird in Phase 2 ergaenzt. Vorerst: Funktion, die ein
einzelnes File aus /data/inbox/* aufnimmt.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import date
from pathlib import Path

from app.queue import JobQueue

KIND_BY_INBOX = {
    "documents": "document",
    "scans": "document",
    "screenshots": "screenshot",
    "images": "image",
    "immich_exports": "image",
}


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def immutabilize(src: Path, originals_root: Path) -> tuple[str, Path]:
    """Kopiert nach originals/immutable/yyyy/mm/<sha>.<ext>, idempotent."""
    sha = sha256_of(src)
    today = date.today()
    dst_dir = originals_root / f"{today.year:04d}" / f"{today.month:02d}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    dst = dst_dir / f"{sha}{ext}"
    if not dst.exists():
        shutil.copy2(src, dst)
        dst.chmod(0o440)  # read-only fuer alle
    return sha, dst


def ingest(
    src: Path,
    *,
    inbox_root: Path,
    originals_root: Path,
    queue: JobQueue,
) -> str:
    """Nimmt eine Datei aus inbox_root auf. Gibt job_id zurueck."""
    if not src.is_file():
        raise FileNotFoundError(src)
    if not src.is_relative_to(inbox_root):
        raise ValueError(f"{src} liegt nicht unter {inbox_root}")
    sub = src.relative_to(inbox_root).parts[0]
    kind = KIND_BY_INBOX.get(sub)
    if kind is None:
        raise ValueError(f"unbekanntes Inbox-Subverzeichnis: {sub}")
    sha, dst = immutabilize(src, originals_root)
    return queue.enqueue(sha256=sha, kind=kind, source_path=str(dst))
