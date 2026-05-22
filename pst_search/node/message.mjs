// Full message dump for .eml export.
//
// Usage: node message.mjs <pst-file> <descriptor-node-id>
// Output: JSON to stdout. Diagnostics to stderr.
//
// The JSON contains everything Python needs to assemble an RFC 5322 .eml:
// subject, sender, recipients (parsed from transport headers), both body
// representations, and every attachment's bytes base64-encoded.
//
// Memory note: this script holds all attachments in memory before emitting.
// For a single-message export that's fine (attachments typically <10 MB);
// for batch-export-all we'd want a streaming format instead.

import { PSTFile, PSTMessage } from 'pst-extractor';
import Long from 'long';

const [, , pstPath, descNodeIdStr] = process.argv;
if (!pstPath || !descNodeIdStr) {
  process.stderr.write('usage: node message.mjs <pst-file> <descriptor-node-id>\n');
  process.exit(2);
}

let pst;
try { pst = new PSTFile(pstPath); }
catch (e) { process.stderr.write(`OPEN_FAILED: ${e?.message || e}\n`); process.exit(1); }

let descId;
try { descId = Long.fromString(descNodeIdStr); }
catch { descId = Long.fromNumber(parseInt(descNodeIdStr, 10)); }

let descNode;
try { descNode = pst.getDescriptorIndexNode(descId); }
catch (e) { process.stderr.write(`LOOKUP_FAILED: ${e?.message || e}\n`); process.exit(1); }

let msg;
try { msg = new PSTMessage(pst, descNode); }
catch (e) { process.stderr.write(`MSG_FAILED: ${e?.message || e}\n`); process.exit(1); }

function safe(fn, dflt = '') {
  try { const v = fn(); return v == null ? dflt : v; } catch { return dflt; }
}
function isoOrNull(d) { if (!d) return null; try { return d.toISOString(); } catch { return null; } }

const out = {
  subject:           safe(() => msg.subject),
  sender_name:       safe(() => msg.senderName),
  sender_email:      safe(() => msg.senderEmailAddress),
  transport_headers: safe(() => msg.transportMessageHeaders),
  delivery_time:     isoOrNull(safe(() => msg.messageDeliveryTime, null)),
  submit_time:       isoOrNull(safe(() => msg.clientSubmitTime, null)),
  body_text:         safe(() => msg.body),
  body_html:         safe(() => msg.bodyHTML),
  attachments:       [],
};

// Pull each attachment's bytes. Same pattern as attachment.mjs but multiple.
const n = safe(() => msg.numberOfAttachments, 0);
for (let i = 0; i < n; i++) {
  let att;
  try { att = msg.getAttachment(i); } catch { continue; }
  if (!att) continue;

  let stream;
  try { stream = att.fileInputStream; } catch { stream = null; }
  if (!stream) {
    out.attachments.push({
      name: safe(() => att.longFilename) || safe(() => att.filename) || `attachment_${i}.bin`,
      mime: safe(() => att.mimeTag) || 'application/octet-stream',
      size: safe(() => att.filesize, 0) || safe(() => att.size, 0),
      content_base64: '',
      error: 'no stream',
    });
    continue;
  }

  const size = safe(() => att.filesize, 0) || safe(() => att.size, 0);
  const buf = Buffer.alloc(size > 0 ? Math.min(size, 1 << 20) : 4096);
  const chunks = [];
  let totalRead = 0;
  while (true) {
    let read;
    try { read = stream.read(buf); } catch { read = -1; }
    if (read <= 0) break;
    chunks.push(Buffer.from(buf.subarray(0, read)));
    totalRead += read;
    if (size > 0 && totalRead >= size) break;
  }
  const content = Buffer.concat(chunks);
  out.attachments.push({
    name: safe(() => att.longFilename) || safe(() => att.filename) || `attachment_${i}.bin`,
    mime: safe(() => att.mimeTag) || 'application/octet-stream',
    size: content.length,
    content_base64: content.toString('base64'),
  });
}

process.stdout.write(JSON.stringify(out));
