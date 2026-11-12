"""
QRIS Soundbox message signing + Midtrans notification check (Python 3, standard library only).

    #QRISSB <json>|<hex HMAC-SHA256 of the exact json, keyed with the base64 hmac_key>

Run this file to check it against ../test-vectors.json.
"""
import base64
import hashlib
import hmac
import json

PREFIX = "#QRISSB"


def sign(key_b64: str, json_text: str) -> str:
    """Lowercase hex HMAC-SHA256 of the exact JSON text."""
    return hmac.new(base64.b64decode(key_b64), json_text.encode("utf-8"), hashlib.sha256).hexdigest()


def build_message(key_b64: str, obj: dict) -> str:
    """Serialise compactly once, sign that exact text, and wrap it."""
    j = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return f"{PREFIX} {j}|{sign(key_b64, j)}"


def parse_message(text: str, key_b64: str):
    """Returns (obj, verified). obj is None if it isn't a #QRISSB message.
    The signature is checked against the received JSON text, never a re-serialised copy."""
    t = text.strip()
    if not t.startswith(PREFIX):
        return None, False
    body = t[len(PREFIX):].strip()
    bar = body.rfind("|")
    if bar > 0 and len(body) - bar - 1 == 64:
        json_text, sig = body[:bar], body[bar + 1:]
        ok = key_b64 is not None and hmac.compare_digest(sign(key_b64, json_text), sig.lower())
    else:
        json_text, ok = body, False                  # unsigned (only pairing.ok is sent like this)
    try:
        return json.loads(json_text), ok
    except ValueError:
        return None, False


def midtrans_signature_ok(notification: dict, server_key: str) -> bool:
    """SHA512(order_id + status_code + gross_amount + ServerKey), using the notification's own strings."""
    raw = f"{notification.get('order_id', '')}{notification.get('status_code', '')}" \
          f"{notification.get('gross_amount', '')}{server_key}"
    expected = hashlib.sha512(raw.encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, str(notification.get("signature_key", "")).lower())


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    v = json.load(open(os.path.join(here, "..", "test-vectors.json"), encoding="utf-8"))
    q = v["qrissb"]
    assert sign(q["hmac_key"], q["json"]) == q["sig"], "sign"
    assert build_message(q["hmac_key"], json.loads(q["json"])) == q["message"], "build_message"
    obj, ok = parse_message(q["message"], q["hmac_key"])
    assert ok and obj["type"] == "qr.created", "parse_message"
    assert not parse_message(q["tampered_message"], q["hmac_key"])[1], "tampered"
    assert parse_message(q["unsigned_message"], None) == (json.loads(q["unsigned_message"][8:]), False), "unsigned"
    m = v["midtrans"]
    assert midtrans_signature_ok(m["notification"], m["server_key"]), "midtrans ok"
    assert not midtrans_signature_ok({**m["notification"], "gross_amount": "1.00"}, m["server_key"]), "midtrans bad"
    print("python: all test vectors pass")
