"""JobRegistry lifecycle, with the indexer stubbed out.

start() spawns a real daemon thread, so we poll the job to completion with a
short timeout rather than sleeping a fixed amount.
"""
import time

import pytest

import pst_search.indexer as indexer_mod
from pst_search.jobs import IndexJob, JobRegistry


def _wait_for(job, *, statuses, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if job.status in statuses:
            return
        time.sleep(0.01)
    raise AssertionError(f"job stuck in status={job.status!r}")


def test_successful_job_transitions_to_done(tmp_path, monkeypatch):
    def fake_index(path, db_path, *, progress=None, options=None):
        if progress:
            progress(7)
        return 42, 7

    monkeypatch.setattr(indexer_mod, "index_pst", fake_index)

    reg = JobRegistry()
    job = reg.start("/fake/mail.pst", tmp_path / "idx.db")
    _wait_for(job, statuses={"done", "error"})

    assert job.status == "done"
    assert job.pst_id == 42
    assert job.indexed == 7
    assert job.error is None
    assert job.finished_at is not None


def test_failing_job_records_error(tmp_path, monkeypatch):
    def boom(path, db_path, *, progress=None, options=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(indexer_mod, "index_pst", boom)

    reg = JobRegistry()
    job = reg.start("/fake/mail.pst", tmp_path / "idx.db")
    _wait_for(job, statuses={"done", "error"})

    assert job.status == "error"
    assert "kaboom" in job.error
    assert "RuntimeError" in job.error


def test_registry_get_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer_mod, "index_pst",
                        lambda *a, **k: (1, 0))
    reg = JobRegistry()
    job = reg.start("/fake/mail.pst", tmp_path / "idx.db")
    _wait_for(job, statuses={"done", "error"})

    assert reg.get(job.id) is job
    assert job in reg.list()
    assert reg.get("no-such-id") is None


def test_job_to_dict_shape():
    job = IndexJob(id="abc", path="/x.pst")
    d = job.to_dict()
    assert d["id"] == "abc"
    assert d["status"] == "queued"
    assert "elapsed" in d
    # The threading.Event must not leak into the serialized form.
    assert "cancel_event" not in d
