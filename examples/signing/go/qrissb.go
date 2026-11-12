// Package qrissb signs and verifies QRIS Soundbox messages and checks Midtrans notification
// signatures (Go 1.18+, standard library only).
//
//	#QRISSB <json>|<hex HMAC-SHA256 of the exact json, keyed with the base64 hmac_key>
//
// Run `go test` to check it against ../test-vectors.json.
package qrissb

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/sha512"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"strings"
)

const Prefix = "#QRISSB"

// Sign returns the lowercase hex HMAC-SHA256 of the exact JSON text.
func Sign(keyB64, jsonText string) (string, error) {
	key, err := base64.StdEncoding.DecodeString(keyB64)
	if err != nil {
		return "", err
	}
	m := hmac.New(sha256.New, key)
	m.Write([]byte(jsonText))
	return hex.EncodeToString(m.Sum(nil)), nil
}

// BuildMessage serialises v once (compact, no HTML escaping), signs that exact text and wraps it.
// Use a struct to control the field order; a map is serialised with sorted keys (also fine).
func BuildMessage(keyB64 string, v any) (string, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return "", err
	}
	j := strings.TrimSuffix(buf.String(), "\n")
	sig, err := Sign(keyB64, j)
	if err != nil {
		return "", err
	}
	return Prefix + " " + j + "|" + sig, nil
}

// ParseMessage returns the JSON text and whether its signature checks out. ok is false and json
// empty if text isn't a #QRISSB message. The signature is checked against the received text,
// never a re-serialised copy. Unmarshal json yourself.
func ParseMessage(text, keyB64 string) (jsonText string, verified bool, ok bool) {
	t := strings.TrimSpace(text)
	if !strings.HasPrefix(t, Prefix) {
		return "", false, false
	}
	body := strings.TrimSpace(t[len(Prefix):])
	bar := strings.LastIndex(body, "|")
	if bar > 0 && len(body)-bar-1 == 64 {
		jsonText = body[:bar]
		if keyB64 != "" {
			if want, err := Sign(keyB64, jsonText); err == nil {
				verified = hmac.Equal([]byte(want), []byte(strings.ToLower(body[bar+1:])))
			}
		}
	} else {
		jsonText = body // unsigned (only pairing.ok is sent like this)
	}
	return jsonText, verified, json.Valid([]byte(jsonText))
}

// MidtransSignatureOK checks SHA512(order_id + status_code + gross_amount + ServerKey), using the
// notification's own strings.
func MidtransSignatureOK(orderID, statusCode, grossAmount, signatureKey, serverKey string) bool {
	sum := sha512.Sum512([]byte(orderID + statusCode + grossAmount + serverKey))
	want := hex.EncodeToString(sum[:])
	return subtle.ConstantTimeCompare([]byte(want), []byte(strings.ToLower(signatureKey))) == 1
}
