// pst-extractor → NDJSON streaming.
//
// Usage: node extract.mjs <pst-file>
// Output: one JSON object per line on stdout. Each object describes one
//         message. Diagnostics go to stderr.
//
// Why NDJSON rather than one big JSON? Some PSTs have hundreds of thousands
// of messages — streaming lets the Python indexer commit batches as they
// arrive instead of buffering the whole tree in memory.

import { PSTFile, PSTMessage } from 'pst-extractor';
import { writeSync } from 'fs';
// When stdout is piped (not a TTY), Node block-buffers it, so the Python
// consumer sees nothing until the buffer flushes — minutes on a large PST.
// fs.writeSync(1, ...) bypasses that, writing each line immediately.
const STDOUT_FD = 1;

const pstPath = process.argv[2];
if (!pstPath) {
  process.stderr.write('usage: node extract.mjs <pst-file>\n');
  process.exit(2);
}

function isoOrNull(d) {
  if (!d) return null;
  try { return d.toISOString(); } catch { return null; }
}

function safe(fn, dflt = null) {
  try { return fn(); } catch { return dflt; }
}

// Strip HTML inline but keep paragraph breaks. PST messages from modern
// Outlook routinely have 20-100KB of HTML+CSS markup; we keep text content
// with structure intact so the body is readable in the detail pane.
//
// Stripping in Node (single-pass regex) is dramatically faster than calling
// BeautifulSoup per message from Python — measured ~100x in initial tests.
const HTML_HEAD_STYLE_RE = /<(script|style|head)\b[^>]*>[\s\S]*?<\/\1>/gi;
// Block-level closings and forced line breaks get converted to a newline
// BEFORE we strip remaining tags, so the body retains visible paragraph
// structure when rendered in the detail pane with white-space: pre-wrap.
const HTML_BLOCK_BREAK_RE = /<\/?(p|div|br|tr|li|h[1-6]|blockquote|pre|hr)\b[^>]*>/gi;
const HTML_TAG_RE = /<[^>]+>/g;
const HTML_ENTITY_RE = /&(amp|lt|gt|quot|apos|#39|nbsp|mdash|ndash|hellip);/g;
const WHITESPACE_RE = /\s+/g;
// Collapse runs of spaces/tabs but PRESERVE newlines
const INLINE_WS_RE = /[ \t]+/g;
// Collapse 3+ blank lines down to 2 (one blank line between paragraphs)
const MULTI_NEWLINE_RE = /\n{3,}/g;
// Leading/trailing whitespace on each line
const TRIM_LINES_RE = /^[ \t]+|[ \t]+$/gm;
const ENTITY_MAP = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", '#39': "'", nbsp: ' ', mdash: '—', ndash: '–', hellip: '…' };

function stripHtml(s) {
  if (!s) return '';
  if (!s.includes('<')) return s.replace(/\r\n?/g, '\n').replace(INLINE_WS_RE, ' ').replace(TRIM_LINES_RE, '').replace(MULTI_NEWLINE_RE, '\n\n').trim();
  return s
    .replace(HTML_HEAD_STYLE_RE, ' ')
    .replace(HTML_BLOCK_BREAK_RE, '\n')
    .replace(HTML_TAG_RE, ' ')
    .replace(HTML_ENTITY_RE, (_, n) => ENTITY_MAP[n] || ' ')
    .replace(/\r\n?/g, '\n')
    .replace(INLINE_WS_RE, ' ')
    .replace(TRIM_LINES_RE, '')
    .replace(MULTI_NEWLINE_RE, '\n\n')
    .trim();
}

// Cap stored body text per message. Set generously — most personal email
// fits comfortably under 32 KB after HTML stripping. Tunable for users with
// huge attachment-bearing PSTs who want a smaller index.
const BODY_CAP = parseInt(process.env.PST_SEARCH_BODY_CAP || '32768', 10);
// Skip the HTML body branch only for genuinely enormous messages. The cost
// of fetching HTML scales with subnode reads but is much cheaper than the
// recipients API we already bypass. Was 100 KB (too aggressive — 68% of one
// real mailbox came back empty); 4 MB covers essentially every real email.
const MAX_HTML_FETCH_SIZE = parseInt(process.env.PST_SEARCH_MAX_HTML_FETCH || '4194304', 10);

function capBody(s) {
  if (!s) return '';
  return s.length > BODY_CAP ? s.slice(0, BODY_CAP) : s;
}

// Body extraction can be toggled off via PST_SEARCH_BODY=0. On big PSTs this
// can be the difference between minutes and hours for indexing — pst-extractor
// is slow on the subnode disk reads required to assemble body text. Subject,
// sender, recipients, and folder paths are still indexed and remain searchable.
const FETCH_BODY = (process.env.PST_SEARCH_BODY || '1') !== '0';

function extractBody(msg) {
  if (!FETCH_BODY) return '';
  const plain = safe(() => msg.body, '');
  if (plain && plain.length) return capBody(plain);
  const msgSize = safe(() => Number(msg.messageSize?.toNumber?.() ?? msg.messageSize ?? 0), 0);
  if (msgSize > 0 && msgSize < MAX_HTML_FETCH_SIZE) {
    const html = safe(() => msg.bodyHTML, '');
    if (html && html.length) return capBody(stripHtml(html));
    const rtf = safe(() => msg.bodyRTF, '');
    if (rtf && rtf.length) {
      const stripped = rtf.replace(/\\[a-z]+\-?\d*\s?/gi, ' ').replace(/[{}]/g, ' ').replace(WHITESPACE_RE, ' ').trim();
      return capBody(stripped);
    }
  }
  return '';
}

// Parse recipients out of transportMessageHeaders rather than pst-extractor's
// getRecipient() API. The API call hits subnode disk reads per recipient and
// dominates indexing time on big PSTs (measured at ~120ms/message). Header
// parsing is essentially free since we fetch the headers anyway.
const HEADER_TO_RE   = /^to:\s*(.+(?:\r?\n[ \t].+)*)/im;
const HEADER_CC_RE   = /^cc:\s*(.+(?:\r?\n[ \t].+)*)/im;
const HEADER_BCC_RE  = /^bcc:\s*(.+(?:\r?\n[ \t].+)*)/im;

// Cap header size we parse. Some PST messages (especially auto-generated JIRA
// notifications) have multi-MB transport-header blobs that turn the recipient
// regex into a ReDoS — we observed Node burning CPU for 5+ min on one such
// message in a real mailbox. 32KB is more than enough for legitimate headers.
const MAX_HEADER_PARSE = 32 * 1024;

function recipientsFromHeaders(headers) {
  if (!headers) return [];
  if (headers.length > MAX_HEADER_PARSE) headers = headers.slice(0, MAX_HEADER_PARSE);
  const out = [];
  const addLine = (m, type) => {
    if (!m) return;
    const flat = m[1].replace(/\r?\n[ \t]+/g, ' ').replace(/\s+/g, ' ').trim();
    // Split on commas but not inside quotes
    const tokens = flat.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/);
    for (let tok of tokens) {
      tok = tok.trim();
      if (!tok) continue;
      const m2 = tok.match(/^"?([^"]*?)"?\s*<([^>]+)>$/) || tok.match(/^([^<]+)\s+\(([^)]+)\)$/);
      let name = '', email = '';
      if (m2) { name = m2[1].trim(); email = m2[2].trim(); }
      else if (tok.includes('@')) { email = tok; }
      else { name = tok; }
      out.push({ name, email, type });
    }
  };
  addLine(headers.match(HEADER_TO_RE), 1);
  addLine(headers.match(HEADER_CC_RE), 2);
  addLine(headers.match(HEADER_BCC_RE), 3);
  return out;
}

function extractAttachments(msg) {
  const out = [];
  const n = safe(() => msg.numberOfAttachments, 0);
  for (let i = 0; i < n; i++) {
    const a = safe(() => msg.getAttachment(i));
    if (!a) continue;
    out.push({
      index: i,
      name: safe(() => a.longFilename, '') || safe(() => a.filename, '') || `attachment_${i}`,
      size: safe(() => a.filesize, 0) || safe(() => a.size, 0),
      mime: safe(() => a.mimeTag, '') || '',
    });
  }
  return out;
}

function emit(obj) {
  // Synchronous write — defeats Node's pipe block-buffering so the Python
  // indexer receives each record as it's produced.
  writeSync(STDOUT_FD, JSON.stringify(obj) + '\n');
}

let pst;
try {
  pst = new PSTFile(pstPath);
} catch (e) {
  process.stderr.write(`OPEN_FAILED: ${e?.message || e}\n`);
  process.exit(1);
}

let totalMessages = 0;
let totalFolders = 0;
let skipped = 0;

// We label search/system folders by name and don't recurse into them — those
// are the ones pst-extractor's findBtreeItem fails on, and they contain
// search caches, not user mail.
const SKIP_BY_NAME = new Set(['SPAM Search Folder 2', 'ItemProcSearch', 'PST Conversation Lookup']);

function walk(folder, pathSegments) {
  totalFolders++;
  const name = safe(() => folder.displayName, '');
  const here = pathSegments.concat(name || '<unnamed>');
  const pathStr = here.join('/');
  const count = safe(() => folder.contentCount, 0);

  // Drain messages
  if (count > 0) {
    for (let i = 0; i < count; i++) {
      const tMsg = Date.now();
      let m;
      try { m = folder.getNextChild(); } catch (e) {
        skipped++;
        process.stderr.write(`MSG_ERR ${pathStr}#${i}: ${e?.message || e}\n`);
        continue;
      }
      const dtGetChild = Date.now() - tMsg;
      if (!m || !(m instanceof PSTMessage)) {
        // Not all children are PSTMessage (some are PSTContact, PSTTask, etc.)
        // We still try to grab subject/body fields if they exist.
      }
      try {
        const headers = safe(() => m.transportMessageHeaders, '');
        const obj = {
          identifier: safe(() => m.descriptorNodeId?.toString?.() ?? String(m.descriptorNodeId), null),
          folder_path: pathStr,
          subject: safe(() => m.subject, ''),
          sender_name: safe(() => m.senderName, ''),
          sender_email: safe(() => m.senderEmailAddress, ''),
          recipients: recipientsFromHeaders(headers),
          delivery_time: isoOrNull(safe(() => m.messageDeliveryTime)),
          submit_time: isoOrNull(safe(() => m.clientSubmitTime)),
          body: extractBody(m),
          transport_headers: headers,
          attachments: extractAttachments(m),
        };
        emit({ type: 'msg', ...obj });
        totalMessages++;
        if (totalMessages % 100 === 0) {
          process.stderr.write(`progress: ${totalMessages} messages\n`);
        }
        // Surface any single message that took more than 2s — usually a sign
        // that a pathological message is up next or pst-extractor is fighting
        // a corrupt subnode.
        const dtMsg = Date.now() - tMsg;
        if (dtMsg > 2000) {
          process.stderr.write(`SLOW msg #${totalMessages}: ${dtMsg}ms (getNextChild=${dtGetChild}ms, id=${obj.identifier}, subj=${(obj.subject || '').slice(0, 60)})\n`);
        }
      } catch (e) {
        skipped++;
        process.stderr.write(`MSG_PARSE_ERR ${pathStr}#${i}: ${e?.message || e}\n`);
      }
    }
  }

  // Recurse into subfolders, skipping known-broken search caches
  let subs = [];
  try { subs = folder.getSubFolders(); } catch (e) {
    process.stderr.write(`SUBFOLDER_ERR ${pathStr}: ${e?.message || e}\n`);
    return;
  }
  for (const sub of subs) {
    const subName = safe(() => sub.displayName, '');
    if (SKIP_BY_NAME.has(subName)) {
      process.stderr.write(`skipping system folder: ${subName}\n`);
      continue;
    }
    walk(sub, here);
  }
}

const t0 = Date.now();
walk(pst.getRootFolder(), []);
const elapsedSec = (Date.now() - t0) / 1000;
emit({ type: 'summary', messages: totalMessages, folders: totalFolders, skipped, elapsed_seconds: elapsedSec });
process.stderr.write(`done: ${totalMessages} messages, ${totalFolders} folders, ${skipped} skipped in ${elapsedSec.toFixed(1)}s\n`);
