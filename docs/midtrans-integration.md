# Midtrans integration

How a gateway built on the **Midtrans Core API** connects merchants' QRIS Soundboxes: every
QR the customer scans is a Midtrans QRIS, and every settled payment is announced by the box.

This guide covers the Midtrans side. The messages exchanged with the SoundboxBridge app are
specified in [protocol.md](protocol.md); a runnable reference implementation is in
[examples/midtrans-simulator](../examples/midtrans-simulator).

## Contents

- [What you need](#what-you-need)
- [How it fits together](#how-it-fits-together)
- [1. Connect the merchant's bot](#1-connect-the-merchants-bot)
- [2. Pair the outlet's phone](#2-pair-the-outlets-phone)
- [3. Turn a printed bill into a Midtrans QRIS](#3-turn-a-printed-bill-into-a-midtrans-qris)
- [4. Turn a Midtrans notification into an announcement](#4-turn-a-midtrans-notification-into-an-announcement)
- [What the box shows](#what-the-box-shows)
- [Timing](#timing)
- [Security](#security)
- [Testing in the sandbox](#testing-in-the-sandbox)
- [Going to production](#going-to-production)
- [Troubleshooting](#troubleshooting)
- [References](#references)

## What you need

| | |
|---|---|
| **Midtrans account** | Core API access with QRIS enabled. Sandbox first: *Settings → Access Keys*, Server Key starting with `SB-Mid-server-` |
| **A public HTTPS endpoint** | For Telegram webhooks and Midtrans notifications. In development, a tunnel (Pinggy, ngrok, cloudflared) |
| **The merchant's Telegram bot** | The merchant creates it with @BotFather and enters its token in your dashboard |
| **Box firmware 1.3.0+** | For dynamic-only boxes (Midtrans has no static QRIS). Older firmware refuses the pairing |
| **SoundboxBridge with dynamic-only support** | Accepts `"qr_mode": "dynamic"` in the pairing link |

Only two Midtrans calls are involved:

1. `POST /v2/charge` with `payment_type: "qris"`: one per printed bill.
2. The HTTP notification Midtrans POSTs to you when the transaction changes status.

## How it fits together

```mermaid
sequenceDiagram
    autonumber
    participant POS
    participant Box
    participant App as SoundboxBridge
    participant Bot as Merchant's bot
    participant GW as Your gateway
    participant MT as Midtrans
    POS->>Box: print bill (Rp 95.000, order SO1)
    Box->>App: BILL (Bluetooth)
    App->>Bot: qr.request
    Bot->>GW: webhook POST
    GW->>MT: POST /v2/charge (qris)
    MT-->>GW: status_code "201" + qr_string
    GW->>Bot: sendMessage: qr.created
    Bot->>App: qr.created
    App->>Box: dynamic QR, shown with the amount
    Note over Box: customer scans and pays
    MT->>GW: notification: settlement
    GW->>Bot: sendMessage: payment.succeeded
    Bot->>App: payment.succeeded
    App->>Box: "Pembayaran diterima, sembilan puluh lima ribu rupiah"
```

Steps 2 to 9 must finish within **8 seconds** of the bill being printed (see [Timing](#timing)).

## 1. Connect the merchant's bot

When the merchant saves their bot token in your dashboard:

1. Call `getMe` to check the token and get the bot's username.
2. Call `setWebhook` once:
   - `url`: `https://<your gateway>/telegram/<merchant id>` (the path tells you which merchant)
   - `secret_token`: a random string you store with the merchant
   - `allowed_updates`: `["message"]`
3. Store the token encrypted.

Every message sent to the bot now arrives as a POST with the header
`X-Telegram-Bot-Api-Secret-Token: <secret_token>`. Reject anything else with `401`, answer valid
POSTs `200` straight away, and process them from a queue.

## 2. Pair the outlet's phone

Your dashboard shows a pairing link as a QR code for each outlet. For Midtrans, send
`"qr_mode": "dynamic"` and no `qris`:

```json
{
  "v": 1, "role": "owner", "provider": "MIDTRANS",
  "merchant_name": "Kopi Senja", "outlet_id": "OUT-0012", "outlet_name": "Kopi Senja Bekasi",
  "qr_mode": "dynamic",
  "transport": { "type": "telegram_bot", "bot": "KopiSenjaKasirBot" },
  "pairing_token": "pt_8f3c0b1e2a4d6c8e0f1a2b3c",
  "expires_at": "2026-11-12T14:10:00+07:00"
}
```

```
soundboxbridge://pair?d=<base64url of that JSON, no padding>
```

The merchant scans it in SoundboxBridge, the app sends `/start <pairing_token>` to the bot, and
you answer `pairing.ok` with a new `device_id` and a 32-byte `hmac_key`. Remember the Telegram
chat id the `/start` came from: you send that device's messages there. Field rules and the
handshake are in [protocol.md](protocol.md#pairing-link).

`outlet_name` matters more than usual here: a dynamic-only box shows it on its idle screen
(up to 39 ASCII characters; accents are dropped).

## 3. Turn a printed bill into a Midtrans QRIS

The app sends `qr.request` when the box reports a printed bill:

```json
{"v":1,"type":"qr.request","device_id":"dev_9a1b2c3d","outlet_id":"OUT-0012","ts":1794467500,
 "request_id":"sb_0a1b2c3d","amount":95000,"currency":"IDR","pos_ref":"SO1"}
```

After checking the signature, device, outlet and `ts` ([protocol.md](protocol.md#message-envelope-and-signing)),
charge Midtrans.

### The charge request

```http
POST https://api.sandbox.midtrans.com/v2/charge
Authorization: Basic base64("<Server Key>:")
Content-Type: application/json
Accept: application/json
X-Override-Notification: https://<your gateway>/midtrans/notify
```

```json
{
  "payment_type": "qris",
  "transaction_details": { "order_id": "SO1", "gross_amount": 95000 },
  "qris": { "acquirer": "gopay" }
}
```

| Field | From | Notes |
|---|---|---|
| `payment_type` | | `"qris"` |
| `transaction_details.order_id` | `pos_ref` (or `request_id`) | The POS order number, so the merchant finds it in the Midtrans dashboard; see below |
| `transaction_details.gross_amount` | `amount` | Whole rupiah |
| `qris.acquirer` | your setting | `"gopay"` or `"airpay shopee"` (ShopeePay) |

`payment_type` and `transaction_details` are the only required fields. The `X-Override-Notification`
header makes Midtrans send this transaction's notifications to the given URL instead of the
dashboard's (up to 3 URLs, comma-separated; `X-Append-Notification` adds to the dashboard's
instead). In production you can set the URL once in the dashboard and leave the header out.

**order_id.** Use the POS order number from `pos_ref` when the receipt has one: the merchant then
sees the same number on the receipt and in the Midtrans dashboard, which makes payments easy to
check. Midtrans rejects a repeated `order_id` (`406`), and the same order number comes back when
a bill is reprinted, or from another outlet on the same Midtrans account. So:

1. Try `pos_ref` as it is (`SO1`).
2. On a `406`, retry once with the bill's code appended: `SO1-0a1b2c3d` (the 8 hex digits of
   `request_id`, unique per printed bill). It still starts with the merchant's order number.
3. Without `pos_ref`, use something unique, e.g. `<outlet_id>-<request_id>-<unix time>`.

Allowed characters are letters, digits, `-`, `_`, `~` and `.` (up to 50): replace anything else,
so `INV/2026/001` becomes `INV-2026-001`. The retry costs one extra call (about 0.3 s), well within
the [8 seconds](#timing). Keep a map from `order_id` to device, chat, `request_id` and `pos_ref`
for the notification.

### The charge response

A successful charge answers `status_code` `"201"`. Midtrans can answer HTTP 200 with an error
`status_code` inside, so check the body, not just the HTTP status. The fields you use:

| Field | Use |
|---|---|
| `status_code` | `"201"` = created; anything else is an error (`status_message`, `validation_messages`) |
| `qr_string` | The QRIS text: goes into `qr.created` as `qris` |
| `transaction_id` | Keep it: the notification's id, and your `event_id` later |
| `expiry_time` | When present, the QR's expiry (`YYYY-MM-DD HH:MM:SS`, GMT+7) |
| `transaction_time` | When `expiry_time` is missing, the reference simulator assumes `transaction_time` + 15 minutes |
| `actions[]` | `generate-qr-code` (plain PNG) and `generate-qr-code-v2` (PNG with ASPI's border): image URLs, handy for testing, not needed by the box |

`qr_string` is returned by the sandbox, although the response example in Midtrans' QRIS reference
doesn't show it. If a response ever lacks it, send `qr.failed`: the box needs the QRIS text,
not an image.

### The answer

```json
{"v":1,"type":"qr.created","device_id":"dev_9a1b2c3d","outlet_id":"OUT-0012","ts":1794467501,
 "request_id":"sb_0a1b2c3d","amount":95000,"qris":"<qr_string>",
 "expires_at":"2026-11-12T14:26:41+07:00"}
```

| `qr.created` field | From |
|---|---|
| `request_id` | `qr.request` |
| `amount` | `qr.request` (Midtrans' QR carries the same amount in tag 54; the box checks it) |
| `qris` | `qr_string` |
| `expires_at` | `expiry_time` with `+07:00`, or your own default. The box shows the QR until then, clamped to 10 to 900 seconds |

If the charge fails (Midtrans error, timeout, no `qr_string`), answer `qr.failed` at once with a
short `reason`:

```json
{"v":1,"type":"qr.failed","device_id":"dev_9a1b2c3d","outlet_id":"OUT-0012","ts":1794467501,
 "request_id":"sb_0a1b2c3d","reason":"gateway error"}
```

The box then shows "QR gagal" immediately instead of waiting out the 8 seconds.

**`pos_ref`.** Midtrans makes the QR, so you can't put the POS order number in the QR's bill
number yourself; it becomes the `order_id` instead (above). Also send it back as `reference` in
`payment.succeeded`, so the app logs which order was paid.

**`qr.cancel`.** The app sends it when a newer bill replaces this one or your answer came too
late. You can cancel the Midtrans transaction, or let the QR expire. If it is paid anyway, still
announce it.

## 4. Turn a Midtrans notification into an announcement

Midtrans POSTs a JSON notification to your notification URL whenever the transaction changes
status. You also get one with `pending` right after the charge.

**1. Verify it.** Compute

```
SHA512(order_id + status_code + gross_amount + ServerKey)
```

over the notification's own `order_id`, `status_code` and `gross_amount` strings (e.g.
`"95000.00"`, as sent), lowercase hex, and compare it with `signature_key`. Reject a mismatch
(the reference implementation answers `403`).

**2. Answer `200` quickly**, then process from a queue. Midtrans waits up to 15 seconds and
recommends answering within 5. It retries failed deliveries (at most five times, roughly 2, 10,
30, 90 and 210 minutes later), so the same notification can arrive more than once.

**3. Act on the status:**

| `transaction_status` | Do |
|---|---|
| `pending` | Nothing (the QR is waiting) |
| `settlement` (or `capture`) | Send `payment.succeeded`, once per `transaction_id` |
| `expire` | Nothing: the box's QR times out by itself |
| `deny`, `cancel`, `failure` | Nothing to announce. Log it |

```json
{"v":1,"type":"payment.succeeded","device_id":"dev_9a1b2c3d","outlet_id":"OUT-0012","ts":1794467560,
 "event_id":"c8c98727-2880-4c4a-8cfa-a31a459d8cef","request_id":"sb_0a1b2c3d","amount":95000,
 "currency":"IDR","reference":"SO1","issuer":"GOPAY","paid_at":"2026-11-12T14:12:40+07:00",
 "rrn":"c8c98727-2880-4c4a-8cfa-a31a459d8cef"}
```

| `payment.succeeded` field | From |
|---|---|
| `event_id` | `transaction_id` (unique: the app drops repeats) |
| `request_id`, `reference` | Your order map (`request_id`, `pos_ref`) |
| `amount` | `gross_amount` as a whole number (`"95000.00"` → `95000`) |
| `currency` | `currency` (`"IDR"`) |
| `issuer` | `issuer` (sent with settlement), else `acquirer`, upper-cased |
| `paid_at` | `settlement_time` with `+07:00` |
| `rrn` | `reference_id` when present (ShopeePay), else `transaction_id` |

Send it to the chat of the device whose bill it was. The app announces it if it arrives within
120 seconds; a phone that was offline longer shows it without speaking.

**Missed notifications.** Midtrans recommends its GET Status API as a fallback when a
notification doesn't arrive in time, and before marking a transaction failed. The reference
simulator doesn't use it; a production gateway should reconcile with it.

## What the box shows

A box paired with `"qr_mode": "dynamic"` holds no static QRIS:

| Situation | Box screen |
|---|---|
| Idle | Outlet name and a "Kami menerima" QRIS / GPN badge (no QR) |
| Bill printed, `qr.created` in time | The amount and your Midtrans QR, until `expires_at` |
| Paid | Back to idle (the 3.97" box shows "Pembayaran diterima" and the amount first) and the voice announcement |
| `qr.failed`, no answer in 8 s, amount out of tolerance (±), phone not connected | "QR gagal / Cetak ulang tagihan" (QR failed, print the bill again) for 10 s |

The cashier reprints the bill to try again; each reprint is a new `qr.request`.

## Timing

The box and the app both stop waiting **8 seconds** after the bill is printed. Within that time:

- box → app over Bluetooth (well under a second),
- app → bot → your webhook (Telegram, usually under a second),
- your Midtrans charge (about 0.3 s in sandbox tests),
- your `sendMessage` → app → box.

A sandbox run end to end: webhook POST to `qr.created` sent in 1.1 s, of which the charge took
0.3 s. Keep the webhook handler fast, reuse HTTP connections to Midtrans and Telegram, and send
`qr.failed` as soon as a charge fails instead of retrying past the window.

## Security

- **Server Key**: server side only, never in the pairing link, the app or logs.
- **Bot tokens**: stored encrypted; check `X-Telegram-Bot-Api-Secret-Token` on every webhook POST.
- **Device keys**: one random 32-byte `hmac_key` per paired phone, sent once in `pairing.ok`.
  Never log it. Delete it and send `device.revoked` when the merchant unpairs the phone.
- **Pairing tokens**: random, one use, short-lived (10 minutes is plenty).
- **Every message**: verify signature, `device_id`, `outlet_id` and `ts` (±300 s) before acting.
- **Notifications**: verify `signature_key` before announcing anything; deduplicate by
  `transaction_id`.
- **Amounts**: announce `gross_amount` from the verified notification, never an amount that came
  from the app.

## Testing in the sandbox

The [Midtrans simulator example](../examples/midtrans-simulator) is a complete gateway in one
Python file (standard library only) that does everything above against the Midtrans sandbox.

1. Create a test bot with @BotFather; copy your sandbox Server Key.
2. Start a tunnel to port 8080, e.g. `ssh -p 443 -R0:localhost:8080 a.pinggy.io`.
3. Run:
   ```
   python3 pg_sim_midtrans.py --token <BOT_TOKEN> --server-key SB-Mid-server-... \
       --public-url https://<tunnel host> --outlet-name "Kopi Senja"
   ```
4. In SoundboxBridge: *Branches → Branch phone → Scan owner's QR* (or *Paste link*), then send
   the QRIS to the box when the app asks.
5. Print a bill from the POS to the box. The simulator logs the charge and its QR image URL.
6. Pay: open the [Midtrans sandbox QRIS simulator](https://simulator.sandbox.midtrans.com/v2/qris/index),
   paste the QR image URL, pay. The settlement notification makes the box announce it.

Type `fail` to make the next request fail (the box shows "QR gagal"), `revoke` to unpair, `info`
for the webhook status.

## Going to production

| | Sandbox | Production |
|---|---|---|
| API base | `https://api.sandbox.midtrans.com` | `https://api.midtrans.com` |
| Server Key | `SB-Mid-server-...` | `Mid-server-...` |
| Notification URL | `X-Override-Notification` per charge | Dashboard setting (or keep the header) |
| Paying | Sandbox QRIS simulator | Any QRIS app |

Before going live:

- [ ] `order_id` from the POS order number, with the `406` retry, and unique ids for bills without one
- [ ] Notifications verified, answered within 5 seconds, deduplicated
- [ ] GET Status reconciliation for missed notifications
- [ ] Bot tokens and device keys encrypted at rest, never logged
- [ ] Webhook processing queued, with `qr.failed` on any charge error
- [ ] Merchants told that boxes need firmware 1.3.0 or newer

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| App says the pairing code isn't valid | App version without dynamic-only support; expired link; bot username or token malformed |
| App asks to update the box firmware | Box firmware older than 1.3.0 (no "D" in its status): it refuses a dynamic-only identity |
| Box shows "QR gagal" for every bill | Answer later than 8 s (see the simulator's "answered in" line); charge error; `qr_string` missing; amount out of tolerance (±99); box's gateway mode off |
| QR shows, payment never announced | Notification URL unreachable (tunnel changed), signature mismatch (wrong Server Key), payment sent to another chat, or the message reached the phone more than 120 s later |
| `charge: 406` | Repeated `order_id`: retry with the bill's code appended (see [order_id](#the-charge-request)) |
| `charge: 401` | Wrong Server Key, or a production key against the sandbox |
| Webhook gets nothing | `setWebhook` replaced by another tool using the same bot, or the tunnel URL changed: call `setWebhook` again |

## References

- Midtrans: [QRIS charge](https://docs.midtrans.com/reference/qris) ·
  [HTTP(S) notification / webhooks](https://docs.midtrans.com/docs/https-notification-webhooks) ·
  [Override notification URL](https://docs.midtrans.com/reference/override-notification-url) ·
  [midtrans-go (header names)](https://pkg.go.dev/github.com/midtrans/midtrans-go)
- Telegram: [setWebhook](https://core.telegram.org/bots/api#setwebhook) ·
  [sendMessage](https://core.telegram.org/bots/api#sendmessage)
- This repository: [protocol.md](protocol.md) · [signing examples](../examples/signing) ·
  [Midtrans simulator](../examples/midtrans-simulator)
