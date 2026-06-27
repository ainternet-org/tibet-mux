"""Causal re-attestation chain — trust is a sequence, not a duration.

Design: gravity.aint (causal-reattestation-chain-v0). Build: root_idd.

Wall-clock is distrusted (a P520 drifted 2h). So leases and re-attestation are
defined purely by CAUSAL ticks (causal_seq distance) and causal EVENTS, never a
TTL clock. Each re-attestation is a `CausalChainLink` hash-chained to the prior
one (prev_receipt_hash), so the chain proves its own continuity without ever
reading a clock.

The self-blocker (gravity): the next onion payload key is derived from the
current valid link — K = HKDF(tpm_secret, prev_receipt_hash || causal_seq).
Skip or fail attestation and you simply cannot compute the key; the payload is
undecryptable noise (chaff). Fail-closed by math, no firewall in the hot path.

    Trust is not a duration. Trust is a logical sequence of proven causal steps.

Canonical form (the seam this module owns): compact JSON, sorted keys. Signing
bytes exclude the `signature` field; the link hash covers the whole committed
link. Conformance vectors align to this. Pure stdlib; signature verification is
pluggable (pass the family Ed25519 verifier). One love, one fAmIly.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Callable, Dict, List, Optional

from . import carrier_policy as cp
from . import route_posture as rp

LINK_KIND = "org.ainternet.mux.causal_chain_link.v1"
GENESIS_PREV = "sha256:" + "0" * 64

# --- Trigger policy: causal-distance thresholds per band (gravity's table) ----
DELTA_C: Dict[str, int] = {
    "P0": 0,
    "P1": 5000,   # triage / human — rarely re-attests
    "P2": 500,
    "P3": 500,
    "P4": 100,    # hot-path — re-attests often under activity
    "P5": 100,
}

#: The four causal re-attestation triggers (gravity).
TRIGGERS = (
    "causal_distance_exceeded",
    "posture_transition",
    "phoenix_reset",
    "control_plane_revocation",
)


def delta_c_for_band(band: str) -> int:
    return DELTA_C.get(band, 500)


def needs_reattestation(*, current_seq: int, expires_seq: int,
                        posture_changed: bool = False, phoenix_reset: bool = False,
                        revoked: bool = False) -> List[str]:
    """Return the list of fired triggers. Empty list = chain still valid.
    Note: idle phases advance no causal_seq, so keys don't expire needlessly."""
    fired = []
    if current_seq > expires_seq:
        fired.append("causal_distance_exceeded")
    if posture_changed:
        fired.append("posture_transition")
    if phoenix_reset:
        fired.append("phoenix_reset")
    if revoked:
        fired.append("control_plane_revocation")
    return fired


# --- Canonical / hashing (the seam this module owns) -------------------------
def _canonical(link: Dict, *, exclude: tuple = ()) -> bytes:
    d = {k: v for k, v in link.items() if k not in exclude}
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def signing_bytes(link: Dict) -> bytes:
    """Bytes an actor signs: the link minus the signature field."""
    return _canonical(link, exclude=("signature",))


def link_hash(link: Dict) -> str:
    """SHA256 of the whole committed link (gravity: hash of the previous link)."""
    return "sha256:" + hashlib.sha256(_canonical(link)).hexdigest()


def build_link(*, actor: str, actor_class: str, causal_seq: int,
               posture_observed: str, relation_hash: str, jis_proof: Dict,
               prev_link: Optional[Dict] = None, band: Optional[str] = None,
               sign: Optional[Callable[[bytes], str]] = None) -> Dict:
    """Build a CausalChainLink. expires_seq = causal_seq + ΔC(band). Chains to
    prev_link via its hash (genesis if none). `sign` signs `signing_bytes`."""
    if band is None:
        band = cp.posture_band(rp.decode_posture(posture_observed))
    dc = delta_c_for_band(band)
    prev_hash = link_hash(prev_link) if prev_link is not None else GENESIS_PREV
    link = {
        "kind": LINK_KIND,
        "actor": actor,
        "actor_class": actor_class,
        "causal_seq": causal_seq,
        "expires_seq": causal_seq + dc,
        "prev_receipt_hash": prev_hash,
        "relation_hash": relation_hash,
        "posture_observed": posture_observed,
        "jis_proof": jis_proof,
    }
    link["signature"] = sign(signing_bytes(link)) if sign else "ed25519:UNSIGNED"
    return link


# --- verify_chain: three-stage validation (gravity) --------------------------
def verify_chain(links: List[Dict], *, current_seq: int,
                 verify_sig: Optional[Callable[[Dict], bool]] = None) -> Dict:
    """Three checks: (1) crypto, (2) causal continuity, (3) expiry.
    Any failure -> route blocked, posture DARK (#00000). Returns a verdict dict."""
    def fail(reason: str, idx: Optional[int] = None) -> Dict:
        return {"ok": False, "posture": rp.DARK, "reason": reason, "failed_index": idx}

    if not links:
        return fail("empty chain")

    for i, link in enumerate(links):
        # Check 1: cryptographic integrity (pluggable — pass the family verifier)
        if verify_sig is not None and not verify_sig(link):
            return fail("bad signature / jis_proof", i)
        # Check 2: causal continuity
        if i > 0:
            if link.get("prev_receipt_hash") != link_hash(links[i - 1]):
                return fail("broken chain: prev_receipt_hash mismatch", i)
            if link["causal_seq"] <= links[i - 1]["causal_seq"]:
                return fail("causal_seq not monotonically increasing", i)

    # Check 3: expiry — the HEAD link must still be causally current.
    last = links[-1]
    if current_seq > last["expires_seq"]:
        return fail(
            f"stale: current_seq {current_seq} > expires_seq {last['expires_seq']} "
            f"-> re-attest or DARK")
    return {"ok": True, "posture": last["posture_observed"],
            "reason": "chain valid (crypto + causal continuity + expiry)",
            "head_seq": last["causal_seq"], "expires_seq": last["expires_seq"]}


# --- Key derivation chain: the self-blocker (gravity) ------------------------
def _hkdf_sha256(ikm: bytes, info: bytes, length: int = 32, salt: bytes = b"") -> bytes:
    """RFC 5869 HKDF-SHA256 (extract + expand), pure stdlib."""
    if not salt:
        salt = b"\x00" * hashlib.sha256().digest_size
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm, t, counter = b"", b"", 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def derive_payload_key(tpm_secret: bytes, prev_receipt_hash: str, causal_seq: int,
                       length: int = 32) -> bytes:
    """K_payload = HKDF(tpm_secret, prev_receipt_hash || causal_seq).

    Skip a step or fail attestation -> a different (prev_receipt_hash, causal_seq)
    -> a different key -> the payload decrypts to noise. Fail-closed by math.
    """
    info = (prev_receipt_hash + "|" + str(causal_seq)).encode("utf-8")
    return _hkdf_sha256(tpm_secret, info, length)


def derive_next_key(tpm_secret: bytes, valid_head_link: Dict, length: int = 32) -> bytes:
    """Convenience: derive the next onion-layer key from a verified head link."""
    return derive_payload_key(tpm_secret, valid_head_link["prev_receipt_hash"],
                              valid_head_link["causal_seq"], length)
