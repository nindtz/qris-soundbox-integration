package qrissb

import (
	"encoding/json"
	"os"
	"testing"
)

type vectors struct {
	Qrissb struct {
		HmacKey         string `json:"hmac_key"`
		JSON            string `json:"json"`
		Sig             string `json:"sig"`
		Message         string `json:"message"`
		TamperedMessage string `json:"tampered_message"`
		UnsignedMessage string `json:"unsigned_message"`
	} `json:"qrissb"`
	Midtrans struct {
		ServerKey    string            `json:"server_key"`
		Notification map[string]string `json:"notification"`
	} `json:"midtrans"`
}

// Same fields, in the same order, as the message in the test vectors.
type qrCreated struct {
	V         int    `json:"v"`
	Type      string `json:"type"`
	DeviceID  string `json:"device_id"`
	OutletID  string `json:"outlet_id"`
	Ts        int64  `json:"ts"`
	RequestID string `json:"request_id"`
	Amount    int64  `json:"amount"`
	Qris      string `json:"qris"`
	ExpiresAt string `json:"expires_at"`
	Note      string `json:"note"`
}

func TestVectors(t *testing.T) {
	raw, err := os.ReadFile("../test-vectors.json")
	if err != nil {
		t.Fatal(err)
	}
	var v vectors
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	q := v.Qrissb

	if sig, _ := Sign(q.HmacKey, q.JSON); sig != q.Sig {
		t.Fatalf("Sign: got %s", sig)
	}
	var obj qrCreated
	if err := json.Unmarshal([]byte(q.JSON), &obj); err != nil {
		t.Fatal(err)
	}
	if msg, _ := BuildMessage(q.HmacKey, obj); msg != q.Message {
		t.Fatalf("BuildMessage: got %s", msg)
	}
	if j, ok, isMsg := ParseMessage(q.Message, q.HmacKey); !isMsg || !ok || j != q.JSON {
		t.Fatal("ParseMessage: valid message not verified")
	}
	if _, ok, _ := ParseMessage(q.TamperedMessage, q.HmacKey); ok {
		t.Fatal("ParseMessage: tampered message verified")
	}
	if _, ok, isMsg := ParseMessage(q.UnsignedMessage, ""); !isMsg || ok {
		t.Fatal("ParseMessage: unsigned message handled wrong")
	}

	n, key := v.Midtrans.Notification, v.Midtrans.ServerKey
	if !MidtransSignatureOK(n["order_id"], n["status_code"], n["gross_amount"], n["signature_key"], key) {
		t.Fatal("MidtransSignatureOK: valid notification rejected")
	}
	if MidtransSignatureOK(n["order_id"], n["status_code"], "1.00", n["signature_key"], key) {
		t.Fatal("MidtransSignatureOK: changed amount accepted")
	}
	t.Log("go: all test vectors pass")
}
