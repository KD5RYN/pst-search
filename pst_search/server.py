"""FastAPI search server.

The DB path is provided via environment variable `PSTSEARCH_DB` so the CLI
and any future bundled entry point can share one configuration source.
Static frontend is served from `pst_search/web`.
"""
from __future__ import annotations

import base64
import io
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from email.message import EmailMessage
from email.parser import HeaderParser
from email.utils import format_datetime, parsedate_to_datetime
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
    recipient: str | None = None,
    folder: str | None = None,
    has_attachments: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = Query("newest", description="One of: newest, oldest, relevance"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    conn = dbmod.connect(_db_path())
    try:
        try:
            rows, total = dbmod.search(
                conn, q,
                sender=sender, recipient=recipient, folder=folder,
                has_attachments=has_attachments,
                date_from=date_from, date_to=date_to,
                sort=sort,
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


_FILENAME_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_filename(s: str, fallback: str) -> str:
    """Sanitize a string for use as a downloaded filename."""
    cleaned = _FILENAME_BAD_CHARS.sub("_", (s or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned)[:120].rstrip(". ")
    return cleaned or fallback


# Common header lines that we'll respect from the original PST transport
# headers when assembling the .eml. Everything else (Message-ID, References,
# In-Reply-To, Reply-To, etc.) is also preserved verbatim.
_HEADER_PASSTHROUGH = (
    "message-id", "references", "in-reply-to", "reply-to",
    "return-path", "received", "x-originating-ip",
)


def _build_eml(data: dict) -> bytes:
    """Assemble an RFC 5322 .eml from the JSON dump produced by message.mjs.

    Preserves the original transport headers where possible (Message-ID,
    threading headers) but overrides content headers since we're putting the
    body and attachments into fresh MIME parts.
    """
    em = EmailMessage()

    # Pre-existing headers — parse with Python's email.parser so folded
    # multi-line values (e.g. Message-ID continued on next line) are joined
    # correctly. We copy the threading/routing headers verbatim and let
    # ourselves overwrite Subject/From/To/Cc below.
    raw_headers = data.get("transport_headers") or ""
    original_headers = HeaderParser().parsestr(raw_headers) if raw_headers else None
    if original_headers is not None:
        for name in _HEADER_PASSTHROUGH:
            val = original_headers.get(name)
            if val:
                try:
                    em[name] = val
                except Exception:
                    pass

    em["Subject"] = data.get("subject") or "(no subject)"
    sender_name = data.get("sender_name") or ""
    sender_email = data.get("sender_email") or ""
    if sender_email and sender_name:
        em["From"] = f'"{sender_name}" <{sender_email}>'
    elif sender_email:
        em["From"] = sender_email
    elif sender_name:
        em["From"] = sender_name

    # To/Cc/Bcc taken from the original headers if present — they preserve
    # display names and ordering better than anything we could reconstruct.
    if original_headers is not None:
        for name in ("To", "Cc", "Bcc"):
            val = original_headers.get(name)
            if val:
                try:
                    em[name] = val
                except Exception:
                    pass

    # Date: pst-extractor hands us ISO 8601 (e.g. 2025-01-28T20:18:00.000Z).
    # Convert to the RFC 5322 form most clients expect in a Date: header.
    when = data.get("delivery_time") or data.get("submit_time")
    if when:
        try:
            iso = when.replace("Z", "+00:00")
            em["Date"] = format_datetime(datetime.fromisoformat(iso))
        except Exception:
            try:
                em["Date"] = format_datetime(parsedate_to_datetime(when))
            except Exception:
                em["Date"] = when

    # Body — prefer the HTML form as the alternative since most modern clients
    # render that one. Always include plain text too so text-only clients
    # work.
    body_text = data.get("body_text") or ""
    body_html = data.get("body_html") or ""
    if not body_text and body_html:
        # Crude HTML→text fallback. Better-than-nothing for clients that only
        # show the plain part.
        body_text = re.sub(r"<[^>]+>", " ", body_html)
        body_text = re.sub(r"\s+", " ", body_text).strip()
    em.set_content(body_text or "(empty body)")
    if body_html:
        em.add_alternative(body_html, subtype="html")

    # Attachments
    for att in data.get("attachments") or []:
        content_b64 = att.get("content_base64") or ""
        if not content_b64:
            continue
        try:
            content = base64.b64decode(content_b64)
        except Exception:
            continue
        mime = att.get("mime") or "application/octet-stream"
        if "/" in mime:
            maintype, subtype = mime.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        em.add_attachment(
            content, maintype=maintype, subtype=subtype,
            filename=att.get("name") or "attachment.bin",
        )

    return em.as_bytes()


@app.get("/api/message/{message_id}/export.eml")
def api_export_eml(message_id: int) -> StreamingResponse:
    conn = dbmod.connect(_db_path())
    try:
        msg, _atts, pst = dbmod.get_message(conn, message_id)
        if msg is None or pst is None:
            raise HTTPException(status_code=404, detail="message not found")
        pst_path = pst["path"]
        pff_id = str(msg["pff_identifier"])
        subject = msg["subject"]
    finally:
        conn.close()

    if not Path(pst_path).exists():
        raise HTTPException(status_code=410, detail=f"source PST no longer at {pst_path}")

    try:
        data = pstmod.export_message(pst_path, pff_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"export failed: {e}")

    eml = _build_eml(data)
    filename = _safe_filename(subject, f"message_{message_id}") + ".eml"
    return StreamingResponse(
        io.BytesIO(eml),
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

class IndexOptions(BaseModel):
    """Per-scan settings the user can adjust when indexing a PST.

    All fields are optional — `None` means "use the extract.mjs default".
    Defaults match the values baked into extract.mjs and are documented in
    the README under Performance Notes.
    """
    include_body: bool | None = None       # PST_SEARCH_BODY (1/0)
    body_cap_bytes: int | None = None      # PST_SEARCH_BODY_CAP (default 32768)
    max_html_fetch_bytes: int | None = None  # PST_SEARCH_MAX_HTML_FETCH (default 4194304)


class IndexRequest(BaseModel):
    path: str
    options: IndexOptions | None = None


def _gnome_text_scaling() -> float | None:
    """Read GNOME's text-scaling-factor. Returns None on non-GNOME or any error.
    Used to size the Tk file picker on Linux, where Tk otherwise ignores the
    desktop's scaling and looks tiny on HiDPI displays."""
    try:
        out = subprocess.check_output(
            ["gsettings", "get", "org.gnome.desktop.interface", "text-scaling-factor"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode("utf-8", errors="replace").strip()
        val = float(out)
        return val if val > 0 else None
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
            FileNotFoundError, ValueError, OSError):
        return None


def _apply_tk_scaling(root) -> None:
    """Bump Tk's scaling factor on HiDPI Linux. Honors PSTSEARCH_TK_SCALING
    as an absolute override; otherwise multiplies Tk's auto-detected scaling
    by the GNOME text-scaling-factor when running on GNOME/Pop!_OS/Ubuntu."""
    override = os.environ.get("PSTSEARCH_TK_SCALING")
    if override:
        try:
            root.tk.call("tk", "scaling", float(override))
        except (ValueError, Exception):  # noqa: BLE001
            pass
        return
    if not sys.platform.startswith("linux"):
        return
    factor = _gnome_text_scaling()
    if not factor or factor <= 1.05:
        return
    try:
        current = float(root.tk.call("tk", "scaling"))
        root.tk.call("tk", "scaling", current * factor)
    except Exception:  # noqa: BLE001
        pass


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
        except ImportError:
            if sys.platform.startswith("linux"):
                hint = (
                    "On Debian/Ubuntu/Pop!_OS, run `sudo apt install python3-tk` "
                    "and restart the server."
                )
            elif sys.platform == "darwin":
                hint = (
                    "On macOS with Homebrew Python, run "
                    "`brew install python-tk@3.12` (match your Python version) "
                    "and restart the server."
                )
            else:
                hint = "Install a Python build that includes the tkinter stdlib."
            result["error"] = (
                "Native file picker unavailable — tkinter is not installed. "
                f"{hint} You can also paste a path into the field below."
            )
            return
        try:
            root = Tk()
            _apply_tk_scaling(root)
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
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/index")
def api_index(req: IndexRequest) -> dict:
    p = Path(req.path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=400, detail=f"file not found: {req.path}")
    if p.suffix.lower() != ".pst":
        raise HTTPException(status_code=400, detail="file must have .pst extension")
    opts = req.options.model_dump() if req.options else {}
    job = job_registry.start(str(p), _db_path(), options=opts)
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


@app.get("/api/settings")
def api_settings() -> dict:
    """Return the app-wide runtime settings — bind address, port, DB path.

    These are set at server start and require restart to change. The UI uses
    this to show informational text and an "Open data folder" button.
    """
    host = os.environ.get("PSTSEARCH_HOST", "127.0.0.1")
    port = int(os.environ.get("PSTSEARCH_PORT", "8765"))
    db_path = _db_path()
    return {
        "host": host,
        "port": port,
        "is_local_only": host in ("127.0.0.1", "localhost", "::1"),
        "db_path": str(db_path),
        "db_dir": str(db_path.parent),
    }


@app.post("/api/open-data-folder")
def api_open_data_folder() -> dict:
    """Open the index DB's parent folder in the OS file manager.

    Local-app convenience — the server is always running on the user's own
    machine, so spawning a file-manager process there does what they expect.
    """
    folder = _db_path().parent
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))   # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(folder)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"could not open folder: {e}")
    return {"opened": str(folder)}


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
