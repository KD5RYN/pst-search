"""Structured filters, sorting, browse mode, and pagination for db.search."""
from pst_search.db import search


def subjects(rows):
    return [r["subject"] for r in rows]


# ---- Browse mode (empty query) -------------------------------------------

def test_browse_returns_all_newest_first(seeded_db):
    rows, total = search(seeded_db, "")
    assert total == 3
    # delivery_time DESC: 2001-07 (Lunch?), 2001-05 (Retention), 2001-03 (budget)
    assert subjects(rows) == ["Lunch?", "Email Retention Policy", "Quarterly budget review"]


def test_browse_oldest_first(seeded_db):
    rows, _ = search(seeded_db, "", sort="oldest")
    assert subjects(rows) == ["Quarterly budget review", "Email Retention Policy", "Lunch?"]


def test_browse_relevance_falls_back_to_newest(seeded_db):
    # relevance only makes sense for FTS; browse silently uses newest.
    rows, _ = search(seeded_db, "", sort="relevance")
    assert subjects(rows) == ["Lunch?", "Email Retention Policy", "Quarterly budget review"]


def test_unknown_sort_defaults_to_newest(seeded_db):
    rows, _ = search(seeded_db, "", sort="bogus")
    assert subjects(rows)[0] == "Lunch?"


# ---- Structured filters ---------------------------------------------------

def test_filter_by_folder(seeded_db):
    rows, total = search(seeded_db, "", folder="Inbox")
    assert total == 2
    assert set(subjects(rows)) == {"Email Retention Policy", "Lunch?"}


def test_filter_by_sender(seeded_db):
    rows, total = search(seeded_db, "", sender="carol")
    assert total == 1
    assert subjects(rows) == ["Quarterly budget review"]


def test_filter_by_recipient(seeded_db):
    rows, total = search(seeded_db, "", recipient="alice")
    assert total == 1
    assert subjects(rows) == ["Email Retention Policy"]


def test_filter_has_attachments_true(seeded_db):
    rows, total = search(seeded_db, "", has_attachments=True)
    assert total == 1
    assert subjects(rows) == ["Email Retention Policy"]


def test_filter_has_attachments_false(seeded_db):
    rows, total = search(seeded_db, "", has_attachments=False)
    assert total == 2
    assert "Email Retention Policy" not in subjects(rows)


def test_date_range_filter(seeded_db):
    rows, total = search(seeded_db, "", date_from="2001-04-01", date_to="2001-06-01")
    assert total == 1
    assert subjects(rows) == ["Email Retention Policy"]


def test_filter_combines_with_fts_query(seeded_db):
    # FTS query + structured filter together.
    rows, total = search(seeded_db, "meeting", folder="Inbox")
    assert total == 1
    assert subjects(rows) == ["Lunch?"]


# ---- Pagination -----------------------------------------------------------

def test_limit_and_offset(seeded_db):
    page1, total = search(seeded_db, "", limit=2, offset=0)
    page2, _ = search(seeded_db, "", limit=2, offset=2)
    assert total == 3
    assert len(page1) == 2
    assert len(page2) == 1
    # No overlap between pages.
    assert set(subjects(page1)).isdisjoint(subjects(page2))
