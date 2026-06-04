"""Executable spec for the documented search-matching behavior.

This is the test that pins the README / in-app-cheatsheet claim: FTS5 matches
whole words, so a bare fragment does not match a longer word — you need the
prefix `*`. If someone "fixes" search to do substring matching, these tests
(and the docs) should be updated together, deliberately.
"""
from pst_search.db import search


def subjects(rows):
    return [r["subject"] for r in rows]


def test_whole_word_matches(seeded_db):
    rows, total = search(seeded_db, "retention")
    assert total == 1
    assert subjects(rows) == ["Email Retention Policy"]


def test_bare_fragment_does_not_match(seeded_db):
    # "retent" is not a whole token -> no hit. This is the surprising case
    # the docs now explain.
    rows, total = search(seeded_db, "retent")
    assert total == 0
    assert rows == []


def test_prefix_wildcard_matches_fragment(seeded_db):
    rows, total = search(seeded_db, "retent*")
    assert total == 1
    assert subjects(rows) == ["Email Retention Policy"]


def test_leading_wildcard_is_stripped_to_whole_word(seeded_db):
    # A leading '*' has no suffix-match power in FTS5; we strip it, so "*tention"
    # becomes a plain whole-word search for "tention" (which nothing matches).
    # The point: it returns cleanly instead of raising "unknown special query".
    rows, total = search(seeded_db, "*tention")
    assert total == 0
    assert rows == []


def test_star_retent_star_is_treated_as_prefix(seeded_db):
    # Regression: *retent* used to raise (FTS5 special-query syntax). We now
    # strip the leading '*', so it behaves exactly like the prefix query retent*.
    a, _ = search(seeded_db, "retent*")
    b, _ = search(seeded_db, "*retent*")
    assert subjects(a) == subjects(b) == ["Email Retention Policy"]


def test_bare_asterisk_falls_back_to_browse(seeded_db):
    # "*" alone has no searchable content after stripping -> browse all, no error.
    rows, total = search(seeded_db, "*")
    assert total == 3


def test_operator_from_matches_whole_word_not_substring(seeded_db):
    # from:bob matches the token "bob" (present in "bob@enron.com" because
    # unicode61 splits on @/.), but NOT a longer word like "bobby".
    rows, total = search(seeded_db, "from:bob")
    assert total == 1
    assert subjects(rows) == ["Email Retention Policy"]

    none, n = search(seeded_db, "from:bobby")
    assert n == 0


def test_implicit_and_requires_both_words(seeded_db):
    # Two bare words -> implicit AND. Only message 1 has both.
    rows, total = search(seeded_db, "retention policy")
    assert total == 1
    assert subjects(rows) == ["Email Retention Policy"]


def test_snippet_is_highlighted_for_body_hits(seeded_db):
    # The snippet() is built from the body column, so a term that appears in the
    # body gets <mark>-highlighted. ("schedule" is in message 1's body.)
    rows, _ = search(seeded_db, "schedule")
    assert rows
    assert "<mark>" in rows[0]["snippet"]
