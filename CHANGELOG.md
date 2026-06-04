# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2026-06-04

### Added
- **Automated test suite** (`tests/`) with pytest: unit tests for the query
  translation, the FTS5 whole-word/prefix matching rules, structured filters,
  the indexer, and the job registry; plus an end-to-end integration test that
  indexes a committed slice of the public-record Enron corpus
  (`tests/fixtures/enron.pst`) through the real Node extractor.
- **CI** (`.github/workflows/test.yml`): runs the suite on every push and PR
  across Python 3.10–3.13.

### Fixed
- **Leading `*` in a search no longer errors.** Queries like `*retent*` or
  `*foo` (typed out of glob/LIKE habit) used to hit FTS5's special-query
  parser and fail with `unknown special query`. A leading `*` is now stripped,
  so `*retent*` is treated as the valid prefix query `retent*`, and a bare `*`
  falls back to browse. (There is still no substring/suffix matching — FTS5
  can't do it.)
- **Failed searches no longer show stale results.** On a search error the
  result list now clears and shows the error, instead of leaving the previous
  results on screen (which made a broken query look like it had succeeded).

### Docs
- Corrected the README and in-app cheatsheet: a leading `*` is ignored (not a
  substring match), and a trailing `*` is the only wildcard form.

## [1.1.0] - 2026-06-04

### Added
- **About section in Settings.** The Settings dialog (⚙️) now shows the running
  version, the MIT license (linked), a link back to the GitHub project, and a
  pointer to the third-party licenses. The version is served from the package's
  `__version__` via `/api/settings`, so it always reflects the installed build.
- **This changelog.**

### Fixed
- The FastAPI app version (and `/docs`) reported a hardcoded `0.1.0` regardless
  of the installed version; it now reads the real package version.
- The Add-PST options dialog opened *behind* the Manage PSTs modal (both shared
  one z-index, so DOM order won the paint-order tiebreak), making it look like
  adding a PST silently failed. The options dialog now stacks on top.

## [1.0.0] - 2026-06-04

First stable release. The index → search → retrieve core has been stable across
the 0.1.x line, so the package is now marked Production/Stable.

### Changed
- Promoted to 1.0.0 and flipped the package classifier from `3 - Alpha` to
  `5 - Production/Stable`.
- Modernized the release workflow off the deprecated Node 20 GitHub Actions
  (force-migrated by GitHub on 2026-06-16): `checkout` v4→v6,
  `setup-python` v5→v6, `upload-artifact` v4→v7, `download-artifact` v4→v8.
  The publish mechanism is unchanged — still PyPI Trusted Publishing via OIDC.

## [0.1.4] - 2026-06-04

### Changed
- Clarified search matching in the README and the in-app help: FTS5 matches
  whole words, so `retent` will not find "Retention" — use the prefix form
  `retent*`. Corrected the operator descriptions to say "has the word …"
  rather than "contains …", which had implied substring matching.

## [0.1.3] - 2026-06-03

### Fixed
- Auto-bump the Tk file-picker scaling on HiDPI Linux using a screen-width
  heuristic, so the "Add a PST" dialog is legible on high-resolution displays.

## [0.1.2] - 2026-06-03

### Added
- HiDPI-aware Tk file picker on Linux.

## [0.1.1] - 2026-06-03

### Fixed
- Handle the Linux `tkinter`-not-installed gap gracefully and offer a manual
  path-entry field so a PST can still be added without the native picker.

## [0.1.0] - 2026-06-03

### Added
- First public release: index Outlook PST files and search them locally over
  SQLite FTS5, with attachment retrieval on demand from the source PST.
- PyPI-publishable packaging metadata, a `pstsearch setup` command, and the
  tag-driven release workflow.

[1.1.0]: https://github.com/KD5RYN/pst-search/releases/tag/v1.1.0
[1.0.0]: https://github.com/KD5RYN/pst-search/releases/tag/v1.0.0
[0.1.4]: https://github.com/KD5RYN/pst-search/releases/tag/v0.1.4
[0.1.3]: https://github.com/KD5RYN/pst-search/releases/tag/v0.1.3
[0.1.2]: https://github.com/KD5RYN/pst-search/releases/tag/v0.1.2
[0.1.1]: https://github.com/KD5RYN/pst-search/releases/tag/v0.1.1
[0.1.0]: https://github.com/KD5RYN/pst-search/releases/tag/v0.1.0
