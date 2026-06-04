"""Pure dict->Message mapping and option translation in pst.py.

No subprocess: these exercise the record-shaping helpers directly.
"""
import os

from pst_search.pst import _env_for_options, _format_recipients, _from_record


# ---- _format_recipients ---------------------------------------------------

def test_format_recipients_empty():
    assert _format_recipients([]) == ""


def test_format_recipients_groups_by_type():
    rs = [
        {"name": "Alice", "email": "alice@x.com", "type": 1},
        {"name": "Bob", "email": "bob@x.com", "type": 2},
    ]
    out = _format_recipients(rs)
    assert out == 'To: "Alice" <alice@x.com> | Cc: "Bob" <bob@x.com>'


def test_format_recipients_falls_back_to_name_or_email():
    assert _format_recipients([{"name": "", "email": "x@y.com", "type": 1}]) == "To: x@y.com"
    assert _format_recipients([{"name": "Solo", "email": "", "type": 1}]) == "To: Solo"
    assert _format_recipients([{"name": "", "email": "", "type": 1}]) == "To: (unknown)"


# ---- _from_record ---------------------------------------------------------

def test_from_record_full():
    rec = {
        "identifier": 2099,
        "subject": "Hi",
        "sender_name": "Bob",
        "sender_email": "bob@x.com",
        "recipients": [{"name": "Al", "email": "al@x.com", "type": 1}],
        "delivery_time": "2001-01-01T00:00:00",
        "folder_path": "Top/Inbox",
        "attachments": [{"index": 0, "name": "a.pdf", "size": "1024", "mime": "application/pdf"}],
    }
    m = _from_record(rec)
    assert m.identifier == "2099"          # coerced to str
    assert m.subject == "Hi"
    assert m.recipients == 'To: "Al" <al@x.com>'
    assert m.folder_path == "Top/Inbox"
    assert len(m.attachments) == 1
    assert m.attachments[0].size == 1024   # coerced to int


def test_from_record_empty_strings_become_none():
    m = _from_record({"identifier": "", "subject": "", "sender_email": ""})
    assert m.identifier == ""
    assert m.subject is None
    assert m.sender_email is None
    assert m.recipients is None
    assert m.folder_path == ""
    assert m.attachments == []


def test_from_record_attachment_index_defaults_to_position():
    rec = {"identifier": "1", "attachments": [{"name": "x"}, {"name": "y"}]}
    m = _from_record(rec)
    assert [a.index for a in m.attachments] == [0, 1]


# ---- _env_for_options -----------------------------------------------------

def test_env_for_options_none_returns_plain_environ():
    env = _env_for_options(None)
    assert env.get("PATH") == os.environ.get("PATH")
    assert "PST_SEARCH_BODY" not in env


def test_env_for_options_sets_only_chosen_vars():
    env = _env_for_options({"include_body": False})
    assert env["PST_SEARCH_BODY"] == "0"
    assert "PST_SEARCH_BODY_CAP" not in env


def test_env_for_options_numeric_vars():
    env = _env_for_options({
        "include_body": True,
        "body_cap_bytes": 65536,
        "max_html_fetch_bytes": 4194304,
    })
    assert env["PST_SEARCH_BODY"] == "1"
    assert env["PST_SEARCH_BODY_CAP"] == "65536"
    assert env["PST_SEARCH_MAX_HTML_FETCH"] == "4194304"
