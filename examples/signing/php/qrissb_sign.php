<?php
// QRIS Soundbox message signing + Midtrans notification check (PHP 7.4+, no packages).
//
//   #QRISSB <json>|<hex HMAC-SHA256 of the exact json, keyed with the base64 hmac_key>
//
// Run `php qrissb_sign.php` to check it against ../test-vectors.json.

const QRISSB_PREFIX = '#QRISSB';

/** Lowercase hex HMAC-SHA256 of the exact JSON text. */
function qrissb_sign(string $keyB64, string $jsonText): string
{
    return hash_hmac('sha256', $jsonText, base64_decode($keyB64, true));
}

/** Serialise once (compact, UTF-8 as is), sign that exact text, and wrap it. */
function qrissb_build_message(string $keyB64, array $obj): string
{
    $json = json_encode($obj, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    return QRISSB_PREFIX . ' ' . $json . '|' . qrissb_sign($keyB64, $json);
}

/**
 * Returns [array|null $obj, bool $verified]; $obj is null if it isn't a #QRISSB message.
 * The signature is checked against the received JSON text, never a re-serialised copy.
 */
function qrissb_parse_message(string $text, ?string $keyB64): array
{
    $t = trim($text);
    if (strpos($t, QRISSB_PREFIX) !== 0) return [null, false];
    $body = trim(substr($t, strlen(QRISSB_PREFIX)));
    $bar = strrpos($body, '|');
    $json = $body;
    $verified = false;
    if ($bar !== false && $bar > 0 && strlen($body) - $bar - 1 === 64) {
        $json = substr($body, 0, $bar);
        $verified = $keyB64 !== null &&
            hash_equals(qrissb_sign($keyB64, $json), strtolower(substr($body, $bar + 1)));
    }                                                 // else unsigned (only pairing.ok is sent like this)
    $obj = json_decode($json, true);
    return is_array($obj) ? [$obj, $verified] : [null, false];
}

/** SHA512(order_id + status_code + gross_amount + ServerKey), using the notification's own strings. */
function midtrans_signature_ok(array $n, string $serverKey): bool
{
    $raw = ($n['order_id'] ?? '') . ($n['status_code'] ?? '') . ($n['gross_amount'] ?? '') . $serverKey;
    return hash_equals(hash('sha512', $raw), strtolower((string)($n['signature_key'] ?? '')));
}

if (PHP_SAPI === 'cli' && realpath($argv[0] ?? '') === __FILE__) {
    $v = json_decode(file_get_contents(__DIR__ . '/../test-vectors.json'), true);
    $q = $v['qrissb'];
    assert_or_die(qrissb_sign($q['hmac_key'], $q['json']) === $q['sig'], 'sign');
    assert_or_die(qrissb_build_message($q['hmac_key'], json_decode($q['json'], true)) === $q['message'], 'build_message');
    [$obj, $ok] = qrissb_parse_message($q['message'], $q['hmac_key']);
    assert_or_die($ok && $obj['type'] === 'qr.created', 'parse_message');
    assert_or_die(!qrissb_parse_message($q['tampered_message'], $q['hmac_key'])[1], 'tampered');
    [$u, $uok] = qrissb_parse_message($q['unsigned_message'], null);
    assert_or_die(!$uok && $u['type'] === 'pairing.ok', 'unsigned');
    $m = $v['midtrans'];
    assert_or_die(midtrans_signature_ok($m['notification'], $m['server_key']), 'midtrans ok');
    assert_or_die(!midtrans_signature_ok(array_merge($m['notification'], ['gross_amount' => '1.00']), $m['server_key']), 'midtrans bad');
    echo "php: all test vectors pass\n";
}

function assert_or_die(bool $ok, string $what): void
{
    if (!$ok) { fwrite(STDERR, "php: FAILED $what\n"); exit(1); }
}
