# QRIS Soundbox: payment gateway integration

Documentation and examples for payment gateways that want their merchants' payments announced
by a **QRIS Soundbox**, and their dynamic QRIS codes shown on it for bills printed from the POS.

The box is driven by **SoundboxBridge**, an Android app on the outlet's phone. The gateway
talks to the app through the merchant's own Telegram bot, so there is no app backend to call:
a webhook and the Telegram Bot API are all you need.

```mermaid
flowchart LR
    POS -- bill --> Box
    Box <-- Bluetooth --> App[SoundboxBridge]
    App <-- "Telegram (merchant's bot)" --> GW[Your gateway]
    GW <-- "charge / notification" --> PSP[Midtrans or your QRIS system]
```

## Start here

| | |
|---|---|
| [docs/protocol.md](docs/protocol.md) | The protocol: pairing link, message signing, every message type, timing |
| [docs/midtrans-integration.md](docs/midtrans-integration.md) | Step-by-step integration with the Midtrans Core API (QRIS) |
| [examples/midtrans-simulator](examples/midtrans-simulator) | A working gateway against the Midtrans sandbox, one Python file |
| [examples/signing](examples/signing) | Message signing and Midtrans notification checks in Python, Node.js, PHP, Go and Kotlin |

## In short

1. The merchant creates a Telegram bot and enters its token in your dashboard; you set its
   webhook.
2. Your dashboard shows a pairing link as a QR code; the merchant scans it in SoundboxBridge.
3. When the POS prints a bill, you get `qr.request` and answer `qr.created` with a dynamic QRIS
   for that amount, within 8 seconds.
4. When a payment settles, you send `payment.succeeded`, and the box announces it.

Every message is a signed Telegram text (`#QRISSB <json>|<HMAC-SHA256>`).

## Requirements

- Box firmware **1.3.0** or newer for gateways without a static QRIS (dynamic-only, e.g. Midtrans)
- A SoundboxBridge version that supports `"qr_mode": "dynamic"`
- A public HTTPS endpoint for Telegram webhooks (and your payment provider's notifications)

## Repository layout

```
docs/
  protocol.md                 the gateway protocol
  midtrans-integration.md     Midtrans Core API integration guide
examples/
  midtrans-simulator/         complete sandbox gateway (Python, standard library)
  signing/                    sign/verify snippets + shared test vectors
    python/ node/ php/ go/ kotlin/
    test-vectors.json
```
