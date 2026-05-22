"""Command-line entry point.

  pstsearch index FILE.pst            -> index into the default DB
  pstsearch serve [--host --port]     -> launch web UI

The default DB lives at %APPDATA%\\pst-search\\index.db on Windows so multiple
PSTs can be indexed into one searchable library.
"""
from __future__ import annotations

import os
import sys
import time
import webbrowser
from pathlib import Path

import click
import uvicorn

from . import db as dbmod
from .indexer import index_pst


def default_db_path() -> Path:
    """Per-OS user data directory for the index DB.

      Windows : %APPDATA%\\pst-search\\index.db
      macOS   : ~/Library/Application Support/pst-search/index.db
      Linux   : $XDG_DATA_HOME/pst-search/index.db, falling back to
                ~/.local/share/pst-search/index.db
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    p = base / "pst-search" / "index.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@click.group()
@click.version_option(package_name="pst-search")
def main() -> None:
    """Local search engine for Outlook PST files."""


@main.command("index")
@click.argument("pst_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None,
              help="SQLite DB path (default: per-OS user data directory)")
@click.option("--no-body", is_flag=True, default=False,
              help="Skip message body extraction entirely. Subject/sender/folder are still indexed. "
                   "Dramatically faster on huge archives.")
@click.option("--body-cap", type=int, default=None, metavar="KB",
              help="Maximum body text stored per message, in KB. Default: 32.")
@click.option("--max-html-fetch", type=int, default=None, metavar="MB",
              help="Skip body fetch for messages larger than this, in MB. Default: 4.")
def cmd_index(pst_file: Path, db_path: Path | None,
              no_body: bool, body_cap: int | None, max_html_fetch: int | None) -> None:
    """Index a PST file. Re-running on the same file replaces its rows."""
    db_path = db_path or default_db_path()
    options: dict = {}
    if no_body:
        options["include_body"] = False
    if body_cap is not None:
        options["body_cap_bytes"] = body_cap * 1024
    if max_html_fetch is not None:
        options["max_html_fetch_bytes"] = max_html_fetch * 1024 * 1024
    click.echo(f"Indexing {pst_file}")
    click.echo(f"   into  {db_path}")
    if options:
        click.echo(f"   options: {options}")
    t0 = time.monotonic()
    last = [t0]

    def progress(done: int) -> None:
        now = time.monotonic()
        if now - last[0] >= 0.5:
            rate = done / max(now - t0, 0.001)
            click.echo(f"  {done:,} messages  ({rate:,.0f}/s)")
            last[0] = now

    try:
        pst_id, n = index_pst(pst_file, db_path, progress=progress, options=options)
    except Exception as e:
        click.secho(f"FAILED: {e}", fg="red", err=True)
        sys.exit(1)

    elapsed = time.monotonic() - t0
    click.secho(
        f"Indexed {n:,} messages in {elapsed:.1f}s  (pst_id={pst_id})",
        fg="green",
    )


@main.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None,
              help="SQLite DB path (default: %APPDATA%/pst-search/index.db)")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
def cmd_serve(host: str, port: int, db_path: Path | None, no_browser: bool) -> None:
    """Start the web UI."""
    db_path = db_path or default_db_path()
    # We no longer require an existing index — if the DB is missing we
    # initialize an empty one. The web UI shows a welcome screen with a
    # file picker for the user's first PST.
    if not db_path.exists():
        click.secho(f"Creating empty index at {db_path}", fg="yellow")
        dbmod.connect(db_path).close()
    os.environ["PSTSEARCH_DB"] = str(db_path)
    os.environ["PSTSEARCH_HOST"] = host
    os.environ["PSTSEARCH_PORT"] = str(port)
    url = f"http://{host}:{port}/"
    click.echo(f"Serving {db_path}")
    click.echo(f"   at  {url}")
    if not no_browser:
        # Small delay so uvicorn is listening before we open the browser.
        import threading
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run("pst_search.server:app", host=host, port=port, log_level="warning")


@main.command("list")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
def cmd_list(db_path: Path | None) -> None:
    """List indexed PSTs."""
    db_path = db_path or default_db_path()
    if not db_path.exists():
        click.echo("(no index yet)")
        return
    conn = dbmod.connect(db_path)
    try:
        rows = dbmod.list_psts(conn)
    finally:
        conn.close()
    if not rows:
        click.echo("(empty)")
        return
    for r in rows:
        click.echo(f"  [{r['pst_id']}] {r['message_count']:>7,} msgs  {r['indexed_at']}  {r['path']}")


if __name__ == "__main__":
    main()
