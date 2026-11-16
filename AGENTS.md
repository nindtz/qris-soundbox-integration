# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## What this repo is

Documentation and examples for **payment gateways** that want their merchants' payments
announced by a **QRIS Soundbox**, and their dynamic QRIS codes shown on it for bills printed
from the POS. Audience: developers at payment gateways and POS vendors. Reference gateway:
**Midtrans** (Core API, QRIS, sandbox).

- Product site: https://nindtz.github.io/qris-soundbox/
- `docs/protocol.md` is the source of truth. Read it before touching anything else.

## Layout

```
docs/
  protocol.md                 the gateway protocol (v: 1)
  midtrans-integration.md     step-by-step Midtrans Core API guide
examples/
  midtrans-simulator/         complete sandbox gateway, one Python file, stdlib only
  signing/                    sign/verify in python/ node/ php/ go/ kotlin/
    test-vectors.json         shared vectors every language must pass
```

## Architecture (do not change without the maintainer)

- **No QRIS Soundbox backend.** The product is buy-once with no server. Never add or propose a
  hosted relay, MQTT broker or central API.
- **Transport is always the merchant's own Telegram bot.** The merchant creates it with
  @BotFather and enters the token in the gateway's dashboard; the gateway sets a webhook with a
  `secret_token` and replies with `sendMessage`. SoundboxBridge (the outlet's phone) talks to
  the box over Bluetooth. The box never talks to the gateway.
- **Roles:** the gateway is the *owner*; the phone becomes its *branch* by scanning the pairing
  link `soundboxbridge://pair?d=<base64url JSON>`.
- **Every message** after `pairing.ok` is `#QRISSB <json>|<sig>`: lowercase hex HMAC-SHA256 of
  the exact UTF-8 JSON bytes, keyed with the decoded `hmac_key`. `pairing.ok` is the only
  unsigned message.
- **Static vs dynamic-only:** a link carries either `qris` (box can fall back to its own QR) or
  `"qr_mode": "dynamic"` (every QR from the gateway; needs box firmware 1.3.0+). Midtrans has no
  static QRIS, so the Midtrans examples are dynamic-only.

## Protocol rules agents get wrong

- Sign the text you send; verify the text you received. Never re-serialise before verifying.
- Split at the **last** `|`; signature is 64 hex chars; compare in constant time.
- Also check `device_id`, `outlet_id`, and `ts` within **300 s**.
- `qr.created` must answer `qr.request` within **8 s** of the bill printing (two Telegram hops
  included, so aim for ~3 s). Answer the webhook `200` first, do the work from a queue.
- `qr.created.amount` within ±99 of the request; QRIS tag 54 equals `amount`; CRC valid.
- `payment.succeeded` needs a unique `event_id` (resends are safe). The app only speaks payments
  that arrive within **120 s**.
- Amounts are whole rupiah, 1 to 999,999,999. Currency `"IDR"`.
- Midtrans `signature_key` = `SHA512(order_id + status_code + gross_amount + ServerKey)`, using
  `gross_amount` exactly as received (`"95000.00"`).
- **Don't invent fields or message types.** The firmware and SoundboxBridge (Android and iOS)
  parse these messages. If something isn't in `docs/protocol.md`, ask.

## Keeping things in sync

A change to a message, field, limit or timing must update, in the same change:

1. `docs/protocol.md`
2. `docs/midtrans-integration.md` where it's mentioned
3. `examples/midtrans-simulator/pg_sim_midtrans.py` and its README
4. All five signing examples and `test-vectors.json` if signing is affected
5. `README.md` if the summary or requirements change

The five signing files expose the same four functions (`sign`, `buildMessage`, `parseMessage`,
`midtransSignatureOk`, named in each language's style). Keep them parallel.

## Running the checks

```sh
cd examples/signing
python3 python/qrissb_sign.py      # Python 3
node node/qrissb_sign.js           # Node.js 16+
php php/qrissb_sign.php            # PHP 7.4+
(cd go && go test -v)              # Go 1.18+
# Kotlin: see examples/signing/README.md#kotlin (needs kotlinc)
```

Each prints a pass line when all test vectors pass. Run every one you touched.

Simulator (needs a test bot, a Midtrans **sandbox** Server Key and an HTTPS tunnel to 8080):

```sh
python3 examples/midtrans-simulator/pg_sim_midtrans.py --token <BOT_TOKEN> \
    --server-key SB-Mid-server-... --public-url https://<tunnel host>
```

## Conventions

- **English only** in docs and code comments. Box voice/screen strings in Indonesian (e.g.
  "QR gagal") are quoted as-is with an English gloss.
- Examples stay small and dependency-free (standard library only). A gateway developer should
  understand a flow from one file.
- Sandbox only. Never commit real bot tokens, server keys, merchant IDs, QRIS strings or
  `pg_sim_state.json` (it holds device keys and is gitignored). Use placeholders like
  `<BOT_TOKEN>` and `SB-Mid-server-...`.
- The simulator is explicitly not production code; don't grow it into a framework. Production
  advice belongs in `docs/midtrans-integration.md#going-to-production`.

## Before finishing

- [ ] Docs, simulator and signing examples agree on every format touched
- [ ] Signing self-tests pass for every language changed
- [ ] No secrets, tokens, keys or real merchant data in the diff
- [ ] Wording is clear for a non-Indonesian developer
