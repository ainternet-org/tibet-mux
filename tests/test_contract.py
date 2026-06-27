"""Conformance acceptance for the tibet-mux v1.1.0 verifier family (#109 contract).

Lifted from Codex' three-way-accepted reference test (import retargeted to the
package module). Keep byte-for-byte aligned with enclave mux-frame-vectors.json.

    python3 -m pytest packages/tibet-mux/tests/test_contract.py
"""

import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tibet_mux.verify import (
    canonical_without,
    sign_canonical,
    verify_actor_challenge,
    verify_ipoll_headers,
    verify_mux_frame,
    verify_relation,
)


def _pub_hex(priv):
    return priv.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()


def test_canonical_byte_contract():
    value = {"b": {"z": 1, "a": 2}, "sig": "ignored", "a": "x"}
    assert canonical_without(value, ("sig",)) == b'a="x"\x1fb={"a":2,"z":1}'


def test_actor_challenge_valid_and_negative_cases():
    priv = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    pub = _pub_hex(priv)
    now = int(time.time())
    challenge = f"nonce:{now}"
    sig = priv.sign(challenge.encode()).hex()

    assert verify_actor_challenge("richard.test.aint", challenge, sig, pub).ok
    assert not verify_actor_challenge("richard.test.aint", "nonce:1", sig, pub).ok
    assert not verify_actor_challenge("richard.test.aint", challenge, "00" * 64, pub).ok


def test_ipoll_headers_do_not_trust_body_actor_claim():
    priv = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    pub = _pub_hex(priv)
    now = int(time.time())
    challenge = f"nonce:{now}"
    headers = {
        "X-Agent-ID": "codex.aint",
        "X-Challenge": challenge,
        "X-Signature": priv.sign(challenge.encode()).hex(),
    }

    def resolve(agent):
        return pub if agent == "codex.aint" else None

    assert verify_ipoll_headers(headers, resolve, from_agent="codex.aint").ok
    assert not verify_ipoll_headers(headers, resolve, from_agent="gravity.aint").ok


def test_mux_frame_vector_shape_and_tamper():
    priv = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    pub = _pub_hex(priv)
    ts = int(time.time())
    frame = {
        "v": "org.ainternet.mux.frame.v1",
        "from_aint": "richard.test.aint",
        "to_aint": "raint-a.test.aint",
        "surface": "handshake.aint",
        "intent": "probe",
        "lane_id": "lane-1",
        "consent_receipt_hash": "sha256:" + "ab" * 32,
        "nonce": "mux-1",
        "ts": ts,
        "cap": None,
    }
    signed = sign_canonical(frame, priv)
    assert verify_mux_frame(signed, pub, now=ts).ok

    tampered = dict(signed)
    tampered["surface"] = "capture.this"
    assert not verify_mux_frame(tampered, pub, now=ts).ok


def test_relation_requires_all_signatures_and_detects_tamper():
    a = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    b = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    pubkeys = {"raint-a.test.aint": _pub_hex(a), "raint-b.test.aint": _pub_hex(b)}
    now = int(time.time())
    relation = {
        "kind": "org.ainternet.redstone.relation.v1",
        "from": "raint-a.test.aint",
        "to": "raint-b.test.aint",
        "lane_id": "lane-sync-1",
        "surfaces": ["handshake.aint", "audit.aint"],
        "intents": ["probe", "read-audit"],
        "nonce": "relation-1",
        "issued_at": now,
        "expires_at": now + 60,
        "signers": pubkeys,
    }
    relation["signatures"] = {
        "raint-a.test.aint": sign_canonical(relation, a, excluded=("signatures",))["sig"],
        "raint-b.test.aint": sign_canonical(relation, b, excluded=("signatures",))["sig"],
    }
    assert verify_relation(relation, pubkeys, now=now).ok

    tampered = dict(relation)
    tampered["surfaces"] = ["capture.this"]
    assert not verify_relation(tampered, pubkeys, now=now).ok
