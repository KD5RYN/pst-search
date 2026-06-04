"""HTTP API tests via Starlette's TestClient against a seeded temp DB.

These exercise the FastAPI layer end-to-end (routing, query params, status
codes, JSON shapes) without Node or a real PST. The DB is seeded with the
sample corpus from conftest. No tests here hit endpoints that spawn the Node
extractor (.eml export, attachment bytes, indexing) — those are covered by the
integration test.
"""


def subjects(results):
    return [r["subject"] for r in results]


# ---- root + settings ------------------------------------------------------

def test_root_serves_html(api_client):
    r = api_client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title" in r.text.lower()


def test_settings_reports_version_and_about(api_client):
    from pst_search import __version__

    r = api_client.get("/api/settings")
    assert r.status_code == 200
    s = r.json()
    assert s["version"] == __version__
    assert s["license"] == "MIT"
    assert s["repo_url"].endswith("/pst-search")
    assert s["license_url"].endswith("/LICENSE")
    assert s["is_local_only"] is True


# ---- search ---------------------------------------------------------------

def test_search_browse_mode_lists_all(api_client):
    r = api_client.get("/api/search")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["results"]) == 3


def test_search_query_matches(api_client):
    r = api_client.get("/api/search", params={"q": "retention"})
    body = r.json()
    assert body["total"] == 1
    assert subjects(body["results"]) == ["Email Retention Policy"]


def test_search_leading_star_works_via_api(api_client):
    # Regression: *retent* used to return HTTP 400 (FTS5 special query). The
    # leading '*' is now stripped, so the API returns 200 with the prefix hit.
    r = api_client.get("/api/search", params={"q": "*retent*"})
    assert r.status_code == 200
    assert subjects(r.json()["results"]) == ["Email Retention Policy"]


def test_search_invalid_query_returns_400(api_client):
    # A genuinely malformed FTS5 query (dangling NOT) is surfaced as a 400,
    # not a 500.
    r = api_client.get("/api/search", params={"q": "NOT"})
    assert r.status_code == 400
    assert "search error" in r.json()["detail"]


def test_search_filters_and_paging(api_client):
    r = api_client.get("/api/search", params={"folder": "Inbox", "limit": 1, "offset": 0})
    body = r.json()
    assert body["total"] == 2          # two messages in an Inbox folder
    assert len(body["results"]) == 1   # but only one returned this page
    assert body["limit"] == 1


def test_search_has_attachments_filter(api_client):
    r = api_client.get("/api/search", params={"has_attachments": "true"})
    body = r.json()
    assert body["total"] == 1
    assert subjects(body["results"]) == ["Email Retention Policy"]


def test_search_limit_is_bounded(api_client):
    # limit has le=200; over-limit should be a 422 validation error.
    r = api_client.get("/api/search", params={"limit": 9999})
    assert r.status_code == 422


# ---- folders + psts -------------------------------------------------------

def test_folders_lists_distinct_folders(api_client):
    r = api_client.get("/api/folders")
    assert r.status_code == 200
    folders = r.json()["folders"]
    paths = {f["folder_path"] for f in folders}
    assert paths == {"Top/Inbox", "Top/Sent"}
    inbox = next(f for f in folders if f["folder_path"] == "Top/Inbox")
    assert inbox["message_count"] == 2


def test_psts_lists_registered_pst(api_client):
    r = api_client.get("/api/psts")
    assert r.status_code == 200
    psts = r.json()["psts"]
    assert len(psts) == 1
    assert psts[0]["path"].endswith("mailbox.pst")
    assert psts[0]["message_count"] == 3


# ---- message detail -------------------------------------------------------

def test_message_detail_happy_path(api_client):
    # Find the retention message id via search, then fetch its detail.
    sid = api_client.get("/api/search", params={"q": "retention"}).json()["results"][0]["id"]
    r = api_client.get(f"/api/message/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["message"]["subject"] == "Email Retention Policy"
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["name"] == "policy.pdf"
    assert body["pst"]["path"].endswith("mailbox.pst")


def test_message_detail_404(api_client):
    r = api_client.get("/api/message/999999")
    assert r.status_code == 404
    assert r.json()["detail"] == "message not found"


# ---- jobs -----------------------------------------------------------------

def test_jobs_list_is_present(api_client):
    r = api_client.get("/api/jobs")
    assert r.status_code == 200
    assert "jobs" in r.json()


def test_unknown_job_returns_404(api_client):
    r = api_client.get("/api/jobs/does-not-exist")
    assert r.status_code == 404
    assert r.json()["detail"] == "job not found"
