"""Causal re-attestation chain. Design: gravity.aint; build: root_idd.

Trust is not a duration. Trust is a logical sequence of proven causal steps.
"""
import hashlib
import hmac

from tibet_mux import reattestation as ra


# A deterministic stub signer/verifier to exercise the crypto-check path.
_K = b"test-key"


def _sign(b):
    return "stub:" + hmac.new(_K, b, hashlib.sha256).hexdigest()


def _verify_sig(link):
    expected = _sign(ra.signing_bytes(link))
    return link.get("signature") == expected


def _jis():
    return {"challenge_nonce": "challenge-9a1f2b", "tpm_signature": "ed25519:x",
            "tpm_pubkey": "ed25519:y"}


def _chain():
    g = ra.build_link(actor="gpu0.p520.waint", actor_class="waint", causal_seq=8400,
                      posture_observed="#24358", relation_hash="sha256:rel", jis_proof=_jis(),
                      sign=_sign)
    l2 = ra.build_link(actor="gpu0.p520.waint", actor_class="waint", causal_seq=8460,
                       posture_observed="#24358", relation_hash="sha256:rel", jis_proof=_jis(),
                       prev_link=g, sign=_sign)
    return [g, l2]


def test_delta_c_per_band():
    assert ra.delta_c_for_band("P4") == 100
    assert ra.delta_c_for_band("P5") == 100
    assert ra.delta_c_for_band("P2") == 500
    assert ra.delta_c_for_band("P1") == 5000


def test_triggers():
    assert ra.needs_reattestation(current_seq=8450, expires_seq=8500) == []
    assert "causal_distance_exceeded" in ra.needs_reattestation(current_seq=8600, expires_seq=8500)
    assert "posture_transition" in ra.needs_reattestation(
        current_seq=10, expires_seq=9999, posture_changed=True)
    assert "phoenix_reset" in ra.needs_reattestation(
        current_seq=10, expires_seq=9999, phoenix_reset=True)
    assert "control_plane_revocation" in ra.needs_reattestation(
        current_seq=10, expires_seq=9999, revoked=True)


def test_expires_seq_is_causal():
    g = _chain()[0]
    # P4 lane (#24358) -> ΔC 100 -> expires at causal_seq + 100, NOT a clock time.
    assert g["expires_seq"] == 8400 + 100


def test_valid_chain_verifies():
    v = ra.verify_chain(_chain(), current_seq=8470, verify_sig=_verify_sig)
    assert v["ok"] is True
    assert v["posture"] == "#24358"


def test_broken_prev_hash_is_dark():
    # A validly-SIGNED link with a wrong prev_receipt_hash (replay/injection):
    # crypto passes, causal continuity must still catch it.
    c = _chain()
    c[1]["prev_receipt_hash"] = "sha256:" + "f" * 64
    c[1]["signature"] = _sign(ra.signing_bytes(c[1]))  # re-sign so crypto passes
    v = ra.verify_chain(c, current_seq=8470, verify_sig=_verify_sig)
    assert v["ok"] is False
    assert v["posture"] == "#00000"
    assert "prev_receipt_hash" in v["reason"]


def test_non_increasing_causal_seq_fails():
    c = _chain()
    c[1]["causal_seq"] = c[0]["causal_seq"]  # not increasing
    # rehash won't help: continuity check on seq order
    c[1]["prev_receipt_hash"] = ra.link_hash(c[0])
    c[1]["signature"] = _sign(ra.signing_bytes(c[1]))
    v = ra.verify_chain(c, current_seq=8470, verify_sig=_verify_sig)
    assert v["ok"] is False
    assert "monoton" in v["reason"]


def test_stale_chain_demands_reattest_or_dark():
    v = ra.verify_chain(_chain(), current_seq=99999, verify_sig=_verify_sig)
    assert v["ok"] is False
    assert v["posture"] == "#00000"
    assert "re-attest" in v["reason"] or "stale" in v["reason"]


def test_bad_signature_is_dark():
    c = _chain()
    c[1]["signature"] = "stub:deadbeef"
    v = ra.verify_chain(c, current_seq=8470, verify_sig=_verify_sig)
    assert v["ok"] is False
    assert "signature" in v["reason"]


def test_self_blocker_key_derivation():
    secret = b"tpm-root-secret"
    head = _chain()[1]
    k_good = ra.derive_next_key(secret, head)
    # same inputs -> same key (the legit next-layer key)
    assert ra.derive_next_key(secret, head) == k_good
    assert len(k_good) == 32
    # skip/fail a step -> different prev_hash or seq -> different key -> noise
    k_skip = ra.derive_payload_key(secret, head["prev_receipt_hash"], head["causal_seq"] + 1)
    assert k_skip != k_good
    k_tamper = ra.derive_payload_key(secret, "sha256:" + "f" * 64, head["causal_seq"])
    assert k_tamper != k_good
