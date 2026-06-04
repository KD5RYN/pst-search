"""Unit tests for the Gmail-style operator translation (db.translate_query).

These pin the rewrite from human-friendly `op:value` syntax into FTS5
column-restricted syntax, and confirm native FTS5 passes through untouched.
"""
from pst_search.db import translate_query


def test_from_expands_to_both_sender_columns():
    assert translate_query("from:bob") == "(sender_email:bob OR sender_name:bob)"


def test_to_cc_bcc_map_to_recipients():
    assert translate_query("to:alice") == "recipients:alice"
    assert translate_query("cc:alice") == "recipients:alice"
    assert translate_query("bcc:alice") == "recipients:alice"


def test_single_column_operators():
    assert translate_query("subject:budget") == "subject:budget"
    assert translate_query("body:meeting") == "body:meeting"
    assert translate_query("folder:inbox") == "folder_path:inbox"


def test_quoted_phrase_passes_through():
    assert translate_query('subject:"Q4 plan"') == 'subject:"Q4 plan"'


def test_value_with_special_chars_gets_quoted():
    # Email addresses contain @ and . which FTS5 won't accept unquoted.
    assert translate_query("from:bob@enron.com") == (
        '(sender_email:"bob@enron.com" OR sender_name:"bob@enron.com")'
    )
    assert translate_query("folder:Top/Inbox") == 'folder_path:"Top/Inbox"'


def test_bare_word_value_stays_unquoted():
    # Pure \w+ values are safe for FTS5 and should not be wrapped.
    assert translate_query("subject:budget") == "subject:budget"


def test_operator_is_case_insensitive():
    assert translate_query("From:bob") == "(sender_email:bob OR sender_name:bob)"


def test_mixed_query_only_rewrites_operators():
    out = translate_query("meeting AND from:bob NOT folder:trash")
    assert out == (
        "meeting AND (sender_email:bob OR sender_name:bob) NOT folder_path:trash"
    )


def test_native_fts5_passes_through_untouched():
    # No operator aliases -> identical string out.
    for q in ["meet*", "a OR b", '"exact phrase"', "(a OR b) AND c", "retent*"]:
        assert translate_query(q) == q


def test_non_operator_colon_is_left_alone():
    # "time:" isn't a known alias, so it must not be rewritten.
    assert translate_query("time:1200") == "time:1200"


# ---- Leading-asterisk stripping ------------------------------------------

def test_leading_star_is_stripped_to_prefix():
    # *foo* -> foo* (the only valid wildcard form: trailing prefix).
    assert translate_query("*retent*") == "retent*"


def test_leading_star_without_trailing_becomes_whole_word():
    assert translate_query("*foo") == "foo"


def test_leading_star_stripped_per_term():
    assert translate_query("*foo *bar*") == "foo bar*"


def test_trailing_star_is_preserved():
    # A normal prefix query must be left untouched.
    assert translate_query("retent*") == "retent*"


def test_star_inside_quotes_is_left_alone():
    # The '*' here is part of a quoted phrase, not a leading wildcard.
    assert translate_query('"a*b"') == '"a*b"'
