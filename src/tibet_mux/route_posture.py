"""Route Posture Number — not an agent trust score (tibet-mux, 27 Jun 2026).

Design: codex.aint (route-posture-number-not-trust-score doc). Build: root_idd.

An actor does NOT get a permanent "trust = 0.87". A fleeting runtime has a
*current proven posture* for a *specific lane/action/window*. We encode that
posture as a compact 5-digit route number, e.g. ``#24078`` — a coordinate into
evidence, not a moral rating:

    #RCTAM
     |||||
     ||||+-- M: MUX-known / exception posture
     |||+--- A: audit / receipt mode
     ||+---- T: timing / hardware wait lane     (← ties to the cadence ladder)
     |+----- C: consent / relation class
     +------ R: route family / actor class

Doctrine (codex): *trust is not a rating of the actor; trust is the currently
proven route.* The old scalar "trust score" survives only as a human INDEX into
evidence: "show me what #24078 meant, and why it changed to #23078."

Causal-time note (jasper): a posture number is a richer audit coordinate than
"jasper.aint @ 14:02" — and wall-clock is not trustworthy (a P520 drifted 2h and
fell out of sync with the KVM/DL360). So receipts order by a CAUSAL sequence
(Lamport), and carry wall-clock only as *advisory*, explicitly flagged.

Pure stdlib so the MUX, CLI, docs, receipts and arena/richard views can all
share one encoder. One love, one fAmIly.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Optional

# --- Digit semantics (each digit 0-9; map can evolve, doctrine cannot) -------
# R — route family / actor class (apocope forms)
ROUTE_FAMILY: Dict[int, str] = {
    0: "unknown",
    1: "aint (direct identity)",
    2: "saint (controller / system service)",
    3: "raint (runtime enclave)",
    4: "waint (wrapper / tool / resource)",
    5: "caint (composite route)",
}
# C — consent / relation class (escalating strength of what is proven)
CONSENT_CLASS: Dict[int, str] = {
    0: "none",
    1: "token-only",
    2: "fresh JIS challenge",
    3: "bilateral consent",
    4: "active parent relation (bound)",
    5: "2-of-2 DAG relation",
}
# T — timing / hardware wait lane (THE cadence ladder we measured live)
TIMING_LANE: Dict[int, str] = {
    0: "reactive (scheduler in loop)",
    1: "async-batched",
    2: "CBR sleep metronome",
    3: "CBR spin — scheduler-free (RDTSC), 0.00-bit timing",
    4: "DMA graph — CPU out of the loop",
    5: "DMA descriptor ring (isolated device)",
}
# A — audit / receipt mode = EVIDENCE ORIGIN ladder (codex's A2..A7 map).
# Higher = stronger provenance AND a wider throughput gate (see lane_permissions).
#   A2 = camera on the door (observed off-path)
#   A4 = the door handle signs when it moves (native seam, in-path)
#   A5 = the door handle already signed before your hand reached it (shadow)
AUDIT_MODE: Dict[int, str] = {
    0: "none",
    1: "log-only",
    2: "A2 mirrored / observed (off-path camera)",
    3: "A3 receipted",
    4: "A4 native seam (signs in-path)",
    5: "A5 sign-ahead (pre-signed in compute shadow)",
    6: "A6 cadenced (aligned to a known partituur / CBR)",
    7: "A7 durable",
}
# M — MUX-known / exception posture (0 = dark; 8/9 = known; 1-7 = exceptions)
MUX_POSTURE: Dict[int, str] = {
    0: "dark — no valid posture",
    1: "unknown actor",
    2: "stale posture",
    3: "unexpected posture",
    4: "posture changed mid-route",
    5: "actor-class mismatch",
    6: "consent expired",
    7: "hardware lane fell back without receipt",
    8: "MUX knows the partituur",
    9: "MUX knows the partituur — verified",
}

_FIELD_MAPS = (ROUTE_FAMILY, CONSENT_CLASS, TIMING_LANE, AUDIT_MODE, MUX_POSTURE)
_FIELD_NAMES = ("route_family", "consent_class", "timing_lane", "audit_mode", "mux_posture")

#: The dark route — no valid posture on any axis.
DARK = "#00000"

#: The one-line doctrine (jasper — embraced by codex.aint). The whole
#: correction in six words.
DOCTRINE = "Do not score the actor. Number the proven route."


@dataclass(frozen=True)
class PostureFields:
    """The five proven-posture axes of a lane at one moment."""
    route_family: int = 0
    consent_class: int = 0
    timing_lane: int = 0
    audit_mode: int = 0
    mux_posture: int = 0

    def _digits(self):
        return (self.route_family, self.consent_class, self.timing_lane,
                self.audit_mode, self.mux_posture)

    def validate(self) -> None:
        for name, val, m in zip(_FIELD_NAMES, self._digits(), _FIELD_MAPS):
            if val not in m:
                raise ValueError(f"{name}={val} is not a defined posture digit (0-{max(m)})")


def encode_posture(fields: PostureFields) -> str:
    """PostureFields -> ``#RCTAM`` (validated)."""
    fields.validate()
    return "#" + "".join(str(d) for d in fields._digits())


def decode_posture(number: str) -> PostureFields:
    """``#RCTAM`` -> PostureFields (validated)."""
    s = number.lstrip("#")
    if len(s) != 5 or not s.isdigit():
        raise ValueError(f"route posture must be 5 digits like #24078, got {number!r}")
    f = PostureFields(*(int(c) for c in s))
    f.validate()
    return f


def explain(number: str) -> Dict[str, str]:
    """Human cheat-sheet: each axis decoded to its label."""
    f = decode_posture(number)
    return {
        name: m[val]
        for name, val, m in zip(_FIELD_NAMES, f._digits(), _FIELD_MAPS)
    }


def posture_transition(old: str, new: str) -> Dict[str, object]:
    """Describe a posture change as actionable transitions (codex's model).

    Returns the changed axes, each with direction (weakened/strengthened) and a
    human reason — e.g. #24078 -> #23078 = 'hardware lane fallback'. A move to
    DARK is flagged explicitly.
    """
    fo, fn = decode_posture(old), decode_posture(new)
    if new == DARK:
        return {"old": old, "new": new, "dark": True,
                "changes": [{"axis": "all", "reason": "dark route / no valid posture"}]}
    changes = []
    for name, ov, nv, m in zip(_FIELD_NAMES, fo._digits(), fn._digits(), _FIELD_MAPS):
        if ov != nv:
            direction = "weakened" if nv < ov else "strengthened"
            changes.append({
                "axis": name,
                "from": m[ov], "to": m[nv],
                "direction": direction,
                "reason": f"{name.replace('_', ' ')} {direction}: {m[ov]} -> {m[nv]}",
            })
    return {"old": old, "new": new, "dark": False, "changes": changes}


@dataclass
class PostureReceipt:
    """Codex's receipt rule, causal-first (jasper: wall-clock is advisory)."""
    actor: str
    actor_class: str
    route_posture: str
    expanded: Dict[str, str]
    parent_handle: Optional[str] = None
    relation_hash: Optional[str] = None
    mux_known: bool = False
    partituur_known: bool = False
    #: AUTHORITATIVE ordering — a Lamport/causal sequence, not a clock.
    causal_seq: int = 0
    expires_seq: Optional[int] = None
    transition_reason: Optional[str] = None
    #: ADVISORY ONLY — may be wrong (P520 drifted 2h). Never order on this.
    wall_clock_advisory: Optional[str] = None
    wall_clock_trusted: bool = field(default=False)

    def as_dict(self) -> Dict[str, object]:
        return {
            "kind": "org.ainternet.mux.route_posture_receipt.v1",
            "actor": self.actor,
            "actor_class": self.actor_class,
            "route_posture": self.route_posture,
            "expanded": self.expanded,
            "parent_handle": self.parent_handle,
            "relation_hash": self.relation_hash,
            "mux_known": self.mux_known,
            "partituur_known": self.partituur_known,
            "causal_seq": self.causal_seq,
            "expires_seq": self.expires_seq,
            "transition_reason": self.transition_reason,
            "wall_clock_advisory": self.wall_clock_advisory,
            "wall_clock_trusted": self.wall_clock_trusted,
        }


def make_receipt(actor: str, fields: PostureFields, *, causal_seq: int,
                 parent_handle: Optional[str] = None, relation_hash: Optional[str] = None,
                 expires_seq: Optional[int] = None, transition_reason: Optional[str] = None,
                 wall_clock_advisory: Optional[str] = None) -> PostureReceipt:
    """Build a posture receipt from the proven posture + a causal sequence.

    The MUX calls this once it has measured a lane's posture. The number indexes
    the evidence; the causal_seq orders it; wall-clock is carried but distrusted.
    """
    number = encode_posture(fields)
    exp = explain(number)
    return PostureReceipt(
        actor=actor,
        actor_class=ROUTE_FAMILY[fields.route_family],
        route_posture=number,
        expanded=exp,
        parent_handle=parent_handle,
        relation_hash=relation_hash,
        mux_known=fields.mux_posture in (8, 9),
        partituur_known=fields.mux_posture in (8, 9),
        causal_seq=causal_seq,
        expires_seq=expires_seq,
        transition_reason=transition_reason,
        wall_clock_advisory=wall_clock_advisory,
        wall_clock_trusted=False,
    )


# --- Posture IS a gate (codex: audit mode as partituur/state/throughput gate) -
# The number doesn't only DESCRIBE the lane; it bounds what the lane may do —
# which wait state, which throughput class. A2 mirrored = measured but not
# hot-path; A4+ (native seam / sign-ahead / cadenced) = hot path allowed.

def lane_permissions(fields: PostureFields) -> Dict[str, object]:
    """What this posture *allows* — not a description, a gate."""
    fields.validate()
    a, t = fields.audit_mode, fields.timing_lane
    if a <= 1:
        throughput = "none (unaudited)"
    elif a in (2, 3):
        throughput = "measured (not hot-path)"
    else:  # A4 native / A5 sign-ahead / A6 cadenced / A7 durable
        throughput = "hot-path allowed"
    return {
        # Hot path needs evidence in-path or ahead-of-path (native seam or better).
        "hot_path": a >= 4,
        # A locked cadence needs a scheduler-free/GPU-paced lane AND a MUX that
        # knows the partituur.
        "cadence_locked": t >= 3 and fields.mux_posture in (8, 9),
        "throughput_class": throughput,
    }


# --- The three state edges where the MUX SETS the posture (codex's contract) --
# Posture is set at concrete edges, then only transitions. Each edge refines the
# number; T is set at lane admission, A at audit-surface binding.

def at_relation_materialization(route_family: int, consent_class: int,
                                *, mux_posture: int = 8) -> PostureFields:
    """Edge 1: JIS challenge + consent receipt + parent/relation hash landed.
    T and A are not measured yet (0); the initial #RCTAM is minted here."""
    f = PostureFields(route_family, consent_class, 0, 0, mux_posture)
    f.validate()
    return f


def at_lane_admission(prev: PostureFields, timing_lane: int) -> PostureFields:
    """Edge 2: hardware/timing lane selected/measured -> update T before the
    first payload route."""
    f = replace(prev, timing_lane=timing_lane)
    f.validate()
    return f


def at_audit_surface_binding(prev: PostureFields, audit_mode: int) -> PostureFields:
    """Edge 3: audit surface (A2..A7) chosen by evidence origin -> update A."""
    f = replace(prev, audit_mode=audit_mode)
    f.validate()
    return f


def mux_frame_fields(receipt: "PostureReceipt") -> Dict[str, object]:
    """Exactly the posture fields the MUX-frame must carry (codex's contract):
    route_posture + expanded_posture + causal_seq + transition_reason."""
    return {
        "route_posture": receipt.route_posture,
        "expanded_posture": receipt.expanded,
        "causal_seq": receipt.causal_seq,
        "transition_reason": receipt.transition_reason,
    }


# --- The map (jasper): who / where / what / WHEN-causal ----------------------
# Trust score = nothing you can act on. But route postures across actors and
# causal sequence compose into a navigable MAP: a router for identity + posture
# + intent, not packets. "where" = lane/MUX, "what" = audit/action, "when" =
# causal_seq (NEVER wall-clock — a P520 drifted 2h).

def posture_map(receipts) -> Dict[str, object]:
    """Compose posture receipts into a map.

    Returns ``{"snapshot": {actor: latest receipt}, "trace": {actor: [receipts
    ordered by causal_seq]}}`` — the live topology + each actor's causal path.
    """
    by_actor: Dict[str, list] = {}
    for r in receipts:
        by_actor.setdefault(r.actor, []).append(r)
    for actor in by_actor:
        by_actor[actor].sort(key=lambda r: r.causal_seq)
    snapshot = {actor: rs[-1] for actor, rs in by_actor.items()}
    return {"snapshot": snapshot, "trace": by_actor}


def render_map(receipts) -> str:
    """Human map: who / where / what / when (causal). The thing a trust score
    can never give you."""
    m = posture_map(receipts)
    lines = ["Route-posture map — who / where / what / when (causal, not wall-clock)"]
    for actor, r in sorted(m["snapshot"].items()):
        e = r.expanded
        lines.append(f"  {actor}  [{r.actor_class}]  posture {r.route_posture}  @seq {r.causal_seq}")
        lines.append(f"      where : {e['timing_lane']}  |  {e['mux_posture']}")
        lines.append(f"      what  : {e['audit_mode']}  (consent: {e['consent_class']})")
        path = m["trace"][actor]
        if len(path) > 1:
            trail = " -> ".join(f"{p.route_posture}@{p.causal_seq}" for p in path)
            lines.append(f"      when  : {trail}")
    return "\n".join(lines)


# --- Retrace your steps (jasper): reconstruction, not a score ----------------
# A log line "jasper.aint (0.95) did rm -rf /dir" tells you NOTHING. The score
# authorizes nothing useful. What you need is what you do when you lose your
# keys in real life: retrace. Where did I stand, what did I hold, what was said
# before, who was there. Each lane answers a different reconstruction question;
# Storm being there is lane-1 evidence; "what did papa say before" is the causal
# trail. The score appears NOWHERE — because it never mattered.

def reconstruct_event(receipts, actor: str, at_seq: int, window: int = 8) -> Dict[str, object]:
    """Reconstruct the context around an actor's action at a causal sequence.

    Returns the incident posture, what was said/done just before (the causal
    trail), who else was present (witnesses — lane-1 evidence), and each posture
    lane's answer. No trust score: you retrace, you don't rate.
    """
    rs = sorted(receipts, key=lambda r: r.causal_seq)
    incident = None
    for r in rs:
        if r.actor == actor and r.causal_seq <= at_seq:
            incident = r  # the actor's most recent posture at/before the event
    if incident is None:
        raise ValueError(f"no posture for {actor} at/before seq {at_seq}")
    lo = at_seq - window
    before = [r for r in rs if lo <= r.causal_seq < incident.causal_seq]
    witnesses = sorted({r.actor for r in rs
                        if lo <= r.causal_seq <= at_seq and r.actor != actor})
    e = incident.expanded
    return {
        "incident": {
            "who": f"{incident.actor} [{incident.actor_class}]",
            "route_posture": incident.route_posture,
            "causal_seq": incident.causal_seq,
            "wall_clock_advisory": incident.wall_clock_advisory,  # distrusted
        },
        # "wat is ervoor gezegd/gedaan" — the causal trail, any actor
        "before": [{"actor": r.actor, "posture": r.route_posture,
                    "seq": r.causal_seq, "reason": r.transition_reason} for r in before],
        # "wie was erbij" — co-present actors (Storm was there = lane-1 evidence)
        "witnesses": witnesses,
        # each lane answers its reconstruction question
        "by_lane": {
            "who (R)": f"{incident.actor} [{incident.actor_class}]",
            "consent (C)": e["consent_class"],
            "where/how (T)": e["timing_lane"],
            "what-evidence (A)": e["audit_mode"],
            "mux (M)": e["mux_posture"],
        },
        "note": "no trust score is consulted; the route is reconstructed, not rated",
    }


def human_card(number: str) -> str:
    """The CLI / docs / receipt display block."""
    e = explain(number)
    return (
        f"{number}\n"
        f"  route family : {e['route_family']}\n"
        f"  consent      : {e['consent_class']}\n"
        f"  timing lane  : {e['timing_lane']}\n"
        f"  audit        : {e['audit_mode']}\n"
        f"  mux posture  : {e['mux_posture']}"
    )
