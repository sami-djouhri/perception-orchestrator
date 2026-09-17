import tempfile
from pathlib import Path

from app.queue import JobQueue


def test_enqueue_idempotent_for_done():
    with tempfile.TemporaryDirectory() as tmp:
        q = JobQueue(Path(tmp) / "q.sqlite")
        a = q.enqueue(sha256="abc", kind="image", source_path="/x")
        # zweite Aufnahme bei state=queued -> neuer Job
        b = q.enqueue(sha256="abc", kind="image", source_path="/x")
        assert a != b
        # nach done -> wiederverwendet
        q.mark_done(b, "/r")
        c = q.enqueue(sha256="abc", kind="image", source_path="/x")
        assert c == b


def test_claim_next_atomic():
    with tempfile.TemporaryDirectory() as tmp:
        q = JobQueue(Path(tmp) / "q.sqlite")
        jid = q.enqueue(sha256="x", kind="image", source_path="/y")
        first = q.claim_next()
        second = q.claim_next()
        assert first is not None and first["id"] == jid
        assert second is None  # nichts mehr queued


def test_failed_retries_until_max():
    with tempfile.TemporaryDirectory() as tmp:
        q = JobQueue(Path(tmp) / "q.sqlite")
        jid = q.enqueue(sha256="x", kind="image", source_path="/y")
        for _ in range(2):
            q.claim_next()
            q.mark_failed(jid, "boom", max_attempts=3)
        # 3. Versuch
        q.claim_next()
        q.mark_failed(jid, "boom", max_attempts=3)
        assert q.get(jid)["state"] == "failed"
