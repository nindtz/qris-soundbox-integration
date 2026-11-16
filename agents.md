# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## What this repo is

Public integration kit for **payment gateways (PGs)** that want to connect to the
**QRIS Soundbox** ecosystem. A PG acts as the **Owner**; the merchant's phone
running **SoundboxBridge** acts only as a **Branch** and relays payments to the
soundbox hardware, which announces them out loud.

- Product site: https://nindtz.github.io/qris-soundbox/
- Reference PG for docs and examples: **Midtrans** (QRIS sandbox)
- Audience: external developers at payment gateways and POS vendors

## Core architecture (do not change without the maintainer)

- **No QRIS Soundbox backend exists.** The product is buy-once with no server.
  Never propose or add a hosted relay, MQTT broker, or central API run by
  QRIS Soundbox.
- **Transport is always Telegram.** Each merchant creates their own bot via
  BotFather and enters the bot token in the PG's dashboard. The PG talks to the
  merchant's SoundboxBridge through that bot.
- **Pairing:** the PG (as Owner) shows a pairing QR; the branch phone scans it
  in SoundboxBridge.
- **Static QRIS:** PG sends payment notifications → SoundboxBridge → box announces.
- **Dynamic QRIS:** amount from the POS flows box → SoundboxBridge → PG; the PG
  creates a dynamic QR and sends it back for the box to display. A
  dynamic-only box mode is supported (needed for Midtrans, which has no static QRIS).
- QRIS Soundbox takes no fee on PG integrations.

## Repo conventions

- **Documentation is English only.**
- Keep docs and examples in sync: if a message format, field, or step changes
  in the docs, update every example that uses it in the same change.
- Examples must run against **sandbox** credentials only. Never commit real
  bot tokens, server keys, merchant IDs, or QRIS strings. Use placeholders such
  as `YOUR_BOT_TOKEN` / `YOUR_MIDTRANS_SERVER_KEY` and read secrets from env vars.
- Prefer small, copy-pasteable examples over frameworks. A PG developer should
  be able to read one file and understand the flow.
- Don't invent protocol fields. If a field isn't defined in the docs, ask
  rather than guessing — the firmware and SoundboxBridge app parse these messages.

## Related code (not in this repo)

- Soundbox firmware (Arduino, ESP32): Waveshare ESP32-S3-ePaper 3.97,
  1.54 V2 "mini", and ESP32-2432S028 (CYD)
- SoundboxBridge Android app (`id.nindita.qrissbbridge`) and an iOS
  branch-only app

Changes here must stay compatible with what those clients already parse.

## Before finishing a change

- [ ] Docs and examples agree on every message format touched
- [ ] No secrets, tokens, or real merchant data in the diff
- [ ] Examples still run against the Midtrans sandbox
- [ ] Wording is clear for a non-Indonesian developer
