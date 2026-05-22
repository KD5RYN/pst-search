"""SQLite schema + queries.

Single DB file holds one or more indexed PSTs. The pst_files table maps an
integer pst_id to the absolute path of the source PST; messages reference
pst_id and a pff_identifier so we can later re-open the PST and pull
attachments on demand.

Search uses FTS5 over subject + body + from + recipients + folder. We use
the external-content pattern: the FTS5 virtual table indexes the same rows
that live in the messages table, without duplicating storage.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pst_files (
    pst_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    indexed_at  TEXT NOT NULL DEFAULT (datetime('now')),
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pst_id          INTEGER NOT NULL REFERENCES pst_files(pst_id) ON DELETE CASCADE,
    pff_identifier  INTEGER NOT NULL,
    folder_path     TEXT,
    subject         TEXT,
    sender_name     TEXT,
    sender_email    TEXT,
    recipients      TEXT,
    delivery_time   TEXT,
    submit_time     TEXT,
    body            TEXT,
    attachment_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(pst_id, pff_identifier)
);

CREATE INDEX IF NOT EXISTS idx_messages_pst ON messages(pst_id);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_email);
CREATE INDEX IF NOT EXISTS idx_messages_delivery ON messages(delivery_time);

CREATE TABLE IF NOT EXISTS attachments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id   INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    att_index    INTEGER NOT NULL,
    name         TEXT,
    size         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    subject, body, sender_name, sender_email, recipients, folder_path,
    content='messages', content_rowid='id',
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, subject, body, sender_name, sender_email, recipients, folder_path)
    VALUES (new.id, new.subject, new.body, new.sender_name, new.sender_email, new.recipients, new.folder_path);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, body, sender_name, sender_email, recipients, folder_path)
    VALUES('delete', old.id, old.subject, old.body, old.sender_name, old.sender_email, old.recipients, old.folder_path);
END;
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def speed_for_bulk_load(conn: sqlite3.Connection) -> None:
    """Tune the connection for write-heavy bulk loading.

    Trades durability for speed during indexing. Safe because indexing is
    re-runnable from the PST — if a power loss truncates the WAL we just
    re-index. Should be paired with a final commit() in the caller.
    """
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -65536")  # 64 MiB page cache


def register_pst(conn: sqlite3.Connection, path: str) -> int:
    """Insert or replace the pst_files row for `path`, return its pst_id."""
    cur = conn.execute("SELECT pst_id FROM pst_files WHERE path = ?", (path,))
    row = cur.fetchone()
    if row:
        # Re-indexing — wipe previous messages for this PST
        conn.execute("DELETE FROM messages WHERE pst_id = ?", (row["pst_id"],))
        conn.execute(
            "UPDATE pst_files SET indexed_at = datetime('now'), message_count = 0 WHERE pst_id = ?",
            (row["pst_id"],),
        )
        conn.commit()
        return row["pst_id"]
    cur = conn.execute("INSERT INTO pst_files(path) VALUES (?)", (path,))
    conn.commit()
    return cur.lastrowid


def insert_message(conn: sqlite3.Connection, pst_id: int, msg) -> int:
    """Insert a Message dataclass row + its attachments. Returns row id."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO messages
           (pst_id, pff_identifier, folder_path, subject, sender_name, sender_email,
            recipients, delivery_time, submit_time, body, attachment_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            pst_id,
            msg.identifier,
            msg.folder_path,
            msg.subject,
            msg.sender_name,
            msg.sender_email,
            msg.recipients,
            msg.delivery_time,
            msg.submit_time,
            msg.body,
            len(msg.attachments),
        ),
    )
    if cur.rowcount == 0:
        return 0
    message_row_id = cur.lastrowid
    if msg.attachments:
        conn.executemany(
            "INSERT INTO attachments(message_id, att_index, name, size) VALUES (?, ?, ?, ?)",
            [(message_row_id, a.index, a.name, a.size) for a in msg.attachments],
        )
    return message_row_id


def finalize_pst(conn: sqlite3.Connection, pst_id: int) -> None:
    conn.execute(
        """UPDATE pst_files SET message_count = (
               SELECT COUNT(*) FROM messages WHERE pst_id = ?
           ) WHERE pst_id = ?""",
        (pst_id, pst_id),
    )
    conn.commit()
    conn.execute("ANALYZE")


# Gmail/Outlook-style operator aliases. Users type the natural form on the
# left; we rewrite it to FTS5's column-restricted syntax before MATCH'ing.
# Multi-column aliases use parens + OR so they work inside larger expressions.
_OPERATOR_ALIASES: dict[str, list[str]] = {
    "from":    ["sender_email", "sender_name"],
    "to":      ["recipients"],
    "cc":      ["recipients"],
    "bcc":     ["recipients"],
    "subject": ["subject"],
    "body":    ["body"],
    "folder":  ["folder_path"],
}
# Match `op:value` where value is either an unquoted token (no spaces) or a
# quoted phrase. We deliberately allow @ . - _ etc. inside unquoted tokens —
# emails and folder paths are common targets.
_OPERATOR_RE = re.compile(
    r"\b(" + "|".join(_OPERATOR_ALIASES.keys()) + r"):(\"[^\"]+\"|\S+)",
    flags=re.IGNORECASE,
)


def translate_query(query: str) -> str:
    """Translate human-friendly operators into FTS5 column-restricted syntax.

    Examples:
        from:bob          -> (sender_email:bob OR sender_name:bob)
        to:alice          -> recipients:alice
        subject:"Q4 plan" -> subject:"Q4 plan"
        meeting AND from:bob NOT folder:trash
                          -> meeting AND (sender_email:bob OR sender_name:bob) NOT folder_path:trash

    Anything that doesn't match an alias passes through untouched — so
    native FTS5 syntax (AND/OR/NOT, quoted phrases, prefix*, parens) still
    works exactly as it did before.
    """
    def repl(m: re.Match) -> str:
        op = m.group(1).lower()
        val = m.group(2)
        # FTS5's parser only accepts alphanumeric+underscore in unquoted
        # values. Email addresses, folder paths, anything with dots / @ / -
        # has to be wrapped in double quotes. Already-quoted values pass
        # through untouched.
        if not (val.startswith('"') and val.endswith('"')):
            if not re.fullmatch(r"\w+", val):
                val = '"' + val.replace('"', '') + '"'
        cols = _OPERATOR_ALIASES[op]
        if len(cols) == 1:
            return f"{cols[0]}:{val}"
        return "(" + " OR ".join(f"{c}:{val}" for c in cols) + ")"
    return _OPERATOR_RE.sub(repl, query)


def search(
    conn: sqlite3.Connection,
    query: str | None,
    *,
    sender: str | None = None,
    recipient: str | None = None,
    folder: str | None = None,
    has_attachments: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[sqlite3.Row], int]:
    """Search or browse.

    With `query` set, runs an FTS5 MATCH and ranks by BM25; rows get a
    highlighted snippet. With `query` empty/None, returns plain messages
    filtered by the structured criteria, ordered by delivery_time DESC —
    this is the "browse a folder" path.
    """
    query = (query or "").strip()
    if query:
        return _search_fts(conn, query, sender=sender, recipient=recipient, folder=folder,
                           has_attachments=has_attachments,
                           date_from=date_from, date_to=date_to,
                           limit=limit, offset=offset)
    return _browse(conn, sender=sender, recipient=recipient, folder=folder,
                   has_attachments=has_attachments,
                   date_from=date_from, date_to=date_to,
                   limit=limit, offset=offset)


def _structured_filters(
    sender: str | None, recipient: str | None,
    folder: str | None, has_attachments: bool | None,
    date_from: str | None, date_to: str | None,
) -> tuple[list[str], list]:
    where: list[str] = []
    params: list = []
    if sender:
        where.append("(messages.sender_email LIKE ? OR messages.sender_name LIKE ?)")
        params += [f"%{sender}%", f"%{sender}%"]
    if recipient:
        where.append("messages.recipients LIKE ?")
        params.append(f"%{recipient}%")
    if folder:
        where.append("messages.folder_path LIKE ?")
        params.append(f"%{folder}%")
    if has_attachments is True:
        where.append("messages.attachment_count > 0")
    elif has_attachments is False:
        where.append("messages.attachment_count = 0")
    if date_from:
        where.append("messages.delivery_time >= ?")
        params.append(date_from)
    if date_to:
        where.append("messages.delivery_time <= ?")
        params.append(date_to)
    return where, params


def _search_fts(conn, query, *, sender, recipient, folder, has_attachments, date_from, date_to, limit, offset):
    where = ["messages_fts MATCH ?"]
    params: list = [translate_query(query)]
    extra_where, extra_params = _structured_filters(sender, recipient, folder, has_attachments, date_from, date_to)
    where.extend(extra_where)
    params.extend(extra_params)
    where_sql = " AND ".join(where)

    total = conn.execute(
        f"""SELECT COUNT(*) AS n
            FROM messages_fts
            JOIN messages ON messages.id = messages_fts.rowid
            WHERE {where_sql}""",
        params,
    ).fetchone()["n"]

    rows = conn.execute(
        f"""SELECT
                messages.id, messages.pst_id, messages.pff_identifier,
                messages.folder_path, messages.subject, messages.sender_name,
                messages.sender_email, messages.recipients, messages.delivery_time,
                messages.attachment_count,
                pst_files.path AS pst_path,
                snippet(messages_fts, 1, '<mark>', '</mark>', ' … ', 12) AS snippet,
                bm25(messages_fts) AS score
            FROM messages_fts
            JOIN messages ON messages.id = messages_fts.rowid
            JOIN pst_files ON pst_files.pst_id = messages.pst_id
            WHERE {where_sql}
            ORDER BY score
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    return rows, total


def _browse(conn, *, sender, recipient, folder, has_attachments, date_from, date_to, limit, offset):
    where, params = _structured_filters(sender, recipient, folder, has_attachments, date_from, date_to)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM messages{where_sql}", params
    ).fetchone()["n"]

    rows = conn.execute(
        f"""SELECT
                messages.id, messages.pst_id, messages.pff_identifier,
                messages.folder_path, messages.subject, messages.sender_name,
                messages.sender_email, messages.recipients, messages.delivery_time,
                messages.attachment_count,
                pst_files.path AS pst_path,
                COALESCE(substr(messages.body, 1, 200), '') AS snippet,
                NULL AS score
            FROM messages
            JOIN pst_files ON pst_files.pst_id = messages.pst_id
            {where_sql}
            ORDER BY messages.delivery_time DESC NULLS LAST, messages.id DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    return rows, total


def list_folders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """One row per distinct folder_path with its message count."""
    return conn.execute(
        """SELECT folder_path, COUNT(*) AS message_count
           FROM messages
           WHERE folder_path IS NOT NULL
           GROUP BY folder_path
           ORDER BY folder_path"""
    ).fetchall()


def get_message(conn: sqlite3.Connection, message_id: int) -> tuple[sqlite3.Row | None, list[sqlite3.Row], sqlite3.Row | None]:
    msg = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if msg is None:
        return None, [], None
    atts = conn.execute(
        "SELECT * FROM attachments WHERE message_id = ? ORDER BY att_index", (message_id,)
    ).fetchall()
    pst = conn.execute("SELECT * FROM pst_files WHERE pst_id = ?", (msg["pst_id"],)).fetchone()
    return msg, atts, pst


def list_psts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM pst_files ORDER BY indexed_at DESC").fetchall()
