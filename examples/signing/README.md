# Signing examples

Small, dependency-free code for the two checks every gateway needs:

1. **QRIS Soundbox messages**: build, sign and verify `#QRISSB <json>|<sig>` texts
   ([protocol.md](../../docs/protocol.md#message-envelope-and-signing)).
2. **Midtrans notifications**: check `signature_key`
   ([midtrans-integration.md](../../docs/midtrans-integration.md#4-turn-a-midtrans-notification-into-an-announcement)).

| Language | File | Self-test |
|---|---|---|
| Python 3 | [python/qrissb_sign.py](python/qrissb_sign.py) | `python3 python/qrissb_sign.py` |
| Node.js 16+ | [node/qrissb_sign.js](node/qrissb_sign.js) | `node node/qrissb_sign.js` |
| PHP 7.4+ | [php/qrissb_sign.php](php/qrissb_sign.php) | `php php/qrissb_sign.php` |
| Go 1.18+ | [go/qrissb.go](go/qrissb.go) | `cd go && go test -v` |
| Kotlin / Android | [kotlin/QrissbSign.kt](kotlin/QrissbSign.kt) | see [below](#kotlin) |

Every self-test checks the same [test-vectors.json](test-vectors.json): a signed message, a
tampered copy that must fail, an unsigned `pairing.ok`, and a Midtrans notification. The vectors
were also checked independently with `openssl`.

## The functions

Each file has the same four functions (names follow each language's style):

| Function | Does |
|---|---|
| `sign(key, jsonText)` | Lowercase hex HMAC-SHA256 of the exact JSON text, keyed with the decoded base64 `hmac_key` |
| `buildMessage(key, obj)` | Serialises `obj` once (compact), signs that text, returns `#QRISSB <json>\|<sig>` |
| `parseMessage(text, key)` | Splits at the last `\|`, verifies the received JSON text, returns it with a verified flag |
| `midtransSignatureOk(notification, serverKey)` | `SHA512(order_id + status_code + gross_amount + ServerKey)` against `signature_key` |

Python:

```python
from qrissb_sign import build_message, parse_message, midtrans_signature_ok

text = build_message(device["key"], {"v": 1, "type": "qr.created", "device_id": device["id"],
                                     "outlet_id": "OUT-0012", "ts": int(time.time()),
                                     "request_id": rid, "amount": 95000, "qris": qr_string,
                                     "expires_at": expires})
bot.send_message(chat_id, text)

obj, verified = parse_message(update_text, device["key"])
if obj is not None and verified and obj["device_id"] == device["id"] \
        and obj["outlet_id"] == outlet_id and abs(time.time() - obj["ts"]) <= 300:
    handle(obj)
```

Node.js:

```js
const { buildMessage, parseMessage, midtransSignatureOk } = require("./qrissb_sign");

app.post("/midtrans/notify", (req, res) => {
  if (!midtransSignatureOk(req.body, process.env.MIDTRANS_SERVER_KEY)) return res.sendStatus(403);
  res.sendStatus(200);          // answer first...
  queue.push(req.body);         // ...then announce from a queue
});
```

## Rules that make signatures match

- **Sign the text you send, verify the text you received.** Never re-serialise a received
  message to check it: key order, spacing and escaping (`\/`, `ñ`) differ between JSON
  libraries. Each `buildMessage` serialises once and signs those exact bytes.
- **UTF-8.** The HMAC covers the UTF-8 bytes of the JSON text (the vectors include an `ñ` to
  catch encoding mistakes).
- **Lowercase hex, 64 characters.** Receivers lower-case the signature before comparing.
- **Split at the last `|`.** JSON values may contain `|`; the signature never does.
- **Compare in constant time** (`hmac.compare_digest`, `crypto.timingSafeEqual`, `hash_equals`,
  `hmac.Equal`, `MessageDigest.isEqual`).
- **The signature is only the first check.** Also check `device_id`, `outlet_id` and that `ts` is
  within 300 seconds.
- **Midtrans strings as sent.** Use `gross_amount` exactly as it arrives (`"95000.00"`), not a
  number you formatted yourself.

## Kotlin

`QrissbSign.kt` works on JSON strings so it fits any JSON library; on Android, serialise with
`JSONObject.toString()` and parse with `JSONObject(parsed.jsonText)`. It uses `java.util.Base64`
(Android API 26+).

To run its self-check, pass the ten test-vector values in (needs `kotlinc` and a UTF-8 locale):

```sh
kotlinc kotlin/QrissbSign.kt -include-runtime -d check.jar
python3 -c "
import json; v=json.load(open('test-vectors.json', encoding='utf-8'))
q, m = v['qrissb'], v['midtrans']; n = m['notification']
print('\n'.join([q['hmac_key'], q['json'], q['sig'], q['message'], q['tampered_message'],
                 m['server_key'], n['order_id'], n['status_code'], n['gross_amount'], n['signature_key']]))
" > args.txt
mapfile -t A < args.txt && LC_ALL=C.UTF-8 java -jar check.jar "${A[@]}"
```
