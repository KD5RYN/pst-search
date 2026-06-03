"""PST extraction driver.

We pivoted off pypff/libpff to pst-extractor (Node.js). Reasons documented in
the README under "Known limitations" — pypff can't read PSTs whose property
tables trigger a known unfixed bug, and pst-extractor (an independent codebase
ported from java-libpst) handles them. This module hides Node behind a Python
API that mirrors the old pypff one, so the indexer and server didn't need to
change in any structural way.

Two operations are exposed:

  iter_messages(pst_path)           -> yields Message objects from extract.mjs
  extract_attachment(pst_path, ...) -> returns (filename, bytes) from attachment.mjs
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


def _bundled_node_dir() -> Path:
    """Where the .mjs scripts and package.json ship inside the package."""
    return Path(__file__).parent / "node"


def _user_node_dir() -> Path:
    """Per-user fallback location for Node assets when the bundled dir
    isn't writable (typical of system-wide Python installs)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "pst-search" / "node"


def _node_install_dir() -> Path:
    """Choose where node_modules lives. Prefer next to the bundled .mjs
    files (Node's ESM resolver finds the sibling node_modules with no
    env tweaks); fall back to a per-user dir when site-packages is
    read-only."""
    bundled = _bundled_node_dir()
    try:
        bundled.mkdir(parents=True, exist_ok=True)
        probe = bundled / ".pstsearch-write-probe"
        probe.touch()
        probe.unlink()
        return bundled
    except OSError:
        return _user_node_dir()


def _resolve_node() -> str:
    """Return the absolute path to the Node.js interpreter.

    Search order:
      1. PSTSEARCH_NODE env var (full override — useful for non-standard installs)
      2. `node` on PATH (cross-platform — handles both `node.exe` and `node`)
    """
    env_node = os.environ.get("PSTSEARCH_NODE")
    if env_node and Path(env_node).exists():
        return env_node

    found = shutil.which("node")
    if found:
        return found

    raise RuntimeError(
        "Node.js was not found. Install Node 18+ from https://nodejs.org "
        "(or `brew install node` / `apt install nodejs`) and re-run, or set "
        "the PSTSEARCH_NODE environment variable to the absolute path of node."
    )


def ensure_node_deps(verbose: bool = True) -> Path:
    """Make sure pst-extractor (and friends) are installed under a
    node_modules sibling of the .mjs scripts. Returns the directory that
    holds both. Idempotent — a no-op after the first successful call.

    Raises RuntimeError with a user-actionable message if Node or npm is
    missing, or if `npm install` fails.
    """
    install_dir = _node_install_dir()
    marker = install_dir / "node_modules" / "pst-extractor" / "package.json"
    if marker.exists():
        return install_dir

    install_dir.mkdir(parents=True, exist_ok=True)

    bundled = _bundled_node_dir()
    if install_dir != bundled:
        for fname in ("package.json", "package-lock.json"):
            src = bundled / fname
            if src.exists():
                shutil.copy2(src, install_dir / fname)
        for mjs in bundled.glob("*.mjs"):
            shutil.copy2(mjs, install_dir / mjs.name)

    _resolve_node()  # fail fast with the friendly Node-missing message
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError(
            "npm was not found on PATH. npm ships with Node.js — install "
            "Node 18+ from https://nodejs.org and re-run `pstsearch setup`."
        )

    if verbose:
        print(f"Installing Node dependencies into {install_dir}", file=sys.stderr)
        print("(one-time, ~10-30 seconds)", file=sys.stderr)
    try:
        subprocess.run(
            [npm, "install", "--omit=dev", "--no-audit", "--no-fund"],
            cwd=str(install_dir),
            check=True,
            stdout=sys.stderr if verbose else subprocess.DEVNULL,
            stderr=sys.stderr,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"`npm install` failed (exit {e.returncode}) in {install_dir}. "
            "Re-run `pstsearch setup` after fixing the issue (often a network "
            "or proxy problem)."
        ) from e
    return install_dir


def _node_scripts_dir() -> Path:
    """Folder housing extract.mjs / attachment.mjs / node_modules.

    Triggers a one-time `npm install` if node_modules isn't there yet, so
    callers (indexer, attachment fetch, .eml export) Just Work after a
    bare `pip install`.
    """
    return ensure_node_deps()


@dataclass
class Attachment:
    index: int
    name: str | None
    size: int
    mime: str | None = None


@dataclass
class Message:
    identifier: str           # descriptor node id (string — values can exceed 32 bits)
    subject: str | None
    sender_name: str | None
    sender_email: str | None
    recipients: str | None    # joined "Name <addr>; ..." for FTS5 indexing
    delivery_time: str | None
    submit_time: str | None
    body: str | None
    headers: str | None
    folder_path: str
    attachments: list[Attachment] = field(default_factory=list)


def _format_recipients(rs: list[dict]) -> str:
    """[{name, email, type}] -> 'To: a <a@x>, b <b@x> | Cc: c <c@x>'"""
    if not rs:
        return ""
    buckets: dict[int, list[str]] = {}
    for r in rs:
        t = int(r.get("type", 0))
        name = (r.get("name") or "").strip()
        email = (r.get("email") or "").strip()
        if name and email:
            label = f'"{name}" <{email}>'
        else:
            label = name or email or "(unknown)"
        buckets.setdefault(t, []).append(label)
    parts: list[str] = []
    type_names = {1: "To", 2: "Cc", 3: "Bcc"}
    for t in sorted(buckets):
        name = type_names.get(t, f"Type{t}")
        parts.append(f"{name}: " + ", ".join(buckets[t]))
    return " | ".join(parts)


def _from_record(rec: dict) -> Message:
    return Message(
        identifier   = str(rec.get("identifier") or ""),
        subject      = rec.get("subject") or None,
        sender_name  = rec.get("sender_name") or None,
        sender_email = rec.get("sender_email") or None,
        recipients   = _format_recipients(rec.get("recipients") or []) or None,
        delivery_time= rec.get("delivery_time"),
        submit_time  = rec.get("submit_time"),
        body         = (rec.get("body") or None),
        headers      = rec.get("transport_headers") or None,
        folder_path  = rec.get("folder_path") or "",
        attachments  = [
            Attachment(
                index=int(a.get("index", i)),
                name=a.get("name") or None,
                size=int(a.get("size") or 0),
                mime=a.get("mime") or None,
            )
            for i, a in enumerate(rec.get("attachments") or [])
        ],
    )


def _env_for_options(options: dict | None) -> dict:
    """Translate the indexer's options dict into env vars extract.mjs reads.

    Only sets vars that the caller explicitly chose — anything left as None
    falls through to the defaults baked into extract.mjs.
    """
    env = os.environ.copy()
    if not options:
        return env
    if options.get("include_body") is not None:
        env["PST_SEARCH_BODY"] = "1" if options["include_body"] else "0"
    if options.get("body_cap_bytes") is not None:
        env["PST_SEARCH_BODY_CAP"] = str(int(options["body_cap_bytes"]))
    if options.get("max_html_fetch_bytes") is not None:
        env["PST_SEARCH_MAX_HTML_FETCH"] = str(int(options["max_html_fetch_bytes"]))
    return env


def iter_messages(pst_path: str | Path, options: dict | None = None) -> Iterator[Message]:
    """Stream messages from a PST via the Node extractor.

    Yields one Message per record. Raises RuntimeError if the subprocess fails
    to start or exits non-zero before emitting any data.
    """
    node = _resolve_node()
    script = _node_scripts_dir() / "extract.mjs"
    if not script.exists():
        raise RuntimeError(f"missing extract.mjs at {script}")

    proc = subprocess.Popen(
        [node, "--max-old-space-size=4096", str(script), str(pst_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_env_for_options(options),
    )

    # Drain stderr on a background thread so it doesn't deadlock the pipe
    # and so progress lines from Node surface to the user immediately.
    stderr_lines: list[str] = []
    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            if line.startswith("progress:"):
                # Mirror Node's own progress to the parent's stderr
                print("  (node)", line.rstrip(), file=sys.stderr, flush=True)
    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "msg":
                yield _from_record(rec)
    finally:
        proc.stdout.close()
        rc = proc.wait()
        t.join(timeout=5)
        if rc != 0:
            tail = "".join(stderr_lines)[-2000:]
            raise RuntimeError(f"extract.mjs exited {rc}. Last stderr:\n{tail}")


def export_message(pst_path: str | Path, descriptor_node_id: str) -> dict:
    """Return a full dump of a message — headers, both body forms, and every
    attachment's bytes — as a dict. Used to assemble a .eml export.
    """
    node = _resolve_node()
    script = _node_scripts_dir() / "message.mjs"
    if not script.exists():
        raise RuntimeError(f"missing message.mjs at {script}")
    proc = subprocess.Popen(
        [node, str(script), str(pst_path), str(descriptor_node_id)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(
            f"message.mjs failed (rc={proc.returncode}): {stderr.decode('utf-8', errors='replace')}"
        )
    import json
    return json.loads(stdout)


def extract_attachment(pst_path: str | Path, descriptor_node_id: str, attachment_index: int) -> tuple[str, bytes]:
    """Run attachment.mjs and return (filename, bytes)."""
    node = _resolve_node()
    script = _node_scripts_dir() / "attachment.mjs"
    if not script.exists():
        raise RuntimeError(f"missing attachment.mjs at {script}")

    proc = subprocess.Popen(
        [node, str(script), str(pst_path), str(descriptor_node_id), str(attachment_index)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"attachment.mjs failed (rc={proc.returncode}): {stderr.decode('utf-8', errors='replace')}"
        )

    # filename was emitted to stderr as "NAME: <filename>\n"
    name = f"attachment_{attachment_index}.bin"
    for raw in stderr.splitlines():
        s = raw.decode("utf-8", errors="replace")
        if s.startswith("NAME: "):
            name = s[len("NAME: "):].strip() or name
            break
    return name, stdout
