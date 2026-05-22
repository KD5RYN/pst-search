# PST Search

A local search engine for Outlook PST files. Index once, then search by subject, body, sender, recipients, folder, or date — and pull attachments directly from the source PST on demand. Built around SQLite FTS5 for instant full-text search.

![PST Search UI — folder tree, search results, message detail](docs/screenshot.png)

## Why this exists

`libpff` (the standard PST reader used by most Python tools) has a long-standing unfixed bug — `libpff_table_read: invalid table - missing data identifier` — that makes it unable to read certain real-world PSTs, especially those produced by recent Outlook versions. We hit that on a real 8GB mailbox: libpff couldn't read a single message. `pst-search` uses an independent codebase (`pst-extractor`, a Node.js port of `java-libpst`) and reads PSTs that libpff cannot.

## Features

- **Full-text search** across subject, body, sender, recipients, and folder path. FTS5-ranked, with `<mark>`-highlighted snippets.
- **Browse mode** — leave the search box empty to list messages newest-first; click any folder in the tree to filter to it.
- **Filters**: from, folder, date range, has-attachments.
- **Lazy attachments**: the index stores only filenames and sizes. Clicking an attachment re-opens the PST and extracts that one file on demand. No multi-GB attachment dump on disk.
- **Multiple PSTs** in one index. Re-indexing a PST replaces its rows in place.
- **Local-only**: everything runs on `127.0.0.1`. No data leaves your machine.

## Quick start

### Prerequisites (one-time per machine)

The app needs Python and Node.js at runtime. **Git is not required** — you can either `git clone` or just download the source as a ZIP.

| | Windows | macOS | Linux (Ubuntu/Debian) |
| --- | --- | --- | --- |
| Python 3.10+ | `winget install Python.Python.3.12` | `brew install python@3.12` | `sudo apt install python3 python3-pip python3-tk python3-venv` |
| Node.js 18+ | `winget install OpenJS.NodeJS.LTS` | `brew install node` | `sudo apt install nodejs npm` |

> **macOS Homebrew users**: also run `brew install python-tk@3.12` so the file picker dialog works. (The python.org installer includes it already.)

### Get the source

Either:

```bash
# If you have git installed:
git clone https://github.com/KD5RYN/pst-search
cd pst-search
```

…or **download as a ZIP** from <https://github.com/KD5RYN/pst-search> (green **Code** button → **Download ZIP**), then unzip and `cd` into the folder.

### Install

```bash
# macOS / Linux:
./bootstrap.sh

# Windows:
pwsh ./bootstrap.ps1
```

Each bootstrap runs `pip install -e .` and `npm install` in the right places.

### Run

```bash
pstsearch serve
```

A browser tab opens at <http://127.0.0.1:8765>. Click **Manage PSTs → Add another PST**, pick your `.pst` file, and indexing starts. When it's done, search.

The search index lives in your per-user data directory:

- Windows: `%APPDATA%\pst-search\index.db`
- macOS: `~/Library/Application Support/pst-search/index.db`
- Linux: `$XDG_DATA_HOME/pst-search/index.db` (default `~/.local/share/pst-search/index.db`)

Delete that file to wipe the index and start over.

## Commands

```
pstsearch serve [--host --port --db]    # launch the web UI (the normal entry point)
pstsearch index FILE.pst [--db PATH]    # index a PST from the command line
pstsearch list                          # show indexed PSTs
```

## Architecture

```
PST file --[Node + pst-extractor]--NDJSON--> Python indexer --[SQLite + FTS5]--> Search API --[HTML/JS]--> Browser
                                                                                       |
                                                                              (on attachment click,
                                                                               spawn Node, extract
                                                                               one attachment by
                                                                               descriptor node ID)
```

| Layer | File | Purpose |
| --- | --- | --- |
| PST extractor | `pst_search/node/extract.mjs` | Walks the PST with `pst-extractor`, streams one NDJSON record per message to stdout. |
| Attachment extractor | `pst_search/node/attachment.mjs` | Pulls a single attachment's bytes from a PST by descriptor node ID. |
| Python driver | `pst_search/pst.py` | Spawns Node, parses NDJSON, exposes Python iterators and an attachment-fetch function. |
| Indexer | `pst_search/indexer.py` | Consumes the message stream and bulk-inserts into SQLite. |
| Database | `pst_search/db.py` | Schema + FTS5 virtual table + search/browse queries. |
| Server | `pst_search/server.py` | FastAPI endpoints: `/api/search`, `/api/folders`, `/api/message/{id}`, `/api/attachment/{msg}/{idx}`. |
| Web UI | `pst_search/web/index.html` | Single-file frontend (HTML + inline CSS + JS), no build step. |
| CLI | `pst_search/cli.py` | `index` / `serve` / `list` entry points. |

## Performance notes

- Indexing throughput is ~35 messages/sec end-to-end on a typical desktop. An 8GB / 27K-message PST takes ~13 minutes.
- The Node side caps stored body text at 32 KB per message (configurable via `PST_SEARCH_BODY_CAP`). 32 KB is roughly 5,000+ words — well past the length of normal correspondence.
- For genuinely enormous messages (over 4 MB total), the HTML body fetch is skipped to keep indexing predictable (`PST_SEARCH_MAX_HTML_FETCH`). On a typical mailbox this affects far less than 1% of messages. Subject, sender, recipients, and folder are always indexed.
- Recipients are parsed from `transportMessageHeaders` instead of `pst-extractor`'s `getRecipient()` API. The API call hits disk per recipient and dominates indexing time on big PSTs (measured 120 ms/message vs effectively free for header parsing).

## Building a standalone .exe (Windows only, optional)

```pwsh
pwsh ./build_exe.ps1
```

Output: `dist/pst-search/pst-search.exe` — a one-folder distribution that includes Python and the Node runtime. End users running the `.exe` need nothing else installed.

## License

`pst-search` is MIT-licensed (see `LICENSE`). Third-party dependencies and their licenses are listed in `THIRD_PARTY_LICENSES.md`.

## Known limitations

- **Search folders are skipped.** Some PSTs have internal "search root" folders (`SPAM Search Folder 2`, `ItemProcSearch`, etc.) that contain search caches rather than user mail; `pst-extractor` can't enumerate them and we explicitly skip them. No real mail is missed.
- **Body text is capped at 32 KB per message.** Most emails fit well under this; marketing emails with hundreds of KB of HTML get truncated, but the useful content (greeting, offer, call-to-action) is always in the first few KB. Tunable via `PST_SEARCH_BODY_CAP`.
- **Bodies are skipped for messages larger than 4 MB.** This affects the rare giant message (e.g., one with embedded multi-MB inline images). Their subject/sender/recipients/folder are still indexed. The detail pane shows "(empty body)" for those. Tunable via `PST_SEARCH_MAX_HTML_FETCH`.
- **No incremental indexing.** Re-running `index` on the same PST replaces all its rows. Fine for static archives; not designed for live mailboxes.

