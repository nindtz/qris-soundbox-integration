#!/usr/bin/env python3
r"""
pg_sim_midtrans.py - the webhook gateway simulator (pg_sim_webhook.py), but the dynamic QRIS now
comes from the Midtrans SANDBOX (Core API, payment_type "qris") instead of being made locally,
and "paid" comes from Midtrans' payment notification instead of the 'pay' command.

DYNAMIC-ONLY by default: Midtrans has no static QRIS, so the pairing link carries
    "qr_mode": "dynamic"      and no "qris"
The app then gives the box a dynamic-only identity (dyn_id.h, firmware 1.3.0+): the box shows the
"Kami menerima" QRIS / GPN badge while idle, every QR comes from Midtrans, and "QR gagal" when
none comes. Needs an app version that knows "qr_mode"; older apps reject a link without "qris".
With --qris "<static QRIS>" the link carries that QRIS instead (no "qr_mode"), for older apps.

Needs Python 3.8+ only (no packages). Optional: `pip install qrcode` to draw the pairing QR in
the terminal; otherwise copy the link and use "Paste link" in the app.

Midtrans requests used (https://docs.midtrans.com/reference/qris) - only these two:
 1. POST https://api.sandbox.midtrans.com/v2/charge   payment_type=qris  -> qr_string + QR image
 2. Midtrans -> us: HTTP POST payment notification (pending / settlement / expire / deny),
    received on the same server and tunnel as the Telegram webhook, at /midtrans/notify.
    The notification URL is sent with every charge in the X-Override-Notification header, so
    nothing needs setting in the Midtrans dashboard (handy, since free tunnel URLs change).
    Each notification is checked with its signature_key:
        SHA512(order_id + status_code + gross_amount + server_key)

HOW TO RUN
 1. Telegram: @BotFather -> /newbot -> copy the token (the merchant's own bot).
 2. Midtrans: sign up, switch the dashboard to Sandbox, Settings > Access Keys, copy the
    Server Key (starts with SB-Mid-server-).
 3. Start a tunnel to local port 8080, e.g. Pinggy:
        ssh -p 443 -R0:localhost:8080 a.pinggy.io
 4. Start the simulator:
        python3 pg_sim_midtrans.py --token <BOT_TOKEN> --server-key <SB-Mid-server-...> \
            --public-url https://abcd-12-34.a.free.pinggy.link [--outlet-name "Kopi Senja"]
    (add --qris "<static QRIS>" only for an app without dynamic-only support; payments made to
    that static QR are NOT announced, since they don't go through Midtrans)
 5. In the app: Branch > Scan pairing QR (or Paste link). Print a bill from the POS.
 6. To pay: copy the "QR image:" URL logged with each charge (or type "pay" to show the
    last one again), open the Midtrans sandbox QRIS simulator
    (https://simulator.sandbox.midtrans.com/v2/qris/index), paste the URL, and pay.
    Midtrans then POSTs a "settlement" notification and the box announces the payment.
    Commands: pay | fail | revoke | link | info | quit

TIMING: the box waits PG_WAIT_MS (8 s) for the QR after a bill is printed, and so does the app.
Each qr.created line shows how long the Midtrans charge and the whole answer took; a dynamic-only
box shows "QR gagal" when it's later than that. "fail" makes the next request fail on purpose.
"""
import argparse, base64, hashlib, hmac, json, os, queue, re, secrets, sys, threading, time
import urllib.request, urllib.error
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PREFIX = "#QRISSB "
MIDTRANS_SANDBOX = "https://api.sandbox.midtrans.com"
NOTIFY_PATH = "/midtrans/notify"

# ---------- Telegram Bot API ----------
class Bot:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method, **params):
        data = json.dumps(params).encode()
        req = urllib.request.Request(self.base + method, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r)
        except urllib.error.HTTPError as e:
            res = json.load(e)
        if not res.get("ok"):
            raise RuntimeError(f"{method}: {res.get('error_code')} {res.get('description')}")
        return res["result"]

# ---------- Midtrans Core API (sandbox) ----------
class MidtransError(RuntimeError):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = str(code)

class Midtrans:
    def __init__(self, server_key, notify_url):
        self.key = server_key
        self.auth = "Basic " + base64.b64encode((server_key + ":").encode()).decode()
        self.notify_url = notify_url

    def charge_qris(self, order_id, amount, acquirer):
        """Request 1: POST /v2/charge with only the required fields (+ the acquirer)."""
        body = {"payment_type": "qris",
                "transaction_details": {"order_id": order_id, "gross_amount": amount},
                "qris": {"acquirer": acquirer}}
        req = urllib.request.Request(MIDTRANS_SANDBOX + "/v2/charge", data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "Authorization": self.auth, "X-Override-Notification": self.notify_url})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r)
        except urllib.error.HTTPError as e:
            res = json.load(e)
        if str(res.get("status_code")) != "201":       # Midtrans may answer HTTP 200 with an error code inside
            extra = "; ".join(res.get("validation_messages") or [])
            raise MidtransError(res.get("status_code"),
                                f"charge: {res.get('status_code')} {res.get('status_message')} {extra}".strip())
        return res

    def signature_ok(self, n):
        raw = f"{n.get('order_id', '')}{n.get('status_code', '')}{n.get('gross_amount', '')}{self.key}"
        return hmac.compare_digest(hashlib.sha512(raw.encode()).hexdigest(), str(n.get("signature_key", "")))

def mt_iso(s):
    """Midtrans times are 'YYYY-MM-DD HH:MM:SS' in GMT+7."""
    return s.replace(" ", "T") + "+07:00"

def expiry_of(res):
    if res.get("expiry_time"):
        return mt_iso(res["expiry_time"])
    t = datetime.strptime(res["transaction_time"], "%Y-%m-%d %H:%M:%S") + timedelta(minutes=15)  # QRIS default
    return t.strftime("%Y-%m-%dT%H:%M:%S") + "+07:00"

def order_ids(outlet, rid, ref, now):
    """Midtrans order_id candidates, best first. Allowed: letters, digits, - _ ~ . ; at most 50."""
    clean = lambda s: re.sub(r"[^A-Za-z0-9_.~-]", "-", s)
    if ref:
        r = clean(ref)[:25]                            # pos_ref is at most 25 characters anyway
        code = rid[3:] if rid.startswith("sb_") else rid
        return [r, f"{r}-{code}"]                      # "SO1", then "SO1-0a1b2c3d" if SO1 was used
    return [clean(f"{outlet}-{rid}-{int(now)}")[-50:]] # no order number on the receipt

def qr_image_url(res):
    for a in res.get("actions") or []:
        if a.get("name") == "generate-qr-code":
            return a.get("url")
    return None

# ---------- QRIS ----------
def crc16(data: bytes) -> str:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"

def qris_ok(q):
    return len(q) > 12 and crc16(q[:-4].encode()) == q[-4:].upper()

# ---------- messages: "#QRISSB <json>|<hex HMAC-SHA256 of the exact json>" ----------
def sign(key_b64, json_text):
    return hmac.new(base64.b64decode(key_b64), json_text.encode(), hashlib.sha256).hexdigest()

def signed(key_b64, obj):
    j = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return f"{PREFIX}{j}|{sign(key_b64, j)}"

def parse(text, key_b64):
    if not text.startswith(PREFIX.strip()):
        return None, False
    body = text[len(PREFIX.strip()):].strip()
    bar = body.rfind("|")
    if bar > 0 and len(body) - bar - 1 == 64:
        j, sig = body[:bar], body[bar + 1:]
        ok = key_b64 is not None and hmac.compare_digest(sign(key_b64, j), sig.lower())
    else:
        j, ok = body, False
    try:
        return json.loads(j), ok
    except ValueError:
        return None, False

def iso_in(seconds):
    t = time.localtime(time.time() + seconds)
    off = time.strftime("%z", t)
    return time.strftime("%Y-%m-%dT%H:%M:%S", t) + off[:3] + ":" + off[3:]

def rupiah(n):
    return f"Rp {n:,}".replace(",", ".")

def log(tag, msg):
    print(f"{time.strftime('%H:%M:%S')} [{tag}] {msg}", flush=True)

# ---------- one merchant (a real gateway keeps these in its database) ----------
class Merchant:
    def __init__(self, a, state):
        self.id = a.merchant_id
        self.token = a.token                           # stored encrypted in production
        self.bot = Bot(a.token)
        self.secret = secrets.token_urlsafe(32)        # secret_token for this bot's webhook
        self.username = None
        self.qris, self.pin, self.acquirer = a.qris, a.pin, a.acquirer
        self.outlet, self.outlet_name, self.merchant_name, self.provider = a.outlet, a.outlet_name, a.merchant, a.provider
        self.devices = state.get("devices", {})       # chat id -> {device_id, key}
        self.pairing_token = None
        self.fail_next = False
        self.last_qr_url = None

# ---------- the gateway ----------
class Gateway:
    def __init__(self, a):
        self.a = a
        st = json.load(open(a.state)) if os.path.exists(a.state) else {}
        m = Merchant(a, st)
        self.merchants = {m.id: m}                     # webhook path /telegram/<id> -> merchant
        self.m = m
        self.mt = Midtrans(a.server_key, a.public_url.rstrip("/") + NOTIFY_PATH)
        self.orders = {}                               # Midtrans order_id -> (merchant, chat id, request id, ref)
        self.done = set()                              # transaction_ids already announced (notifications repeat)
        self.jobs = queue.Queue()
        self.lock = threading.Lock()

    def save(self):
        json.dump({"devices": self.m.devices}, open(self.a.state, "w"), indent=1)

    # ----- dashboard: "merchant saved their bot token" -----
    def connect_bot(self):
        m = self.m
        me = m.bot.call("getMe")
        m.username = me["username"]
        url = f"{self.a.public_url.rstrip('/')}/telegram/{m.id}"
        m.bot.call("setWebhook", url=url, secret_token=m.secret, allowed_updates=["message"],
                   drop_pending_updates=True, max_connections=10)
        log("webhook", f"setWebhook for @{m.username} -> {url}")
        log("midtrans", f"notifications will come to {self.mt.notify_url}")

    def disconnect_bot(self):
        try:
            self.m.bot.call("deleteWebhook")
            log("webhook", "deleteWebhook: the bot is free again (pg_sim.py / getUpdates work)")
        except Exception as e:
            log("webhook", f"deleteWebhook failed: {e}")

    def webhook_info(self):
        i = self.m.bot.call("getWebhookInfo")
        log("webhook", f"url={i.get('url')} pending={i.get('pending_update_count')} "
                       f"last_error={i.get('last_error_message', '-')}")

    # ----- web server side: check, accept, queue (must be quick) -----
    def accept(self, path, headers, body):
        if path.rstrip("/") == NOTIFY_PATH:
            return self.accept_midtrans(body)
        parts = path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "telegram" or parts[1] not in self.merchants:
            log("http", f"404 {path}")
            return 404
        m = self.merchants[parts[1]]
        given = headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(given, m.secret):
            log("http", f"401 {path}: wrong or missing X-Telegram-Bot-Api-Secret-Token (not from Telegram)")
            return 401
        try:
            update = json.loads(body)
        except ValueError:
            return 400
        log("webhook", f"POST from Telegram, update {update.get('update_id')} -> 200, queued")
        self.jobs.put(("tg", m, update))
        return 200

    def accept_midtrans(self, body):
        try:
            n = json.loads(body)
        except ValueError:
            return 400
        if not self.mt.signature_ok(n):
            log("http", f"403 {NOTIFY_PATH}: bad signature_key (not from Midtrans, or wrong server key)")
            return 403
        log("midtrans", f"notification {n.get('order_id')}: {n.get('transaction_status')} -> 200, queued")
        self.jobs.put(("mt", None, n))
        return 200

    def worker(self):
        while True:
            kind, m, data = self.jobs.get()
            try:
                if kind == "tg":
                    msg = data.get("message") or {}
                    if "text" in msg:
                        self.on_text(m, str(msg["chat"]["id"]), msg["text"])
                else:
                    self.on_notification(data)
            except Exception as e:
                log("pg", f"error: {e}")

    # ----- the gateway's QRIS Soundbox logic -----
    def base(self, m, dev, typ):
        return {"v": 1, "type": typ, "device_id": dev["device_id"], "outlet_id": m.outlet, "ts": int(time.time())}

    def send(self, m, chat_id, text, what):
        m.bot.call("sendMessage", chat_id=int(chat_id), text=text)
        log("pg", f"sendMessage -> {what}")

    def pairing_link(self):
        m = self.m
        m.pairing_token = "pt_" + secrets.token_hex(12)
        d = {"v": 1, "role": "owner", "provider": m.provider, "merchant_name": m.merchant_name,
             "outlet_id": m.outlet, "outlet_name": m.outlet_name,
             "transport": {"type": "telegram_bot", "bot": m.username},
             "pairing_token": m.pairing_token, "expires_at": iso_in(600)}
        if m.qris:
            d["qris"] = m.qris                         # older apps: the box keeps a static QR
        else:
            d["qr_mode"] = "dynamic"                   # Midtrans has no static QRIS: every QR from us
        if m.pin:
            d["pin"] = m.pin
        raw = base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).decode().rstrip("=")
        return "soundboxbridge://pair?d=" + raw

    def on_text(self, m, chat_id, text):
        if text.startswith("/start"):
            token = text[6:].strip()
            if not token or token != m.pairing_token:
                log("pg", f"/start with an unknown or used pairing token from chat {chat_id}")
                return
            m.pairing_token = None                         # one-time
            dev = {"device_id": "dev_" + secrets.token_hex(4), "key": base64.b64encode(secrets.token_bytes(32)).decode()}
            m.devices[chat_id] = dev
            self.save()
            ok = {"v": 1, "type": "pairing.ok", "pairing_token": token, "device_id": dev["device_id"],
                  "outlet_id": m.outlet, "hmac_key": dev["key"], "ts": int(time.time())}
            log("pg", f"/start: paired chat {chat_id} as {dev['device_id']}")
            self.send(m, chat_id, PREFIX + json.dumps(ok, separators=(",", ":")), "pairing.ok (unsigned, carries the key)")
            return
        dev = m.devices.get(chat_id)
        obj, good = parse(text, dev and dev["key"])
        if obj is None:
            return
        if not dev or not good:
            log("pg", f"{obj.get('type')}: bad signature or unpaired chat, ignored")
            return
        if obj.get("device_id") != dev["device_id"] or obj.get("outlet_id") != m.outlet or abs(time.time() - obj.get("ts", 0)) > 300:
            log("pg", f"{obj.get('type')}: other device/outlet or too old, ignored")
            return
        typ = obj.get("type")
        if typ == "qr.request":
            self.on_qr_request(m, chat_id, dev, obj)
        elif typ == "qr.cancel":
            log("pg", f"qr.cancel {obj.get('request_id')} (the Midtrans QR simply expires)")
        else:
            log("pg", f"{typ}: not handled by the simulator")

    def on_qr_request(self, m, chat_id, dev, obj):
        rid, amount, ref = obj["request_id"], int(obj["amount"]), obj.get("pos_ref", "")
        t0 = time.time()
        log("pg", f"qr.request {rid}: {rupiah(amount)}" + (f", order {ref}" if ref else ""))

        def failed(reason):
            self.send(m, chat_id, signed(dev["key"], {**self.base(m, dev, "qr.failed"), "request_id": rid,
                                                      "reason": reason}), f"qr.failed ({reason})")
        if m.fail_next:
            m.fail_next = False
            return failed("simulated failure")
        # Midtrans order_id: the POS order number when the receipt has one, so the merchant finds the
        # same number in the Midtrans dashboard. It must be unique across the whole account, so a
        # reprinted bill (or another outlet's "SO1") gets the bill's code appended on a retry.
        try:
            res, order_id = self.charge_with_order_ids(m, order_ids(m.outlet, rid, ref, t0), amount)
            t_charge = time.time() - t0
        except Exception as e:
            log("midtrans", str(e))
            return failed("gateway error")
        qr_url = qr_image_url(res)
        log("midtrans", f"charge {order_id}: {res.get('transaction_status')}, transaction {res.get('transaction_id')}")
        log("midtrans", f"QR image: {qr_url or '(none in the response)'}")
        qris = res.get("qr_string")
        if not qris:
            log("midtrans", f"no qr_string in the charge response; QR image only: {qr_url}")
            return failed("no QR string from gateway")
        with self.lock:
            self.orders[order_id] = (m, chat_id, rid, ref)
            m.last_qr_url = qr_url
        msg = {**self.base(m, dev, "qr.created"), "request_id": rid, "amount": amount,
               "qris": qris, "expires_at": expiry_of(res)}
        self.send(m, chat_id, signed(dev["key"], msg), "qr.created")
        took = time.time() - t0
        log("pg", f"answered in {took:.1f} s (Midtrans charge {t_charge:.1f} s)"
                  + ("  <-- over 8 s: the box has given up (\"QR gagal\")" if took > 8 else "")
                  + ". Paste the QR image URL above into the Midtrans simulator to pay.")

    def charge_with_order_ids(self, m, candidates, amount):
        """Tries each order_id in turn; moves on only when Midtrans says it's already used (406)."""
        for i, oid in enumerate(candidates):
            try:
                return self.mt.charge_qris(oid, amount, m.acquirer), oid
            except MidtransError as e:
                if e.code == "406" and i + 1 < len(candidates):
                    log("midtrans", f"order_id {oid} already used (reprinted bill?): trying {candidates[i + 1]}")
                    continue
                raise

    def on_notification(self, n):
        oid, status, tid = n.get("order_id"), n.get("transaction_status"), n.get("transaction_id")
        with self.lock:
            order = self.orders.get(oid)
        if not order:
            log("midtrans", f"{oid}: unknown order (made before this run?), ignored")
            return
        m, chat_id, rid, ref = order
        if status in ("settlement", "capture"):
            with self.lock:
                if tid in self.done:
                    log("midtrans", f"{oid}: repeated settlement, already announced")
                    return
                self.done.add(tid)
            dev = m.devices.get(chat_id)
            if not dev:
                log("pg", f"{oid}: paid, but that phone is no longer paired")
                return
            amount = int(float(n.get("gross_amount", "0")))
            msg = {**self.base(m, dev, "payment.succeeded"), "event_id": tid, "request_id": rid, "amount": amount,
                   "currency": n.get("currency", "IDR"),
                   "paid_at": mt_iso(n["settlement_time"]) if n.get("settlement_time") else iso_in(0),
                   "issuer": (n.get("issuer") or n.get("acquirer") or "").upper(),
                   "rrn": n.get("reference_id") or tid}
            if ref:
                msg["reference"] = ref                     # the POS order number, echoed back
            self.send(m, chat_id, signed(dev["key"], msg), f"payment.succeeded {rupiah(amount)}")
        elif status in ("expire", "deny", "cancel", "failure"):
            log("midtrans", f"{oid}: {status}, nothing to announce")
            with self.lock:
                self.orders.pop(oid, None)
        else:
            log("midtrans", f"{oid}: {status}")

    def pay(self):
        url = self.m.last_qr_url
        if not url:
            log("pg", "no QR made yet: print a bill from the POS first")
            return
        print(f"\nOpen https://simulator.sandbox.midtrans.com/v2/qris/index and paste this QR image URL:\n{url}\n")

    def revoke(self):
        m = self.m
        for chat, dev in list(m.devices.items()):
            self.send(m, chat, signed(dev["key"], self.base(m, dev, "device.revoked")), "device.revoked")
        m.devices.clear()
        self.save()

def make_handler(gw):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n) if n else b""
            code = gw.accept(self.path, self.headers, body)
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):                           # handy to check the tunnel in a browser
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"pg_sim_midtrans is running. Telegram POSTs to /telegram/<merchant id>, "
                             b"Midtrans to /midtrans/notify.\n")

        def log_message(self, *args):
            pass
    return Handler

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--token", required=True, help="the merchant's bot token from @BotFather")
    p.add_argument("--server-key", required=True, help="Midtrans SANDBOX server key (SB-Mid-server-...)")
    p.add_argument("--public-url", required=True, help="the tunnel's https URL (Pinggy, ngrok, cloudflared...)")
    p.add_argument("--qris", default="", help="static QRIS for older apps (default: none, dynamic-only pairing)")
    p.add_argument("--acquirer", default="gopay", choices=["gopay", "airpay shopee"], help="Midtrans QRIS acquirer")
    p.add_argument("--port", type=int, default=8080, help="local port the tunnel forwards to")
    p.add_argument("--pin", default="", help="soundbox settings PIN to put in the pairing QR (optional)")
    p.add_argument("--merchant-id", default="m-0001", help="the gateway's merchant id (in the webhook path)")
    p.add_argument("--outlet", default="OUT-TEST")
    p.add_argument("--outlet-name", default="Test outlet")
    p.add_argument("--merchant", default="Test merchant")
    p.add_argument("--provider", default="MIDTRANS-SANDBOX")
    p.add_argument("--state", default="pg_sim_state.json", help="where paired phones are remembered")
    p.add_argument("--keep-webhook", action="store_true", help="leave the Telegram webhook set when quitting")
    a = p.parse_args()
    if not a.public_url.startswith("https://"):
        sys.exit("--public-url must be https:// (Telegram and Midtrans only call HTTPS URLs)")
    if a.qris and not qris_ok(a.qris):
        sys.exit("--qris: CRC doesn't match, check the QRIS text")
    if not a.server_key.startswith("SB-"):
        sys.exit("--server-key: this simulator only talks to the sandbox; use the SB-Mid-server-... key")

    gw = Gateway(a)
    server = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(gw))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=gw.worker, daemon=True).start()
    log("http", f"listening on http://localhost:{a.port} (the tunnel forwards {a.public_url} here)")

    gw.connect_bot()
    log("pg", "pairing mode: " + ("static QRIS in the link (older apps)" if a.qris
                                 else "dynamic-only (qr_mode \"dynamic\", no static QRIS)"))
    link = gw.pairing_link()
    print(f"\nPairing link (valid 10 min, one phone):\n{link}\n")
    try:
        import qrcode
        q = qrcode.QRCode(border=1)
        q.add_data(link)
        q.print_ascii(invert=True)
    except ImportError:
        print("(pip install qrcode to show it as a QR here; or use 'Paste link' in the app)\n")
    print("Commands: pay | fail | revoke | link | info | quit\n")
    try:
        for line in sys.stdin:
            cmd = line.split()
            if not cmd:
                continue
            try:
                if cmd[0] == "pay":
                    gw.pay()
                elif cmd[0] == "fail":
                    gw.m.fail_next = True
                    log("pg", "the next qr.request will fail")
                elif cmd[0] == "revoke":
                    gw.revoke()
                elif cmd[0] == "link":
                    print(gw.pairing_link())
                elif cmd[0] == "info":
                    gw.webhook_info()
                elif cmd[0] in ("quit", "exit"):
                    break
            except Exception as e:
                log("pg", str(e))
    except KeyboardInterrupt:
        pass
    if not a.keep_webhook:
        gw.disconnect_bot()
    server.shutdown()

if __name__ == "__main__":
    main()