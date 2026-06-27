#!/usr/bin/env python3
"""tibet-mux v1.1.0 — one verifier family (the #109 contract, lifted).

Promoted verbatim from Codex' three-way-accepted contract reference (no byte-drift:
the sandbox reference + enclave mux-frame-vectors.json remain the conformance fixtures).

Two signing modes, one family:
  - verify_actor_challenge / verify_ipoll_headers — Ed25519 over the RAW challenge string
    (RABEL / Brain-API JIS headers: X-Agent-ID/X-Challenge/X-Signature).
  - verify_canonical / verify_mux_frame / verify_relation / verify_arena_probe — Ed25519 over
    canonical_without(obj) (Redstone MUX / relation / arena / runtime receipts).

Shared: canonical bytes, key/sig decode, actor normalization, freshness, VerifyDecision shape.
Design & authorship: Codex (contract) + Root AI (lift). Part of the TIBET ecosystem.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

US = "\x1f"
ED25519_PREFIX = "ed25519:"


@dataclass(frozen=True)
class VerifyDecision:
    ok: bool
    reason: str
    actor: str | None = None
    signed: bool = False
    verified_actor: str | None = None


def canonical_without(value: dict[str, Any], excluded: tuple[str, ...] = ("sig",)) -> bytes:
    """Pinned canonical bytes: US-joined sorted keys, compact JSON values."""
    excluded_set = set(excluded)
    return US.join(
        "%s=%s" % (
            key,
            json.dumps(value[key], separators=(",", ":"), sort_keys=True, ensure_ascii=False),
        )
        for key in sorted(value)
        if key not in excluded_set
    ).encode("utf-8")


def _decode_material(value: str) -> bytes | None:
    if not isinstance(value, str) or not value:
        return None
    value = value.strip()
    if value.startswith(ED25519_PREFIX):
        value = value.split(":", 1)[1]
    if len(value) in (64, 128) and all(c in "0123456789abcdefABCDEF" for c in value):
        try:
            return bytes.fromhex(value)
        except ValueError:
            return None
    try:
        return base64.b64decode(value, validate=False)
    except Exception:
        return None


def _is_fresh_challenge(challenge: str, now: float | None = None, window_sec: int = 120) -> bool:
    if not challenge:
        return False
    now = time.time() if now is None else now
    for sep in ("|", ":"):
        if sep in challenge:
            tail = challenge.rsplit(sep, 1)[1].strip()
            try:
                ts = float(tail)
            except ValueError:
                continue
            return abs(now - ts) <= window_sec
    return False


def verify_bytes(message: bytes, signature: str, public_key: str) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        return False
    sig = _decode_material(signature)
    pub = _decode_material(public_key)
    if sig is None or pub is None or len(sig) != 64 or len(pub) != 32:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, message)
        return True
    except Exception:
        return False


def sign_canonical(value: dict[str, Any], private_key, excluded: tuple[str, ...] = ("sig",),
                   sig_field: str = "sig") -> dict[str, Any]:
    signed = {key: val for key, val in value.items() if key != sig_field}
    signed[sig_field] = ED25519_PREFIX + private_key.sign(canonical_without(signed, excluded)).hex()
    return signed


def verify_canonical(value: dict[str, Any], public_key: str, sig: str | None = None,
                     excluded: tuple[str, ...] = ("sig",), sig_field: str = "sig") -> bool:
    signature = sig if sig is not None else value.get(sig_field, "")
    return verify_bytes(canonical_without(value, excluded), signature, public_key)


def verify_actor_challenge(agent_id: str, challenge: str, signature: str, public_key: str,
                           now: float | None = None, window_sec: int = 120) -> VerifyDecision:
    """Verify RABEL/Brain API JIS headers: Ed25519 over the raw challenge string."""
    if not agent_id:
        return VerifyDecision(False, "missing-actor")
    if not _is_fresh_challenge(challenge, now=now, window_sec=window_sec):
        return VerifyDecision(False, "stale-challenge", actor=agent_id)
    if not verify_bytes(challenge.encode("utf-8"), signature, public_key):
        return VerifyDecision(False, "bad-signature", actor=agent_id)
    return VerifyDecision(True, "verified-actor-challenge", actor=agent_id,
                          signed=True, verified_actor=agent_id)


def verify_ipoll_headers(headers: dict[str, str], resolve_pubkey: Callable[[str], str | None],
                         from_agent: str | None = None, now: float | None = None) -> VerifyDecision:
    """Verify X-Agent-ID/X-Challenge/X-Signature without trusting the message body."""
    agent_id = headers.get("X-Agent-ID") or headers.get("x-agent-id")
    challenge = headers.get("X-Challenge") or headers.get("x-challenge")
    signature = headers.get("X-Signature") or headers.get("x-signature")
    if not (agent_id and challenge and signature):
        return VerifyDecision(False, "unsigned", actor=from_agent)
    if from_agent and _normalize_aint(agent_id) != _normalize_aint(from_agent):
        return VerifyDecision(False, "agent-mismatch", actor=from_agent)
    public_key = resolve_pubkey(_normalize_aint(agent_id))
    if not public_key:
        return VerifyDecision(False, "unknown-actor", actor=_normalize_aint(agent_id))
    return verify_actor_challenge(_normalize_aint(agent_id), challenge, signature, public_key, now=now)


def verify_mux_frame(frame: dict[str, Any], public_key: str, now: float | None = None,
                     skew_sec: int = 120) -> VerifyDecision:
    if frame.get("v") != "org.ainternet.mux.frame.v1":
        return VerifyDecision(False, "wrong-frame-version", actor=frame.get("from_aint"))
    ts = frame.get("ts")
    if not isinstance(ts, int):
        return VerifyDecision(False, "missing-ts", actor=frame.get("from_aint"))
    now = time.time() if now is None else now
    if abs(now - ts) > skew_sec:
        return VerifyDecision(False, "stale-frame", actor=frame.get("from_aint"))
    if not verify_canonical(frame, public_key, excluded=("sig",)):
        return VerifyDecision(False, "bad-signature", actor=frame.get("from_aint"))
    return VerifyDecision(True, "verified-mux-frame", actor=frame.get("from_aint"),
                          signed=True, verified_actor=frame.get("from_aint"))


def verify_relation(relation: dict[str, Any], pubkeys: dict[str, str],
                    now: float | None = None) -> VerifyDecision:
    if relation.get("kind") != "org.ainternet.redstone.relation.v1":
        return VerifyDecision(False, "wrong-relation-kind")
    now = time.time() if now is None else now
    if int(relation.get("issued_at", relation.get("ts", 0))) > now + 30:
        return VerifyDecision(False, "issued-in-future")
    if int(relation.get("expires_at", now - 1)) < now:
        return VerifyDecision(False, "relation-expired")
    signers = relation.get("signers", {})
    signatures = relation.get("signatures", {})
    if not isinstance(signers, dict) or not isinstance(signatures, dict) or not signers:
        return VerifyDecision(False, "missing-signers")
    for actor, pub in signers.items():
        expected_pub = pubkeys.get(actor, pub)
        if not expected_pub:
            return VerifyDecision(False, "unknown-signer", actor=actor)
        if not verify_canonical(relation, expected_pub, signatures.get(actor), excluded=("signatures",)):
            return VerifyDecision(False, "bad-relation-signature", actor=actor)
    return VerifyDecision(True, "verified-relation", signed=True)


def verify_arena_probe(frame: dict[str, Any], public_key: str, now: float | None = None) -> VerifyDecision:
    """Arena probe is a MUX frame plus arena-specific surface/op policy outside this primitive."""
    decision = verify_mux_frame(frame, public_key, now=now)
    if not decision.ok:
        return decision
    if not frame.get("surface"):
        return VerifyDecision(False, "missing-surface", actor=frame.get("from_aint"))
    return VerifyDecision(True, "verified-arena-probe", actor=frame.get("from_aint"),
                          signed=True, verified_actor=frame.get("from_aint"))


def _normalize_aint(value: str) -> str:
    return value if value.endswith(".aint") else value + ".aint"


# ----------------------------------------------------------------------------
# v1.1.1 — .caint (composite/derived actor) + forward-consent fast-path
# ----------------------------------------------------------------------------
# A .caint is DERIVED, never expansive: its capability is the set-INTERSECTION of
# its member .waints, and it materializes only if every member signed the manifest
# (N-of-N). No key inheritance, no authority expansion. This is verify_relation +
# capability-intersection — not new crypto, the same canonical_without seam.

def caint_capability(member_caps: list) -> list:
    """Composite capability = set-INTERSECTION of member caps (never a superset)."""
    if not member_caps:
        return []
    inter = set(member_caps[0])
    for caps in member_caps[1:]:
        inter &= set(caps)
    return sorted(inter)


def _without_keys(value: dict, keys: set) -> dict:
    return {k: v for k, v in value.items() if k not in keys}


def caint_parent_anchor(manifest: dict, relation: dict, consent_window: dict) -> dict:
    """Cold-path anchor binding manifest + relation + consent-window.

    Nested manifest/relation are stripped of their own signature fields before the OUTER object
    is canonicalized — the hash is tied to the same semantic bytes the relation verifier signs,
    without inventing a second serializer.
    """
    return {
        "kind": "org.ainternet.caint.parent-anchor.v1",
        "caint": manifest.get("caint"),
        "controller": manifest.get("controller"),
        "members": sorted(manifest.get("members", [])),
        "manifest": _without_keys(manifest, {"sig"}),
        "relation": _without_keys(relation, {"signatures"}),
        "consent_window": consent_window,
    }


def caint_parent_hash(manifest: dict, relation: dict, consent_window: dict) -> str:
    """`sha256:` over canonical(parent-anchor). The cold-path content-address of a composite."""
    anchor = caint_parent_anchor(manifest, relation, consent_window)
    return "sha256:" + hashlib.sha256(canonical_without(anchor, excluded=())).hexdigest()


def caint_manifest_handle(manifest: dict, relation: dict, consent_window: dict,
                          *, epoch=None, lane=None) -> str:
    """Hot-path parent handle. Without epoch/lane = first16(parent_hash); with them = a keyed
    short handle over parent_hash + runtime context. The handle says "expected"; the runtime
    table decides "known" — an unknown/stale handle routes to dark/triage.
    """
    parent_hash = caint_parent_hash(manifest, relation, consent_window)
    if epoch is None and lane is None:
        return parent_hash.split(":", 1)[1][:32]
    material = "|".join([parent_hash, str(epoch or ""), lane or ""]).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


def verify_caint(manifest: dict, pubkeys: dict, now: float | None = None) -> VerifyDecision:
    """Composite-actor gate. Materializes iff:
      1. every member signed the manifest (N-of-N), within issue/expiry window
      2. declared capability ⊆ set-intersection of member caps (no expansion)
    manifest = {kind: org.ainternet.caint.v1, caint, members:{aint:{pub,caps}}, capabilities:[...],
                issued_at, expires_at, signatures:{aint:sig}}. Else -> not ok (caller darks/triages).
    """
    if manifest.get("kind") != "org.ainternet.caint.v1":
        return VerifyDecision(False, "wrong-caint-kind", actor=manifest.get("caint"))
    now = time.time() if now is None else now
    if int(manifest.get("issued_at", manifest.get("ts", 0))) > now + 30:
        return VerifyDecision(False, "issued-in-future", actor=manifest.get("caint"))
    if int(manifest.get("expires_at", now - 1)) < now:
        return VerifyDecision(False, "caint-expired", actor=manifest.get("caint"))
    members = manifest.get("members", {})
    signatures = manifest.get("signatures", {})
    if not isinstance(members, dict) or not members or not isinstance(signatures, dict):
        return VerifyDecision(False, "missing-members", actor=manifest.get("caint"))
    member_caps = []
    for aint, info in members.items():
        pub = pubkeys.get(aint, (info or {}).get("pub"))
        if not pub:
            return VerifyDecision(False, "unknown-member", actor=aint)
        if not verify_canonical(manifest, pub, signatures.get(aint), excluded=("signatures",)):
            return VerifyDecision(False, "bad-member-signature", actor=aint)
        member_caps.append((info or {}).get("caps", []))
    allowed = set(caint_capability(member_caps))
    declared = set(manifest.get("capabilities", []))
    if not declared <= allowed:
        return VerifyDecision(False, "capability-expansion", actor=manifest.get("caint"))
    return VerifyDecision(True, "verified-caint", actor=manifest.get("caint"),
                          signed=True, verified_actor=manifest.get("caint"))


def verify_forward_consent(edge: dict, presenter_pubkey: str, presenter_challenge: str,
                           presenter_signature: str, predecessor_pubkey: str,
                           now: float | None = None) -> VerifyDecision:
    """Expected-successor fast-path: consent pre-positioned by a verified predecessor.

    The predecessor SIGNED a forward-edge naming the successor (next_aint + next_pubkey + lane +
    epoch + expires_at). The presenter must BE that successor: same pubkey (anti-MITM, the slot is
    bound to a key an interposer lacks) AND a fresh signature (it's really you, now). The handle
    says "expected"; the signature says "it's you" — never skip the second.
    edge = {kind: org.ainternet.forward-consent.v1, next_aint, next_pubkey, lane, epoch,
            expires_at, nonce, sig}.
    """
    if edge.get("kind") != "org.ainternet.forward-consent.v1":
        return VerifyDecision(False, "wrong-edge-kind")
    now = time.time() if now is None else now
    if int(edge.get("expires_at", now - 1)) < now:
        return VerifyDecision(False, "forward-edge-expired", actor=edge.get("next_aint"))
    if not verify_canonical(edge, predecessor_pubkey, excluded=("sig",)):
        return VerifyDecision(False, "bad-predecessor-signature", actor=edge.get("next_aint"))
    if edge.get("next_pubkey") != presenter_pubkey:
        return VerifyDecision(False, "successor-pubkey-mismatch", actor=edge.get("next_aint"))
    succ = verify_actor_challenge(edge.get("next_aint", ""), presenter_challenge,
                                  presenter_signature, presenter_pubkey, now=now)
    if not succ.ok:
        return VerifyDecision(False, "successor-%s" % succ.reason, actor=edge.get("next_aint"))
    return VerifyDecision(True, "verified-forward-consent", actor=edge.get("next_aint"),
                          signed=True, verified_actor=edge.get("next_aint"))


def vector_check(path: str) -> dict[str, Any]:
    """Conformance runner against an enclave mux-frame-vectors.json fixture."""
    data = json.load(open(path))
    signers = data.get("signers", {})
    results = []
    for vector in data.get("vectors", []):
        frame = vector["frame"]
        pub = signers.get(frame.get("from_aint"))
        canonical_hex = canonical_without(frame, ("sig",)).hex()
        # Fixture timestamps are historic. For conformance, pin now to ts.
        decision = verify_mux_frame(frame, pub, now=frame.get("ts", 0)) if pub else VerifyDecision(False, "missing-pubkey")
        results.append({
            "name": vector.get("name"),
            "canonical": "ok" if canonical_hex == vector.get("canonical_hex") else "mismatch",
            "signature": "ok" if decision.ok else decision.reason,
        })
    return {"kind": "org.ainternet.tibet-mux.contract-reference.vector-check.v1", "results": results}


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m tibet_mux.verify /path/to/mux-frame-vectors.json")
    print(json.dumps(vector_check(sys.argv[1]), indent=2, sort_keys=True))
