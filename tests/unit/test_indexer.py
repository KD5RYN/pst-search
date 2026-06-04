"""Indexer tests with a stubbed message stream (no Node, no PST file).

We monkeypatch pst.iter_messages to yield synthetic Message objects, so the
real index_pst -> db path is exercised end-to-end without the extractor.
"""
import pst_search.pst as pstmod
from pst_search import db as dbmod
from pst_search.indexer import index_pst


def _stub_stream(messages):
    def _iter(pst_path, options=None):
        yield from messages
    return _iter


def test_index_pst_inserts_messages_and_returns_count(tmp_path, monkeypatch, make_message):
    db_path = tmp_path / "idx.db"
    msgs = [
        make_message("1", subject="Alpha", body="first"),
        make_message("2", subject="Beta", body="second"),
    ]
    monkeypatch.setattr(pstmod, "iter_messages", _stub_stream(msgs))

    pst_id, indexed = index_pst("/fake/mail.pst", db_path)
    assert indexed == 2

    conn = dbmod.connect(db_path)
    rows, total = dbmod.search(conn, "", limit=10)
    assert total == 2
    assert {r["subject"] for r in rows} == {"Alpha", "Beta"}
    conn.close()


def test_index_pst_finalizes_message_count(tmp_path, monkeypatch, make_message):
    db_path = tmp_path / "idx.db"
    msgs = [make_message(str(i), subject=f"S{i}") for i in range(3)]
    monkeypatch.setattr(pstmod, "iter_messages", _stub_stream(msgs))

    pst_id, _ = index_pst("/fake/mail.pst", db_path)

    conn = dbmod.connect(db_path)
    psts = dbmod.list_psts(conn)
    row = next(p for p in psts if p["pst_id"] == pst_id)
    assert row["message_count"] == 3
    conn.close()


def test_index_pst_is_searchable_after_indexing(tmp_path, monkeypatch, make_message):
    db_path = tmp_path / "idx.db"
    msgs = [make_message("1", subject="Email Retention Policy", body="retention schedule")]
    monkeypatch.setattr(pstmod, "iter_messages", _stub_stream(msgs))
    index_pst("/fake/mail.pst", db_path)

    conn = dbmod.connect(db_path)
    # The documented behavior survives a real index roundtrip.
    assert dbmod.search(conn, "retent")[1] == 0
    assert dbmod.search(conn, "retent*")[1] == 1
    conn.close()


def test_reindex_replaces_previous_messages(tmp_path, monkeypatch, make_message):
    db_path = tmp_path / "idx.db"

    monkeypatch.setattr(pstmod, "iter_messages",
                        _stub_stream([make_message("1", subject="Old")]))
    index_pst("/fake/mail.pst", db_path)

    # Re-index the same path with a different message set.
    monkeypatch.setattr(pstmod, "iter_messages",
                        _stub_stream([make_message("2", subject="New")]))
    index_pst("/fake/mail.pst", db_path)

    conn = dbmod.connect(db_path)
    rows, total = dbmod.search(conn, "", limit=10)
    assert total == 1
    assert rows[0]["subject"] == "New"
    conn.close()
