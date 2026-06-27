"""Conformance for tibet-mux v1.1.1 — .caint (composite actor) + forward-consent fast-path.

.caint = verify_relation + capability-INTERSECTION (derived, never expansive).
forward-consent = predecessor-signed expected-successor, slot bound to next_pubkey (anti-MITM).

    python3 -m pytest packages/tibet-mux/tests/test_caint.py
"""

import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tibet_mux.verify import (
    caint_capability,
    caint_manifest_handle,
    sign_canonical,
    verify_caint,
    verify_forward_consent,
)


def _pub_hex(priv):
    return priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def test_capability_is_set_intersection_never_expansion():
    assert caint_capability([["a", "b", "c"], ["b", "c", "d"]]) == ["b", "c"]
    assert caint_capability([["a"], ["b"]]) == []
    assert caint_capability([]) == []


def _signed_caint(caps_a, caps_b, declared, now, expires_delta=60):
    a = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    b = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    pubkeys = {"gpu0.p520.waint": _pub_hex(a), "gpu1.p520.waint": _pub_hex(b)}
    manifest = {
        "kind": "org.ainternet.caint.v1",
        "caint": "p520-gpu-pair.caint",
        "members": {
            "gpu0.p520.waint": {"pub": _pub_hex(a), "caps": caps_a},
            "gpu1.p520.waint": {"pub": _pub_hex(b), "caps": caps_b},
        },
        "capabilities": declared,
        "lane": "gpu-pair-1",
        "epoch": 7,
        "issued_at": now,
        "expires_at": now + expires_delta,
    }
    manifest["signatures"] = {
        "gpu0.p520.waint": sign_canonical(manifest, a, excluded=("signatures",))["sig"],
        "gpu1.p520.waint": sign_canonical(manifest, b, excluded=("signatures",))["sig"],
    }
    return manifest, pubkeys


def test_caint_materializes_on_full_proof_and_subset_caps():
    now = int(time.time())
    m, pk = _signed_caint(["copy", "infer", "evict"], ["copy", "infer"], ["copy", "infer"], now)
    assert verify_caint(m, pk, now=now).ok


def test_caint_rejects_capability_expansion():
    now = int(time.time())
    # declared "evict" is NOT in the intersection (gpu1 lacks it) -> expansion -> reject
    m, pk = _signed_caint(["copy", "infer", "evict"], ["copy", "infer"], ["copy", "evict"], now)
    d = verify_caint(m, pk, now=now)
    assert not d.ok and d.reason == "capability-expansion"


def test_caint_rejects_missing_member_signature():
    now = int(time.time())
    m, pk = _signed_caint(["copy"], ["copy"], ["copy"], now)
    tampered = dict(m, capabilities=["copy"])
    tampered["signatures"] = dict(m["signatures"])
    tampered["signatures"]["gpu1.p520.waint"] = "ed25519:" + "00" * 64  # forged
    assert not verify_caint(tampered, pk, now=now).ok


def test_caint_rejects_expired():
    now = int(time.time())
    m, pk = _signed_caint(["copy"], ["copy"], ["copy"], now, expires_delta=-1)
    assert not verify_caint(m, pk, now=now).ok


def test_manifest_handle_deterministic_and_lane_epoch_sensitive():
    now = int(time.time())
    m, _ = _signed_caint(["copy"], ["copy"], ["copy"], now)
    h1 = caint_manifest_handle(m, lane="L", epoch=1)
    h2 = caint_manifest_handle(m, lane="L", epoch=1)
    h3 = caint_manifest_handle(m, lane="L", epoch=2)
    assert h1 == h2 and h1 != h3 and len(h1) == 32  # 16 bytes hex, epoch rolls the handle


def _forward_edge(pred, succ_pub, succ_aint, now, expires_delta=30):
    edge = {
        "kind": "org.ainternet.forward-consent.v1",
        "next_aint": succ_aint,
        "next_pubkey": succ_pub,
        "lane": "gpu-pair-1",
        "epoch": 7,
        "nonce": "fc-1",
        "expires_at": now + expires_delta,
    }
    return sign_canonical(edge, pred, excluded=("sig",))


def test_forward_consent_fast_opens_for_named_successor():
    now = int(time.time())
    pred = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    succ = Ed25519PrivateKey.from_private_bytes(bytes(range(64, 96)))
    succ_pub = _pub_hex(succ)
    edge = _forward_edge(pred, succ_pub, "gpu1.p520.waint", now)
    ch = f"nonce:{now}"
    sig = succ.sign(ch.encode()).hex()
    d = verify_forward_consent(edge, succ_pub, ch, sig, _pub_hex(pred), now=now)
    assert d.ok and d.verified_actor == "gpu1.p520.waint"


def test_forward_consent_blocks_mitm_wrong_pubkey():
    now = int(time.time())
    pred = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    succ = Ed25519PrivateKey.from_private_bytes(bytes(range(64, 96)))
    mitm = Ed25519PrivateKey.from_private_bytes(bytes(range(96, 128)))
    edge = _forward_edge(pred, _pub_hex(succ), "gpu1.p520.waint", now)
    ch = f"nonce:{now}"
    # MITM presents its OWN key + a valid self-signature, but the slot is bound to succ's pubkey
    d = verify_forward_consent(edge, _pub_hex(mitm), ch, mitm.sign(ch.encode()).hex(),
                               _pub_hex(pred), now=now)
    assert not d.ok and d.reason == "successor-pubkey-mismatch"


def test_forward_consent_rejects_forged_predecessor_and_expiry():
    now = int(time.time())
    pred = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    succ = Ed25519PrivateKey.from_private_bytes(bytes(range(64, 96)))
    other = Ed25519PrivateKey.from_private_bytes(bytes(range(128, 160)))
    succ_pub = _pub_hex(succ)
    ch = f"nonce:{now}"
    sig = succ.sign(ch.encode()).hex()
    # forged predecessor: edge signed by `other`, verified against pred's pubkey -> fail
    edge = _forward_edge(other, succ_pub, "gpu1.p520.waint", now)
    assert not verify_forward_consent(edge, succ_pub, ch, sig, _pub_hex(pred), now=now).ok
    # expired edge
    expired = _forward_edge(pred, succ_pub, "gpu1.p520.waint", now, expires_delta=-1)
    assert not verify_forward_consent(expired, succ_pub, ch, sig, _pub_hex(pred), now=now).ok
