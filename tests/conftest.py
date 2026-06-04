"""Shared fixtures for the test suite.

Everything here is hermetic: temp SQLite databases and synthetic Message
objects. No PST file and no Node runtime are required for the unit tests.
"""
from __future__ import annotations

import sqlite3

import pytest

from pst_search import db as dbmod
from pst_search.pst import Attachment, Message


def build_message(
    identifier: str,
    *,
    subject: str | None = None,
    sender_name: str | None = None,
    sender_email: str | None = None,
    recipients: str | None = None,
    delivery_time: str | None = None,
    submit_time: str | None = None,
    body: str | None = None,
    folder_path: str = "Top of Personal Folders/Inbox",
    attachments: list[Attachment] | None = None,
) -> Message:
    """Build a Message with sensible defaults so tests set only what they assert on."""
    return Message(
        identifier=identifier,
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        recipients=recipients,
        delivery_time=delivery_time,
        submit_time=submit_time,
        body=body,
        headers=None,
        folder_path=folder_path,
        attachments=attachments or [],
    )


@pytest.fixture
def make_message():
    """Factory fixture: hands tests the build_message() helper (no import path coupling)."""
    return build_message


@pytest.fixture
def db_path(tmp_path):
    """Filesystem path for a fresh SQLite DB (some code resolves real paths)."""
    return tmp_path / "index.db"


@pytest.fixture
def conn(db_path) -> sqlite3.Connection:
    """A connected DB with the schema applied and one registered PST."""
    c = dbmod.connect(db_path)
    yield c
    c.close()


@pytest.fixture
def pst_id(conn) -> int:
    return dbmod.register_pst(conn, "/fake/mailbox.pst")


def insert_all(conn, pst_id, messages):
    """Insert a list of Message objects and commit. Returns inserted row ids."""
    ids = [dbmod.insert_message(conn, pst_id, m) for m in messages]
    conn.commit()
    return ids


@pytest.fixture
def seeded_db(conn, pst_id):
    """A DB pre-loaded with a small, known corpus used across search tests.

    Subjects/bodies are chosen to exercise the documented matching rules,
    e.g. the "Email Retention Policy" subject for the whole-word/prefix tests.
    """
    messages = [
        build_message(
            "1",
            subject="Email Retention Policy",
            sender_name="Bob Jones",
            sender_email="bob@enron.com",
            recipients='To: "Alice Smith" <alice@enron.com>',
            delivery_time="2001-05-01T09:00:00",
            body="Please review the updated retention schedule.",
            folder_path="Top/Inbox",
            attachments=[Attachment(index=0, name="policy.pdf", size=2048)],
        ),
        build_message(
            "2",
            subject="Quarterly budget review",
            sender_name="Carol White",
            sender_email="carol@enron.com",
            recipients='To: "Bob Jones" <bob@enron.com>',
            delivery_time="2001-03-15T12:30:00",
            body="The Q4 numbers look strong.",
            folder_path="Top/Sent",
        ),
        build_message(
            "3",
            subject="Lunch?",
            sender_name="Alice Smith",
            sender_email="alice@enron.com",
            recipients='To: "Carol White" <carol@enron.com>; Cc: "Bob" <bob@enron.com>',
            delivery_time="2001-07-20T11:00:00",
            body="Want to grab lunch and talk about the meeting?",
            folder_path="Top/Inbox",
        ),
    ]
    insert_all(conn, pst_id, messages)
    return conn
