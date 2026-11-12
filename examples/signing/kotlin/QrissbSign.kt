// QRIS Soundbox message signing + Midtrans notification check (Kotlin/JVM or Android API 26+,
// no libraries). Works on JSON *text*, so use any JSON library around it (org.json on Android).
//
//   #QRISSB <json>|<hex HMAC-SHA256 of the exact json, keyed with the base64 hmac_key>
//
// Check it with the vectors in ../test-vectors.json (see main below).

import java.security.MessageDigest
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object QrissbSign {
    const val PREFIX = "#QRISSB"

    /** Lowercase hex HMAC-SHA256 of the exact JSON text. */
    fun sign(keyB64: String, jsonText: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(Base64.getDecoder().decode(keyB64), "HmacSHA256"))
        return hex(mac.doFinal(jsonText.toByteArray(Charsets.UTF_8)))
    }

    /** Wraps JSON text you serialised once (e.g. JSONObject.toString()) and signs that exact text. */
    fun buildMessage(keyB64: String, jsonText: String): String = "$PREFIX $jsonText|${sign(keyB64, jsonText)}"

    /** jsonText = null: not a #QRISSB message. Parse jsonText yourself (e.g. JSONObject(jsonText)). */
    data class Parsed(val jsonText: String?, val verified: Boolean)

    /** The signature is checked against the received JSON text, never a re-serialised copy. */
    fun parseMessage(text: String, keyB64: String?): Parsed {
        val t = text.trim()
        if (!t.startsWith(PREFIX)) return Parsed(null, false)
        val body = t.removePrefix(PREFIX).trim()
        val bar = body.lastIndexOf('|')
        if (bar <= 0 || body.length - bar - 1 != 64) return Parsed(body, false)   // unsigned (pairing.ok)
        val json = body.substring(0, bar)
        val ok = keyB64 != null && MessageDigest.isEqual(
            sign(keyB64, json).toByteArray(), body.substring(bar + 1).lowercase().toByteArray())
        return Parsed(json, ok)
    }

    /** SHA512(order_id + status_code + gross_amount + ServerKey), using the notification's own strings. */
    fun midtransSignatureOk(orderId: String, statusCode: String, grossAmount: String,
                            signatureKey: String, serverKey: String): Boolean {
        val want = hex(MessageDigest.getInstance("SHA-512")
            .digest((orderId + statusCode + grossAmount + serverKey).toByteArray(Charsets.UTF_8)))
        return MessageDigest.isEqual(want.toByteArray(), signatureKey.lowercase().toByteArray())
    }

    private fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it.toInt() and 0xFF) }
}

// Self-check with the test vectors (the signing README shows how to pass them in):
//   kotlinc QrissbSign.kt -include-runtime -d check.jar && java -jar check.jar <10 values>
fun main(args: Array<String>) {
    require(args.size == 10) { "pass the 10 test-vector values, see the README" }
    val key = args[0]; val json = args[1]; val sig = args[2]; val message = args[3]; val tampered = args[4]
    val srv = args[5]; val orderId = args[6]; val status = args[7]; val gross = args[8]; val sigKey = args[9]
    check(QrissbSign.sign(key, json) == sig) { "sign" }
    check(QrissbSign.buildMessage(key, json) == message) { "buildMessage" }
    check(QrissbSign.parseMessage(message, key).let { it.verified && it.jsonText == json }) { "parseMessage" }
    check(!QrissbSign.parseMessage(tampered, key).verified) { "tampered" }
    check(QrissbSign.midtransSignatureOk(orderId, status, gross, sigKey, srv)) { "midtrans ok" }
    check(!QrissbSign.midtransSignatureOk(orderId, status, "1.00", sigKey, srv)) { "midtrans bad" }
    println("kotlin: all test vectors pass")
}
