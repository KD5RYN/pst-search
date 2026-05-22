"""FastAPI search server.

The DB path is provided via environment variable `PSTSEARCH_DB` so PyInstaller
bundling and the CLI can share one entry point. Static frontend is served
from pst_search/web.
"""
from __future__ import annotations

import io
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db as dbmod
from . import pst as pstmod
from .jobs import registry as job_registry


def _db_path() -> Path:
    p = os.environ.get("PSTSEARCH_DB")
    if not p:
        raise RuntimeError("PSTSEARCH_DB environment variable not set")
    return Path(p)


WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title="PST Search", version="0.1.0")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/psts")
def api_psts() -> dict:
    conn = dbmod.connect(_db_path())
    try:
        return {"psts": [dict(r) for r in dbmod.list_psts(conn)]}
    finally:
        conn.close()


@app.get("/api/folders")
def api_folders() -> dict:
    conn = dbmod.connect(_db_path())
    try:
        return {"folders": [dict(r) for r in dbmod.list_folders(conn)]}
    finally:
        conn.close()


@app.get("/api/search")
def api_search(
    q: str = Query("", description="FTS5 query string; empty = browse mode"),
    sender: str | None = None,
    folder: str | None = None,
    has_attachments: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    conn = dbmod.connect(_db_path())
    try:
        try:
            rows, total = dbmod.search(
                conn, q,
                sender=sender, folder=folder, has_attachments=has_attachments,
                date_from=date_from, date_to=date_to,
                limit=limit, offset=offset,
            )
        except Exception as e:
            # FTS5 syntax errors come back as sqlite3 errors; surface them gently.
            raise HTTPException(status_code=400, detail=f"search error: {e}")
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "results": [dict(r) for r in rows],
        }
    finally:
        conn.close()


@app.get("/api/message/{message_id}")
def api_message(message_id: int) -> dict:
    conn = dbmod.connect(_db_path())
    try:
        msg, atts, pst = dbmod.get_message(conn, message_id)
        if msg is None:
            raise HTTPException(status_code=404, detail="message not found")
        return {
            "message": dict(msg),
            "attachments": [dict(a) for a in atts],
            "pst": dict(pst) if pst else None,
        }
    finally:
        conn.close()


@app.get("/api/attachment/{message_id}/{att_index}")
def api_attachment(message_id: int, att_index: int) -> StreamingResponse:
    """Lazily extract an attachment from the source PST on the fly."""
    conn = dbmod.connect(_db_path())
    try:
        msg, atts, pst = dbmod.get_message(conn, message_id)
        if msg is None or pst is None:
            raise HTTPException(status_code=404, detail="message not found")
        att_row = next((a for a in atts if a["att_index"] == att_index), None)
        if att_row is None:
            raise HTTPException(status_code=404, detail="attachment not found")
        pst_path = pst["path"]
    finally:
        conn.close()

    if not Path(pst_path).exists():
        raise HTTPException(status_code=410, detail=f"source PST no longer at {pst_path}")

    try:
        name, data = pstmod.extract_attachment(pst_path, str(msg["pff_identifier"]), att_index)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"extraction failed: {e}")

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------- PST library management ----------

class IndexRequest(BaseModel):
    path: str


@app.post("/api/pick-pst")
def api_pick_pst() -> dict:
    """Open a native OS file-picker dialog (Tkinter) and return the chosen path.

    Runs Tkinter on a fresh thread so it doesn't interfere with uvicorn's
    asyncio event loop. The dialog appears on the screen of whoever is running
    the server process — since this app is local-only, that's always the user.
    """
    result: dict = {"path": None, "error": None}

    def runner() -> None:
        try:
            # Import lazily so the server still starts on systems where tk is
            # not installed (only the picker endpoint will fail).
            from tkinter import Tk, filedialog
            root = Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            chosen = filedialog.askopenfilename(
                title="Choose a PST file to index",
                filetypes=[("Outlook PST", "*.pst"), ("All files", "*.*")],
            )
            root.destroy()
            result["path"] = chosen or None
        except Exception as e:  # noqa: BLE001
            result["error"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=runner)
    t.start()
    t.join()

    if result["error"]:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/api/index")
def api_index(req: IndexRequest) -> dict:
    p = Path(req.path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=400, detail=f"file not found: {req.path}")
    if p.suffix.lower() != ".pst":
        raise HTTPException(status_code=400, detail="file must have .pst extension")
    job = job_registry.start(str(p), _db_path())
    return job.to_dict()


@app.get("/api/jobs")
def api_jobs() -> dict:
    return {"jobs": [j.to_dict() for j in job_registry.list()]}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = job_registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_dict()


@app.delete("/api/psts/{pst_id}")
def api_delete_pst(pst_id: int) -> dict:
    conn = dbmod.connect(_db_path())
    try:
        row = conn.execute("SELECT pst_id, path FROM pst_files WHERE pst_id = ?", (pst_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="pst not found")
        # ON DELETE CASCADE removes messages + attachments + FTS rows
        conn.execute("DELETE FROM pst_files WHERE pst_id = ?", (pst_id,))
        conn.commit()
        return {"removed": dict(row)}
    finally:
        conn.close()


# Mount static assets (CSS/JS) after API routes so they don't shadow them.
if (WEB_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
