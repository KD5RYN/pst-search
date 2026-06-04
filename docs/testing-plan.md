# Testing build-out plan

Status: **proposed** (no automated tests exist yet as of v1.1.0).

This plan adds a real test suite to `pst-search`. Today there are zero tests,
no CI test job, and the sample PSTs (`sample.pst`, `enron.pst`, `email-out.pst`)
are gitignored and used only for manual checking. `pytest>=8` is already in the
`dev` optional-dependencies group, so the intent was scaffolded but never filled in.

## Goals

1. Cover the pure logic that has no external dependencies first — fast, hermetic,
   runs on any machine with no Node and no PST. This is where the recently-clarified
   search-matching behavior (`retent` vs `retent*`) should be pinned down.
2. Cover the HTTP API against a seeded in-memory/temp database.
3. Make the Node→indexer→search integration path testable with a *tiny committed
   fixture*, skipping cleanly when Node isn't installed.
4. Keep the big/private corpora (Enron, the 8.6 GB mailbox) as opt-in local-only
   targets, never committed.
5. Gate every push/PR with CI across supported Python versions.

## Layout

```
tests/
  conftest.py            # shared fixtures (temp db, seeded db, synthetic messages)
  unit/
    test_translate_query.py
    test_search_matching.py     # the FTS5 whole-word / prefix rules
    test_search_filters.py      # sender/recipient/folder/has_attachments/date/sort/paging
    test_browse.py
    test_indexer.py             # synthetic Message objects, no Node
    test_pst_records.py         # _from_record / _format_recipients / _env_for_options
    test_jobs.py                # JobRegistry lifecycle with a stubbed indexer
  api/
    test_settings_api.py        # /api/settings — version, license, repo_url, local-only flag
    test_search_api.py          # /api/search against a seeded db
    test_message_api.py         # /api/message, .eml export shape
  integration/
    test_index_roundtrip.py     # tiny fixture PST -> index -> search; skipif no Node
fixtures/
  tiny.pst               # purpose-built minimal PST (a few messages), committed
```

## Tiers (build in this order)

### Tier 1 — pure unit tests (no PST, no Node, no HTTP)
The highest value per line, and fully committable.

- **`translate_query()`** (`db.py:179`) — the Gmail-style operator translation:
  - `from:bob` -> `(sender_email:bob OR sender_name:bob)`
  - `to:`/`cc:`/`bcc:` -> `recipients:…`; `subject:`/`body:`/`folder:` mappings
  - quoted phrases pass through; values with `@ . -` get auto-quoted; `\w+` stays bare
  - native FTS5 (`AND`/`OR`/`NOT`, `meet*`, parens) passes through untouched
- **Search matching** — the behavior we documented. Seed a temp DB via
  `connect()` + `insert_message()` with a message subject "Email Retention Policy",
  then assert:
  - `retent` -> 0 hits (whole-word)
  - `retent*` -> 1 hit (prefix)
  - `retention` -> 1 hit
  - `*tention` -> 0 hits (no suffix wildcard)
  This test *is* the executable spec for the README/cheatsheet wording.
- **Structured filters & sort** (`search()` / `_structured_filters` / `_order_by_clause`)
  — sender, recipient, folder, `has_attachments`, `date_from/date_to`, `newest`/`oldest`/
  `relevance`, `limit`/`offset` paging, and the documented browse-mode fallback from
  `relevance` to `newest`.
- **Indexer** (`index_pst`, `db.py:115 insert_message`) — feed synthetic `Message`
  objects (a fake iterable, bypassing `pst.iter_messages`) and assert rows + FTS
  content land correctly, `finalize_pst` sets counts, body-cap options are honored.
- **PST record mapping** (`pst.py` `_from_record`, `_format_recipients`,
  `_env_for_options`) — pure dict->Message transforms; no subprocess.
- **Jobs** (`JobRegistry`, `jobs.py`) — monkeypatch the indexer to a no-op/raising
  stub and assert status transitions (running -> done / error) and `to_dict()` shape.

Fixtures in `conftest.py`:
- `temp_db` — `connect()` against a `tmp_path` file (or `:memory:`), schema created.
- `seeded_db` — `temp_db` + a known set of synthetic messages for search/browse asserts.
- `synthetic_messages` — a small list of `Message`-shaped objects.

### Tier 2 — API tests (HTTP, seeded DB, no Node)
Requires `httpx` for Starlette's `TestClient` — **add `httpx` to the `dev` extra**
(it is not currently installed; the smoke test during 1.1.0 had to call the
endpoint function directly because of this).

- Point `PSTSEARCH_DB` at a `seeded_db`, build `TestClient(app)`.
- `/api/settings` returns `version == pst_search.__version__`, `license`, `repo_url`,
  `license_url`, and the correct `is_local_only` flag for `127.0.0.1` vs `0.0.0.0`.
- `/api/search` honors query + filters + paging and returns highlighted snippets.
- `/api/folders`, `/api/psts`, `/api/message/{id}` happy paths and 404s.
- `.eml` export endpoint returns a well-formed message (parse it back with
  `email.parser`), without needing a real PST for the header path.

### Tier 3 — integration (tiny fixture PST + Node)
- Commit `fixtures/tiny.pst`: a purpose-built minimal PST (a handful of messages,
  a couple of folders, one attachment). Must be small (<~100 KB) and safe to
  redistribute — synthetic content, not Enron.
- `test_index_roundtrip.py`: run the real `pst.iter_messages` -> `index_pst` ->
  `search()` path. `pytest.mark.skipif` when Node or `pst_search/node/node_modules`
  is absent, so the suite still passes on a bare checkout.
- **Enron / large mailbox**: opt-in only. If `PSTSEARCH_TEST_PST` env var points at
  a local PST, run an extra smoke test against it; otherwise skip. Never committed,
  matches the existing `*.pst` gitignore.

### Tier 4 — CI
Add `.github/workflows/test.yml` (separate from the tag-driven `release.yml`):
- Triggers: `push` and `pull_request`.
- Matrix: Python 3.10 / 3.11 / 3.12 / 3.13 on `ubuntu-latest`.
- Steps: checkout, setup-python, `pip install -e .[dev]`, `pytest`.
- One job sets up Node (`actions/setup-node`) + `npm ci` in `pst_search/node` so the
  Tier-3 integration test actually runs in CI; the others exercise Tiers 1–2 only.
- Use the same modern action majors as `release.yml` (checkout v6, setup-python v6).
- Optional: a coverage gate (`pytest --cov=pst_search`) once the suite stabilizes.

## Packaging / config changes
- `[tool.pytest.ini_options]` in `pyproject.toml`: `testpaths = ["tests"]`,
  sensible `addopts`.
- Add `httpx` (and `pytest-cov` if we want coverage) to the `dev` extra.
- Tests live outside the wheel (`tests/` is not under `pst_search/`), so packaging
  is unaffected; `fixtures/tiny.pst` is committed but excluded from the sdist/wheel.

## Suggested sequencing
1. **Now (fold into 1.1.0 or a fast-follow):** Tier 1 + Tier 4 (unit tests + CI).
   Fully committable, no binary fixtures, and immediately protects the search logic.
2. **Next:** Tier 2 (API), once `httpx` is added to dev deps.
3. **Follow-up:** Tier 3 (commit a tiny fixture PST, wire the Node-enabled CI job,
   add the opt-in Enron target).

## Open questions
- Build vs. find a tiny redistributable fixture PST? (`pst-extractor` is read-only,
  so we can't author a PST with it — we'd need a real-but-trivial PST or a small
  generator.) Until then, Tier 3 can `skipif` the fixture is missing.
- Coverage threshold — start reporting-only, enforce a floor later.
