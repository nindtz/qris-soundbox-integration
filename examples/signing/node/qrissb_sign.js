// QRIS Soundbox message signing + Midtrans notification check (Node.js 16+, no packages).
//
//   #QRISSB <json>|<hex HMAC-SHA256 of the exact json, keyed with the base64 hmac_key>
//
// Run `node qrissb_sign.js` to check it against ../test-vectors.json.
"use strict";
const crypto = require("crypto");

const PREFIX = "#QRISSB";

/** Lowercase hex HMAC-SHA256 of the exact JSON text. */
function sign(keyB64, jsonText) {
  return crypto.createHmac("sha256", Buffer.from(keyB64, "base64")).update(jsonText, "utf8").digest("hex");
}

/** Serialise once, sign that exact text, and wrap it. */
function buildMessage(keyB64, obj) {
  const json = JSON.stringify(obj);
  return `${PREFIX} ${json}|${sign(keyB64, json)}`;
}

function safeEqual(a, b) {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

/**
 * Returns { obj, verified }; obj is null if it isn't a #QRISSB message.
 * The signature is checked against the received JSON text, never a re-serialised copy.
 */
function parseMessage(text, keyB64) {
  const t = text.trim();
  if (!t.startsWith(PREFIX)) return { obj: null, verified: false };
  const body = t.slice(PREFIX.length).trim();
  const bar = body.lastIndexOf("|");
  let json = body, verified = false;
  if (bar > 0 && body.length - bar - 1 === 64) {
    json = body.slice(0, bar);
    verified = !!keyB64 && safeEqual(sign(keyB64, json), body.slice(bar + 1).toLowerCase());
  }                                                  // else unsigned (only pairing.ok is sent like this)
  try {
    return { obj: JSON.parse(json), verified };
  } catch {
    return { obj: null, verified: false };
  }
}

/** SHA512(order_id + status_code + gross_amount + ServerKey), using the notification's own strings. */
function midtransSignatureOk(n, serverKey) {
  const raw = `${n.order_id ?? ""}${n.status_code ?? ""}${n.gross_amount ?? ""}${serverKey}`;
  const expected = crypto.createHash("sha512").update(raw, "utf8").digest("hex");
  return safeEqual(expected, String(n.signature_key ?? "").toLowerCase());
}

module.exports = { sign, buildMessage, parseMessage, midtransSignatureOk };

if (require.main === module) {
  const assert = require("assert");
  const v = JSON.parse(require("fs").readFileSync(require("path").join(__dirname, "..", "test-vectors.json"), "utf8"));
  const q = v.qrissb;
  assert.strictEqual(sign(q.hmac_key, q.json), q.sig, "sign");
  assert.strictEqual(buildMessage(q.hmac_key, JSON.parse(q.json)), q.message, "buildMessage");
  const p = parseMessage(q.message, q.hmac_key);
  assert.ok(p.verified && p.obj.type === "qr.created", "parseMessage");
  assert.ok(!parseMessage(q.tampered_message, q.hmac_key).verified, "tampered");
  const u = parseMessage(q.unsigned_message, null);
  assert.ok(!u.verified && u.obj.type === "pairing.ok", "unsigned");
  const m = v.midtrans;
  assert.ok(midtransSignatureOk(m.notification, m.server_key), "midtrans ok");
  assert.ok(!midtransSignatureOk({ ...m.notification, gross_amount: "1.00" }, m.server_key), "midtrans bad");
  console.log("node: all test vectors pass");
}
