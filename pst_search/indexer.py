"""PST → SQLite indexer.

The PST is read by the Node-side extract.mjs. This module just consumes its
NDJSON stream of Message objects and inserts them in batches.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import db, pst as pstmod

ProgressFn = Callable[[int], None]   # called with cumulative message count


def index_pst(
    pst_path: str | Path,
    db_path: str | Path,
    *,
    progress: ProgressFn | None = None,
    commit_every: int = 5000,
) -> tuple[int, int]:
    pst_path = str(Path(pst_path).resolve())
    conn = db.connect(db_path)
    db.speed_for_bulk_load(conn)
    pst_id = db.register_pst(conn, pst_path)
    # Open a single explicit transaction; we commit at batch boundaries.
    conn.execute("BEGIN")

    indexed = 0
    skipped = 0
    try:
        for msg in pstmod.iter_messages(pst_path):
            try:
                db.insert_message(conn, pst_id, msg)
                indexed += 1
            except Exception:
                skipped += 1
                continue
            if indexed % commit_every == 0:
                conn.commit()
                conn.execute("BEGIN")
                if progress:
                    progress(indexed)
        conn.commit()
        db.finalize_pst(conn, pst_id)
        if progress:
            progress(indexed)
    finally:
        conn.close()
    return pst_id, indexed
