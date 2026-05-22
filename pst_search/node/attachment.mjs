// Single-attachment extraction.
//
// Usage: node attachment.mjs <pst-file> <descriptor-node-id> <attachment-index>
// Output: raw attachment bytes on stdout.
//
// We look up the message directly by its descriptor node ID rather than
// re-walking the folder tree — large PSTs (100K+ messages) would otherwise
// make every attachment download take minutes.

import { PSTFile, PSTMessage } from 'pst-extractor';
import Long from 'long';

const [, , pstPath, descNodeIdStr, attIdxStr] = process.argv;
if (!pstPath || !descNodeIdStr || attIdxStr === undefined) {
  process.stderr.write('usage: node attachment.mjs <pst-file> <descriptor-node-id> <attachment-index>\n');
  process.exit(2);
}
const attachIndex = parseInt(attIdxStr, 10);

let pst;
try {
  pst = new PSTFile(pstPath);
} catch (e) {
  process.stderr.write(`OPEN_FAILED: ${e?.message || e}\n`);
  process.exit(1);
}

let descNodeId;
try {
  descNodeId = Long.fromString(descNodeIdStr);
} catch {
  descNodeId = Long.fromNumber(parseInt(descNodeIdStr, 10));
}

let descNode;
try {
  descNode = pst.getDescriptorIndexNode(descNodeId);
} catch (e) {
  process.stderr.write(`LOOKUP_FAILED: ${e?.message || e}\n`);
  process.exit(1);
}

// Build a PSTMessage from the descriptor node so we can access attachments.
let msg;
try {
  msg = new PSTMessage(pst, descNode);
} catch (e) {
  process.stderr.write(`MSG_FAILED: ${e?.message || e}\n`);
  process.exit(1);
}

const total = msg.numberOfAttachments;
if (attachIndex < 0 || attachIndex >= total) {
  process.stderr.write(`OUT_OF_RANGE: have ${total}, requested ${attachIndex}\n`);
  process.exit(1);
}

const att = msg.getAttachment(attachIndex);
if (!att) {
  process.stderr.write(`NULL_ATTACHMENT\n`);
  process.exit(1);
}

// Filename goes on stderr as a single line prefixed with NAME: — Python reads
// it to name the download. Bytes go on stdout.
const name = att.longFilename || att.filename || `attachment_${attachIndex}.bin`;
process.stderr.write(`NAME: ${name}\n`);

const stream = att.fileInputStream;
if (!stream) {
  process.stderr.write(`NO_STREAM\n`);
  process.exit(1);
}

const size = att.filesize || att.size || 0;
const buf = Buffer.alloc(size > 0 ? size : 4096);
let total_read = 0;
while (true) {
  const n = stream.read(buf);
  if (n <= 0) break;
  process.stdout.write(buf.subarray(0, n));
  total_read += n;
  if (size > 0 && total_read >= size) break;
}
