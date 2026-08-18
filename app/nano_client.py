"""HTTP-Client zum jetson-perception-worker.

Sendet Multipart-Upload (Phase 1) - NFS-Pfad kommt in Phase 6.
Concurrency: aufrufender Code muss Semaphore=1 enforcen.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from app.schemas import PerceptionEnvelope


class NanoClient:
    def __init__(self, base_url: str, token: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()

    async def analyze(self, kind: str, file_path: Path, job_id: str) -> PerceptionEnvelope:
        endpoint = f"{self.base_url}/analyze/{kind}"
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            with file_path.open("rb") as f:
                files = {"file": (file_path.name, f, "application/octet-stream")}
                data = {"job_id": job_id}
                r = await c.post(
                    endpoint, headers=self._headers(), files=files, data=data
                )
            r.raise_for_status()
            return PerceptionEnvelope.model_validate(r.json())
