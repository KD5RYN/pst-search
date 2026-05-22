# PST Search

A local search engine for Outlook PST files. Index once, then search by subject, body, sender, recipients, folder, or date — and pull attachments directly from the source PST on demand. Built around SQLite FTS5 for instant full-text search.

![PST Search UI — folder tree, search results, message detail](docs/screenshot.png)

## Why this exists

`libpff` (the standard PST reader used by most Python tools) has a long-standing unfixed bug — `libpff_table_read: invalid table - missing data identifier` — that makes it unable to read certain real-world PSTs, especially those produced by recent Outlook versions. We hit that on a real 8GB mailbox: libpff couldn't read a single message. `pst-search` uses an independent codebase (`pst-extractor`, a Node.js port of `java-libpst`) and reads PSTs that libpff cannot.

## Features

- **Full-text search** across subject, body, sender, recipients, and folder path. FTS5-ranked, with `<mark>`-highlighted snippets.
- **Gmail-style operators** in the search box: `from:bob`, `to:alice`, `subject:budget`, `body:meeting`, `folder:inbox`, combined with `AND`/`OR`/`NOT`, quoted phrases, prefix matching (`meet*`), and parentheses. Click the **?** next to the search box for the full cheatsheet.
- **Browse mode** — leave the search box empty to list messages newest-first; click any folder in the tree to filter to it.
- **Sort by date or relevance** — dropdown in the result-list header switches between Newest first (default), Oldest first, and Relevance (BM25 ranking for search queries).
- **Filters**: from, to, folder, date range, has-attachments.
- **Lazy attachments**: the index stores only filenames and sizes. Clicking an attachment re-opens the PST and extracts that one file on demand. No multi-GB attachment dump on disk.
- **Export to `.eml`**: every message has a Download button that produces a standard RFC 5322 `.eml` file with headers, body (plain + HTML), and all attachments. Opens in Outlook, Thunderbird, Apple Mail, or any webmail upload.
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

Two commands — same on every OS:

```bash
pip install -e .
(cd pst_search/node && npm install)
```

On Windows PowerShell the second line is:

```pwsh
cd pst_search\node; npm install; cd ..\..
```

### Run

```bash
pstsearch serve
```

A browser tab opens at <http://127.0.0.1:8765>.

1. Click **📁 Manage PSTs → + Add another PST**
2. Pick your `.pst` file in the native dialog
3. **Adjust indexing options** (or accept defaults) and click **Start indexing**
4. Search as soon as the first batch lands; the rest streams in behind you

When it's done, search.

The search index lives in your per-user data directory:

- Windows: `%APPDATA%\pst-search\index.db`
- macOS: `~/Library/Application Support/pst-search/index.db`
- Linux: `$XDG_DATA_HOME/pst-search/index.db` (default `~/.local/share/pst-search/index.db`)

Delete that file to wipe the index and start over.

## Search syntax

The search box accepts the same operators most users already know from Gmail and Outlook, plus all of SQLite FTS5's native query language.

**Operators:**

| Type | Means |
| --- | --- |
| `from:bob` | sender name or email contains "bob" |
| `to:alice` | any recipient (To/Cc/Bcc) contains "alice" |
| `subject:budget` | match restricted to the subject |
| `body:meeting` | match restricted to the body |
| `folder:inbox` | folder path contains "inbox" |
| `cc:` / `bcc:` | recipients (we don't distinguish To/Cc/Bcc) |

**Combining:**

| Form | Means |
| --- | --- |
| `a b` | both words present (implicit AND) |
| `a AND b` | both — explicit |
| `a OR b` | either |
| `a NOT b` | a but not b |
| `"q4 plan"` | exact phrase |
| `meet*` | prefix — matches meeting, meetup, meets, … |
| `(a OR b) AND c` | group with parens |

**Example:** `from:bob AND subject:budget NOT folder:trash` — emails from Bob about budgets that aren't in any trash folder.

Click the **?** icon at the right edge of the search box for a popup version of this cheatsheet.

## Indexing options

The "Add a PST" dialog and the `pstsearch index` CLI command both expose the same three knobs. Defaults work for almost every mailbox; tweak them only when the defaults don't fit your data.

| Option | GUI label | CLI flag | Default | When to change |
| --- | --- | --- | --- | --- |
| Include message bodies | _Index message bodies_ (checkbox) | `--no-body` | on | Off for **huge archives** when you only need to search by subject/sender — indexing becomes dramatically faster. |
| Max body length kept | _Max body length per message_ | `--body-cap KB` | 32 KB | Raise (up to 1024 KB) if your real-content emails routinely run longer; lower to shrink the index. |
| Skip body for very large messages | _Skip bodies larger than_ | `--max-html-fetch MB` | 4 MB | Lower if you want to ignore giant newsletter-style mail; raise toward 100 MB if you specifically want body text from huge messages too. |

Open the **Advanced options** disclosure in the Add-PST dialog to see and adjust the last two.

## App settings (⚙️ button)

Click the gear icon in the header to see what the server is currently doing:

- **Listening at** — the URL the server is bound to
- **Network access** — confirms whether you're local-only or exposed
- **Index database** — where the SQLite file lives, with an **Open data folder** button

These are read-only because changing them requires restarting the server. To change them, pass flags to `pstsearch serve` (see below).

## Commands

```
pstsearch serve  [--host HOST] [--port PORT] [--db PATH] [--no-browser]
    Launch the web UI. Defaults: --host 127.0.0.1 --port 8765.
    Pass --host 0.0.0.0 to expose to your LAN (DO NOT do this on an
    untrusted network — anyone reaching the port can search your mail).

pstsearch index FILE.pst
                 [--no-body]
                 [--body-cap KB]
                 [--max-html-fetch MB]
                 [--db PATH]
    Index a PST from the command line. Re-running on the same file
    replaces its rows. Options mirror the GUI Add-PST dialog.

pstsearch list
    Show indexed PSTs (id, message count, path, indexed-at).
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
| Message dump | `pst_search/node/message.mjs` | Full message export (headers + both body forms + every attachment) for `.eml` building. |
| Python driver | `pst_search/pst.py` | Spawns Node, parses NDJSON, exposes Python iterators, attachment fetch, and full-message export. |
| Indexer | `pst_search/indexer.py` | Consumes the message stream and bulk-inserts into SQLite. |
| Indexing jobs | `pst_search/jobs.py` | Background indexing thread + job registry. Lets the web UI fire off a scan and poll for progress. |
| Database | `pst_search/db.py` | Schema + FTS5 virtual table + search/browse queries + Gmail-style operator translation. |
| Server | `pst_search/server.py` | FastAPI endpoints — see below. |
| Web UI | `pst_search/web/index.html` | Single-file frontend (HTML + inline CSS + JS), no build step. |
| CLI | `pst_search/cli.py` | `index` / `serve` / `list` entry points. |

**HTTP API:**

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/search` | GET | FTS5 search with filters + sort. |
| `/api/folders` | GET | Distinct folder paths and message counts (for the tree). |
| `/api/psts` | GET | List of indexed PSTs. |
| `/api/psts/{pst_id}` | DELETE | Remove a PST from the index. |
| `/api/pick-pst` | POST | Open a native OS file picker dialog and return the chosen path. |
| `/api/index` | POST | Start a background indexing job. Body: `{path, options?}`. |
| `/api/jobs` / `/api/jobs/{id}` | GET | Job progress polling. |
| `/api/settings` | GET | Runtime config (host, port, db path, local-only flag). |
| `/api/open-data-folder` | POST | Open the index DB folder in the OS file manager. |
| `/api/message/{id}` | GET | Message metadata + attachment list. |
| `/api/message/{id}/export.eml` | GET | Download the message as a standard `.eml` file. |
| `/api/attachment/{msg}/{idx}` | GET | Stream one attachment's bytes from the source PST. |

## Performance notes

- Indexing throughput is ~35 messages/sec end-to-end on a typical desktop. An 8GB / 27K-message PST takes ~13 minutes with default options.
- Default body cap is 32 KB per message — roughly 5,000+ words, well past the length of normal correspondence. Marketing emails with hundreds of KB of HTML are truncated, but the useful content (greeting, offer, call-to-action) is always in the first few KB. Tune in the Add-PST dialog or via `--body-cap KB`.
- By default, messages larger than 4 MB total skip body extraction entirely (subject/sender/recipients/folder still indexed). On a typical mailbox this affects well under 1% of messages. Tune via `--max-html-fetch MB`.
- Skipping body extraction altogether (`--no-body` or unchecking _Index message bodies_) makes indexing dramatically faster for huge archives where only header-level search matters.
- Recipients are parsed from `transportMessageHeaders` rather than `pst-extractor`'s `getRecipient()` API, which hits disk per recipient and dominates indexing time on big PSTs (measured 120 ms/message vs effectively free for header parsing).
- Attachment downloads and `.eml` export each spawn a fresh Node process (~100–300 ms latency per click). Fine for one-off use; not built for batch export. The attachment bytes are never stored in the index — they're streamed straight from the PST on demand.

## License

`pst-search` is MIT-licensed (see `LICENSE`). Third-party dependencies and their licenses are listed in `THIRD_PARTY_LICENSES.md`.

## A note on "password-protected" PST files

Outlook lets you set a password on a PST. Despite the name, **this is not encryption of the message content** — it's a hash stored in the PST header that Outlook checks before opening the file. The actual messages and attachments are stored as cleartext (or with a weak public byte-permutation cipher that every PST library handles transparently).

This means:

- `pst-search` reads password-protected PSTs without asking for a password, because the underlying parser (pst-extractor) doesn't honor the header check. This matches the default behavior of essentially every PST tool — libpff, libpst, SysTools, Aspose, and the rest.
- This is true of the format itself, not specific to our tool. Microsoft documented this in `[MS-PST]`. Anyone with the file can read its contents regardless of the password.
- If you need the contents of a PST to remain confidential, **rely on file-system encryption** (BitLocker, FileVault, LUKS, an encrypted disk image) rather than Outlook's PST password.
- Individual messages encrypted via S/MIME are a different mechanism (per-message PKCS#7, requires the recipient's private key) and `pst-search` cannot decrypt those. Their bodies will appear as encrypted blobs in the search index, which is correct behavior.

## Known limitations

- **Internal search folders are skipped.** Some PSTs contain auto-generated "search root" folders (`SPAM Search Folder 2`, `ItemProcSearch`, `PST Conversation Lookup`, etc.) that hold search caches rather than user mail. `pst-extractor` can't reliably enumerate them and we explicitly skip them. No real mail is missed.
- **No incremental indexing.** Re-running `index` on the same PST replaces all its rows. Fine for static archives; not designed for live mailboxes where the source file keeps changing.
- **The source PST must stay where you indexed it.** We store the absolute path in the database and need to re-open the file for attachment downloads and `.eml` export. If you move or rename the `.pst`, those operations return a clear error and you'll need to re-index.
- **S/MIME-encrypted messages are not decrypted.** Per-message PKCS#7 encryption requires the recipient's private key — out of scope for this tool. Such messages appear in the index with encrypted-looking body content. Their headers (subject, sender, date) are still searchable.
- **HTML body is converted to plain text in the search index.** The detail pane shows the stripped text. The original HTML is preserved when you export the message as `.eml`, but the in-app body view is text only. Tradeoff for compact storage and reliable search.

