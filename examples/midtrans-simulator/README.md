# Midtrans gateway simulator

A complete, single-file gateway that connects a QRIS Soundbox to the **Midtrans sandbox**:
pairing, Telegram webhook, QRIS charge, payment notification and announcement. Python 3.8+,
standard library only.

Use it to try the whole flow with a real box before writing your own gateway, and as a
reference implementation of [the Midtrans guide](../../docs/midtrans-integration.md).

## What it does

| Step | Code |
|---|---|
| Sets the merchant bot's webhook with a `secret_token`, removes it on quit | `Gateway.connect_bot`, `disconnect_bot` |
| Serves the Telegram webhook and the Midtrans notification on one port | `Gateway.accept` |
| Prints a dynamic-only pairing link (and QR, with `pip install qrcode`) | `Gateway.pairing_link` |
| Answers `/start` with `pairing.ok` and a new device key | `Gateway.on_text` |
| Turns `qr.request` into `POST /v2/charge` and answers `qr.created` / `qr.failed` | `Gateway.on_qr_request` |
| Uses the POS order number as Midtrans `order_id`, retrying with the bill's code on a duplicate | `order_ids`, `Gateway.charge_with_order_ids` |
| Verifies notifications and sends `payment.succeeded` once per transaction | `Gateway.accept_midtrans`, `on_notification` |

Paired phones are kept in `pg_sim_state.json`, so they stay paired across restarts.

## Run it

You need a test bot from @BotFather, your sandbox Server Key (*Midtrans dashboard → Sandbox →
Settings → Access Keys*) and a tunnel to port 8080.

```sh
# 1. tunnel (prints a public https URL); Pinggy's free tunnel lasts 60 minutes
ssh -p 443 -R0:localhost:8080 a.pinggy.io

# 2. simulator, in another terminal
python3 pg_sim_midtrans.py --token <BOT_TOKEN> --server-key SB-Mid-server-... \
    --public-url https://<tunnel host> --outlet-name "Kopi Senja"
```

Then:

1. In SoundboxBridge: *Branches → Branch phone → Scan owner's QR* (or *Paste link*). Send the
   QRIS to the box when the app asks.
2. Print a bill from the POS to the box. The simulator logs the charge:
   ```
   13:06:36 [pg] qr.request sb_b424b1ed: Rp 95.000, order SO1
   13:06:36 [midtrans] charge SO1: pending, transaction c8c98727-...
   13:06:36 [midtrans] QR image: https://api.sandbox.midtrans.com/v2/qris/c8c98727-.../qr-code
   13:06:37 [pg] answered in 1.1 s (Midtrans charge 0.3 s). Paste the QR image URL above ...
   ```
   The Midtrans dashboard lists the transaction under the receipt's order number (`SO1`). A
   reprinted bill gets `SO1-<bill code>`, since Midtrans doesn't accept the same order id twice;
   a receipt without an order number gets `<outlet>-<request id>-<time>`.
3. Open the [Midtrans sandbox QRIS simulator](https://simulator.sandbox.midtrans.com/v2/qris/index),
   paste the QR image URL and pay. The settlement notification arrives and the box announces the
   payment.

A new tunnel URL needs a restart of the simulator with the new `--public-url`: `setWebhook`
replaces the old one, and every charge carries the new notification URL.

## Commands

| Command | Does |
|---|---|
| `pay` | Prints the last QR image URL again |
| `fail` | Makes the next `qr.request` fail (the box shows "QR gagal") |
| `revoke` | Sends `device.revoked` to every paired phone and forgets them |
| `link` | Prints a new pairing link |
| `info` | Shows Telegram's webhook status (URL, pending updates, last error) |
| `quit` | Removes the webhook and exits (`--keep-webhook` leaves it) |

## Options

| Option | Default | |
|---|---|---|
| `--token` | required | The merchant bot's token |
| `--server-key` | required | Sandbox Server Key (`SB-Mid-server-...`); production keys are refused |
| `--public-url` | required | The tunnel's `https://` URL |
| `--outlet-name` | `Test outlet` | Shown on a dynamic-only box's idle screen |
| `--qris` | none | A static QRIS instead of `qr_mode: dynamic`, for app versions without dynamic-only support |
| `--acquirer` | `gopay` | `gopay` or `airpay shopee` |
| `--pin` | none | Box settings PIN to put in the pairing link |
| `--outlet`, `--merchant`, `--merchant-id`, `--provider` | test values | Pairing link fields |
| `--port` | `8080` | Local port the tunnel forwards to |
| `--state` | `pg_sim_state.json` | Where paired phones are remembered |

## Not production code

It keeps everything in memory and one JSON file, handles one merchant, and has no GET Status
reconciliation, retries or encryption at rest. See
[Going to production](../../docs/midtrans-integration.md#going-to-production) for what a real
gateway adds.
