"""Route-posture carrier policy — the upper grammar (tibet-mux, 27 Jun 2026).

Design: codex.aint (route-posture-carrier-policy-grammar-v0). Build: root_idd.

`#RCTAM` is the small grammar: it PROVES the posture. This module is the upper
grammar: given route posture + intent + payload class, it CHOOSES the carrier,
lane behavior, fallback and receipt fields. It does NOT add to the five digits —
it READS them.

    The route number proves posture; orchestration chooses the carrier.

Posture bands (P0..P5) are policy bands, not new digits — derived from the
existing #RCTAM via `posture_band()`. Lane skipping is allowed ONLY with a
receipt (no receipt, no skip). This policy does not rate actors; it routes by
posture. One love, one fAmIly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import route_posture as rp

# --- Carrier + payload vocab (codex's names, verbatim) -----------------------
CARRIERS = (
    "dark_route", "ipoll.message", "cmail.capsule", "cap_bus.event",
    "continuityd.arrival", "phantom.resume", "phantom.diff_merge",
    "upip.instruction", "redstone.raint_lane", "gpu_mailbox_capsule",
    "direct_local_lane",
)
PAYLOAD_CLASSES = (
    "control", "message", "capsule", "session_snapshot", "session_diff",
    "process_instruction", "hot_transfer", "evidence",
)

# --- Posture bands (policy bands, NOT new digits) ----------------------------
BAND_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}
# Walk weaker bands when a (band,payload) row is absent: a stronger posture
# inherits everything a weaker one may do.
_WEAKER = ["P5", "P4", "P3", "P2", "P1"]


def posture_band(f: rp.PostureFields) -> str:
    """Map #RCTAM onto a policy band (codex's band table). Strongest match wins;
    P0 is the hard floor."""
    f.validate()
    M, C, A, T = f.mux_posture, f.consent_class, f.audit_mode, f.timing_lane
    if M == 0 or C == 0:
        return "P0"
    if A == 7 and M == 9 and C >= 4:
        return "P5"
    if A >= 5 and T >= 3 and M in (8, 9) and C >= 4:
        return "P4"
    if A >= 4 and M in (8, 9) and C >= 3:
        return "P3"
    if A in (2, 3) and M in (8, 9) and C >= 2:
        return "P2"
    return "P1"  # M in 1..7 / stale / exception / doesn't meet observed bar


# --- Carrier matrix (band, payload) -> (carrier, lane_skip_eligible, fallback)
# Transcribed from codex's table.
MATRIX: Dict[Tuple[str, str], Tuple[str, bool, str]] = {
    ("P1", "control"): ("ipoll.message", False, "dark_route"),
    ("P1", "evidence"): ("cmail.capsule", False, "dark_route"),
    ("P2", "message"): ("ipoll.message", False, "cmail.capsule"),
    ("P2", "capsule"): ("cmail.capsule", False, "triage"),
    ("P2", "session_snapshot"): ("cmail.capsule", False, "phantom.diff_merge"),
    ("P2", "hot_transfer"): ("cmail.capsule", False, "triage"),  # request only, no hot path
    ("P3", "control"): ("cap_bus.event", True, "ipoll.message"),
    ("P3", "process_instruction"): ("upip.instruction", True, "triage"),
    ("P3", "session_diff"): ("phantom.diff_merge", True, "cmail.capsule"),
    ("P3", "hot_transfer"): ("gpu_mailbox_capsule", True, "cap_bus.event"),
    ("P4", "control"): ("cap_bus.event", True, "ipoll.message"),
    ("P4", "process_instruction"): ("upip.instruction", True, "triage"),
    ("P4", "session_diff"): ("phantom.diff_merge", True, "phantom.resume"),
    ("P4", "hot_transfer"): ("gpu_mailbox_capsule", True, "dark_route"),
    ("P5", "evidence"): ("continuityd.arrival", False, "report"),
    ("P5", "session_snapshot"): ("phantom.resume", True, "phantom.diff_merge"),
}

# Multi-track collapse per band (codex's track rule).
_TRACKS: Dict[str, Tuple[List[str], List[str]]] = {
    "P0": ([], ["control", "data", "evidence", "resume", "human", "hot_path"]),
    "P1": (["human", "evidence"], ["control", "data", "resume", "hot_path"]),
    "P2": (["control", "evidence"], ["data", "resume", "hot_path", "human"]),
    "P3": (["control", "resume", "data"], ["hot_path"]),
    "P4": (["control", "hot_path", "resume"], []),
    "P5": (["control", "data", "evidence", "resume", "human", "hot_path"], []),
}


def lane_skip_allowed(f: rp.PostureFields, *, has_receipt: bool,
                      causal_current: bool = True, relation_active: bool = True,
                      manifest_matches: bool = True) -> bool:
    """Codex's lane-skip rule. No receipt -> no skip, full stop."""
    return (
        f.mux_posture in (8, 9)
        and f.consent_class >= 4
        and f.audit_mode >= 4
        and has_receipt
        and causal_current
        and relation_active
        and manifest_matches
    )


def posture_satisfies(observed: str, required: str) -> bool:
    """Does the observed posture satisfy a required one? (manifest rule)
    Band must be at least as strong, and audit/consent/mux at least as high."""
    o, r = rp.decode_posture(observed), rp.decode_posture(required)
    return (
        BAND_RANK[posture_band(o)] >= BAND_RANK[posture_band(r)]
        and o.audit_mode >= r.audit_mode
        and o.consent_class >= r.consent_class
        and o.mux_posture >= r.mux_posture
    )


def _matrix_lookup(band: str, payload: str) -> Optional[Tuple[str, bool, str]]:
    """Find the row for (band,payload), inheriting from weaker bands if absent."""
    if band not in BAND_RANK or band == "P0":
        return None
    start = _WEAKER.index(band) if band in _WEAKER else 0
    for b in _WEAKER[start:]:
        row = MATRIX.get((b, payload))
        if row is not None:
            return row
    return None


@dataclass
class CarrierDecision:
    decision: str          # allow | hold | triage | dark
    carrier: str
    route_posture: str
    band: str
    lane_skipping: bool
    tracks_opened: List[str]
    tracks_held: List[str]
    fallback: Optional[str]
    causal_seq: int
    receipt_required: bool
    reason: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "kind": "org.ainternet.mux.carrier_policy.decision.v1",
            "decision": self.decision,
            "carrier": self.carrier,
            "route_posture": self.route_posture,
            "band": self.band,
            "lane_skipping": self.lane_skipping,
            "tracks_opened": self.tracks_opened,
            "tracks_held": self.tracks_held,
            "fallback": self.fallback,
            "causal_seq": self.causal_seq,
            "receipt_required": self.receipt_required,
            "reason": self.reason,
        }


POSTURE_CARD_KIND = "org.ainternet.mux.posture_card.v1"


def posture_card(actor: str, route_posture: str, *,
                 session_proven: frozenset = frozenset()) -> Dict[str, object]:
    """A human/audit posture card for an actor on a route (Richard demo display).

    HONEST by construction (codex's rule: do not claim T3/A5 unless the session
    lane proves it). Capabilities the digits *imply* but that the session has not
    demonstrated are listed in `held`, not asserted. `session_proven` is the set
    of axes actually measured this session, e.g. {"cadence", "sign_ahead"}.
    Display/audit only — grants no authority.
    """
    f = rp.decode_posture(route_posture)
    perm = rp.lane_permissions(f)
    band = posture_band(f)
    held: List[str] = []
    if perm["hot_path"] and not perm["cadence_locked"]:
        held.append("hot_path: cadence not locked (timing lane below CBR-spin)")
    if f.timing_lane >= 3 and "cadence" not in session_proven:
        held.append("T>=3 (cadence) is claimed by posture but NOT session-proven")
    if f.audit_mode >= 5 and "sign_ahead" not in session_proven:
        held.append("A5 sign-ahead is claimed by posture but NOT session-proven")
    hot_path_active = (perm["hot_path"] and perm["cadence_locked"]
                       and not any("session-proven" in h for h in held))
    return {
        "kind": POSTURE_CARD_KIND,
        "actor": actor,
        "route_posture": route_posture,
        "band": band,
        "axes": rp.explain(route_posture),
        "permissions": perm,
        "hot_path_active": hot_path_active,
        "held": held,
        "session_proven": sorted(session_proven),
    }


def render_card(card: Dict[str, object]) -> str:
    """The CLI/audit print for `redstone posture` / after-richard-start."""
    a = card["axes"]
    lines = [
        f"{card['actor']}  {card['route_posture']}  [{card['band']}]",
        f"  route family : {a['route_family']}",
        f"  consent      : {a['consent_class']}",
        f"  timing lane  : {a['timing_lane']}",
        f"  audit        : {a['audit_mode']}",
        f"  mux posture  : {a['mux_posture']}",
        f"  hot_path     : {'ACTIVE' if card['hot_path_active'] else 'HELD'}",
    ]
    for h in card["held"]:
        lines.append(f"  held         : {h}")
    return "\n".join(lines)


def choose_carrier(route_posture: str, payload_class: str, *,
                   causal_seq: int = 0, has_receipt: bool = False,
                   causal_current: bool = True, relation_active: bool = True,
                   manifest_matches: bool = True,
                   required_posture: Optional[str] = None,
                   slot_valid: Optional[bool] = None) -> CarrierDecision:
    """Read the posture, choose the carrier. Never extends #RCTAM."""
    if payload_class not in PAYLOAD_CLASSES:
        raise ValueError(f"unknown payload_class {payload_class!r}")
    f = rp.decode_posture(route_posture)
    band = posture_band(f)
    opened, held = _TRACKS[band]

    def mk(decision, carrier, lane_skipping, fallback, reason):
        return CarrierDecision(decision, carrier, route_posture, band, lane_skipping,
                               opened, held, fallback, causal_seq,
                               receipt_required=lane_skipping or band in ("P4", "P5"),
                               reason=reason)

    # P0 / dark — no carrier opens.
    if band == "P0":
        return mk("dark", "dark_route", False, None, "no valid posture (dark route)")

    # UPIP slot rule: a presented-but-missed slot -> triage; dark posture -> dark.
    if slot_valid is False:
        return mk("triage", "ipoll.message", False, "dark_route",
                  "UPIP slot missed -> triage_or_dark")

    # Capsule manifest rule: observed below required -> hold as capsule.
    if required_posture is not None and not posture_satisfies(route_posture, required_posture):
        return mk("hold", "cmail.capsule", False, "triage",
                  f"observed {route_posture} below required {required_posture} -> held as capsule")

    row = _matrix_lookup(band, payload_class)
    if row is None:
        return mk("triage", "cmail.capsule", False, "dark_route",
                  f"no carrier row for {band}/{payload_class} -> triage")
    carrier, skip_eligible, fallback = row
    skipping = skip_eligible and lane_skip_allowed(
        f, has_receipt=has_receipt, causal_current=causal_current,
        relation_active=relation_active, manifest_matches=manifest_matches)
    reason = (f"{band} {rp.AUDIT_MODE[f.audit_mode]}; "
              f"{rp.TIMING_LANE[f.timing_lane]}; {rp.MUX_POSTURE[f.mux_posture]}")
    if skip_eligible and not skipping:
        reason += " (skip-eligible but no receipt/active relation -> no skip)"
    return mk("allow", carrier, skipping, fallback, reason)
