"""Background indexing job manager.

We run each PST index on a worker thread so the FastAPI request handler can
return immediately. The UI polls /api/jobs/{id} to render progress. State
lives in memory only — the server process is a single uvicorn worker and
jobs don't survive restarts, which is fine because indexing is restartable
and bounded (~15 minutes for a multi-GB PST).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import indexer


@dataclass
class IndexJob:
    id: str
    path: str
    status: str = "queued"   # queued | running | done | error | cancelled
    indexed: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    pst_id: int | None = None
    error: str | None = None
    # threading.Event holds a _thread.lock which dataclasses.asdict can't
    # deepcopy — keep it out of the dataclass field list. Attached lazily.
    cancel_event: threading.Event = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.cancel_event is None:
            object.__setattr__(self, "cancel_event", threading.Event())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "status": self.status,
            "indexed": self.indexed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pst_id": self.pst_id,
            "error": self.error,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
        }


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, IndexJob] = {}
        self._lock = threading.Lock()

    def list(self) -> list[IndexJob]:
        with self._lock:
            return list(self._jobs.values())

    def get(self, job_id: str) -> IndexJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, pst_path: str, db_path: Path) -> IndexJob:
        job = IndexJob(id=str(uuid.uuid4()), path=str(Path(pst_path).resolve()))
        with self._lock:
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, db_path), daemon=True).start()
        return job

    def _run(self, job: IndexJob, db_path: Path) -> None:
        job.status = "running"

        def on_progress(done: int) -> None:
            job.indexed = done

        try:
            pst_id, total = indexer.index_pst(job.path, db_path, progress=on_progress)
            job.pst_id = pst_id
            job.indexed = total
            job.status = "done"
        except Exception as e:  # noqa: BLE001
            job.error = f"{type(e).__name__}: {e}"
            job.status = "error"
        finally:
            job.finished_at = time.time()


# Module-level singleton — FastAPI imports this and shares one registry across
# requests. Safe because uvicorn runs a single worker for this app.
registry = JobRegistry()
