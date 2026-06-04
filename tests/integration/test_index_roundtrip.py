"""End-to-end integration test against the committed Enron fixture.

This runs the *real* path: Node extract.mjs -> NDJSON -> indexer -> SQLite ->
search. It needs Node on PATH (the extractor's deps auto-install on first use,
and CI installs them explicitly). When Node is absent the whole module is
skipped so a bare `pytest` on a checkout without Node still passes.

Fixture: tests/fixtures/enron.pst — a slice of the public-record Enron corpus
(FERC release, no PII), the lokay-m mailbox: 71 messages across 5 folders.
"""
import shutil
from pathlib import Path

import pytest

from pst_search import db as dbmod
from pst_search.indexer import index_pst

FIXTURE = Path(__file__).parent.parent / "fixtures" / "enron.pst"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not on PATH"),
    pytest.mark.skipif(not FIXTURE.exists(), reason="enron.pst fixture missing"),
]

# Known shape of the fixture (discovered by indexing it once).
EXPECTED_MESSAGES = 71
EXPECTED_FOLDERS = 5


@pytest.fixture(scope="module")
def enron_db(tmp_path_factory):
    """Index the fixture once per module run into a temp DB."""
    db_path = tmp_path_factory.mktemp("enron") / "index.db"
    pst_id, indexed = index_pst(FIXTURE, db_path)
    conn = dbmod.connect(db_path)
    yield conn, pst_id, indexed
    conn.close()


def test_indexes_expected_message_count(enron_db):
    _, _, indexed = enron_db
    assert indexed == EXPECTED_MESSAGES


def test_message_count_persisted_on_pst_row(enron_db):
    conn, pst_id, _ = enron_db
    row = next(p for p in dbmod.list_psts(conn) if p["pst_id"] == pst_id)
    assert row["message_count"] == EXPECTED_MESSAGES


def test_folder_structure(enron_db):
    conn, _, _ = enron_db
    folders = dbmod.list_folders(conn)
    assert len(folders) == EXPECTED_FOLDERS
    # Real folder names from the lokay-m mailbox.
    names = " ".join(f["folder_path"] for f in folders)
    assert "Personal" in names
    assert "Sent Items" in names
    # Counts sum to the total message count.
    assert sum(f["message_count"] for f in folders) == EXPECTED_MESSAGES


def test_known_subject_is_searchable(enron_db):
    conn, _, _ = enron_db
    rows, total = dbmod.search(conn, "retention")
    assert total >= 1
    assert any(r["subject"] == "Email Retention Policy" for r in rows)


def test_whole_word_vs_prefix_on_real_data(enron_db):
    # The documented behavior, verified against the actual corpus the user hit.
    conn, _, _ = enron_db
    assert dbmod.search(conn, "retent")[1] == 0      # bare fragment -> nothing
    rows, total = dbmod.search(conn, "retent*")       # prefix -> the policy email
    assert total == 1
    assert rows[0]["subject"] == "Email Retention Policy"


def test_star_retent_star_works_on_real_data(enron_db):
    # Regression for the *retent* report: a leading '*' used to raise; it now
    # behaves like retent* and finds the policy email.
    conn, _, _ = enron_db
    rows, total = dbmod.search(conn, "*retent*")
    assert total == 1
    assert rows[0]["subject"] == "Email Retention Policy"


def test_attachments_extracted(enron_db):
    conn, _, _ = enron_db
    n = conn.execute("SELECT COUNT(*) AS n FROM attachments").fetchone()["n"]
    assert n > 0


def test_full_message_fetch(enron_db):
    conn, _, _ = enron_db
    rows, _ = dbmod.search(conn, "retent*")
    msg, atts, pst = dbmod.get_message(conn, rows[0]["id"])
    assert msg is not None
    assert msg["subject"] == "Email Retention Policy"
    assert pst is not None
