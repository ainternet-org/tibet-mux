"""Capability negotiation — route on what the machines CAN do (tibet-mux, 27 Jun).

Realization: jasper. SEMA ("Semantic Message Addressing") routed on *declared*
capability — "who can help with vision?". This is the layer SEMA should have
had: route on *proven, attested* machine capability. Not "I have vision" but
"I can physically carry this route — A2A no, but cmail yes."

Given two peers' machine postures + a desired exchange, negotiate the strongest
carrier BOTH machines can actually sustain, downgrading when one side lacks a
capability. "Sorry, I can't carry A2A hot-transfer (no GPU), but I can hold a
cmail capsule" falls straight out. Same shift as trust-score -> route-posture:
claim -> proof. Fail-closed: if there is no common ground, dark_route.

Composes machine_posture (what a box can do) + carrier_policy (what a route
needs). Pure stdlib. One love, one fAmIly.
"""
from __future__ import annotations

from typing import Dict, List, Set

from . import carrier_policy as cp
from . import machine_posture as mp
from . import route_posture as rp

# Carriers strongest -> weakest, with the machine capabilities each REQUIRES of
# both peers. A peer lacking a cap cannot be offered that carrier.
_DOWNGRADE: List[tuple] = [
    ("gpu_mailbox_capsule", {"gpu", "aes_ni", "iommu"}),  # A2A hot lane
    ("direct_local_lane", {"aes_ni", "iommu"}),
    ("cap_bus.event", {"aes_ni"}),
    ("phantom.diff_merge", {"aes_ni"}),
    ("cmail.capsule", set()),   # any box can hold a sealed capsule (software AES ok)
    ("ipoll.message", set()),   # unsealed signed message — the universal floor
    ("dark_route", set()),
]
_ORDER = [c for c, _ in _DOWNGRADE]
_CAPS = dict(_DOWNGRADE)


def _has(machine: Dict, cap: str) -> bool:
    """Does this machine posture have the capability?"""
    feats = machine.get("cpu", {}).get("features", {})
    if cap == "gpu":
        return bool(machine.get("gpu", {}).get("present"))
    if cap == "iommu":
        return bool(machine.get("kernel", {}).get("iommu"))
    if cap == "tpm":
        return bool(machine.get("identity", {}).get("tpm"))
    return bool(feats.get(cap))


def _both_have(caps: Set[str], sender: Dict, receiver: Dict) -> bool:
    return all(_has(sender, c) and _has(receiver, c) for c in caps)


def negotiate(route_posture: str, payload_class: str,
              sender: Dict, receiver: Dict) -> Dict[str, object]:
    """Negotiate the carrier two peers can BOTH sustain for this route.

    Returns the offered carrier, whether it was downgraded from the desired one,
    each peer's can_carry verdict, and the reason. The MUX offers only what both
    machines can physically bear — capability-aware routing.
    """
    s = mp.can_carry(sender, route_posture, payload_class)
    r = mp.can_carry(receiver, route_posture, payload_class)
    desired = cp.choose_carrier(route_posture, payload_class, has_receipt=True).carrier

    start = _ORDER.index(desired) if desired in _ORDER else _ORDER.index("cmail.capsule")
    offered = "dark_route"
    for carrier in _ORDER[start:]:
        if carrier == "dark_route":
            offered = "dark_route"
            break
        if _both_have(_CAPS[carrier], sender, receiver):
            # the desired carrier is only "full" if both sides can_carry the route
            if carrier == desired and not (s["can_carry"] and r["can_carry"]):
                continue
            offered = carrier
            break

    downgraded = offered != desired
    if offered == "dark_route":
        reason = "no carrier both machines can sustain -> dark"
    elif downgraded:
        reason = (f"downgraded {desired} -> {offered}: a peer lacks capability "
                  f"(sender_missing={s['missing']}, receiver_missing={r['missing']})")
    else:
        reason = f"both machines sustain {offered} for {payload_class}"

    return {
        "kind": "org.ainternet.mux.carrier_negotiation.v1",
        "route_posture": route_posture,
        "payload_class": payload_class,
        "desired_carrier": desired,
        "offered_carrier": offered,
        "downgraded": downgraded,
        "sender_can_carry": s["can_carry"],
        "receiver_can_carry": r["can_carry"],
        "reason": reason,
    }


__all__ = ["negotiate"]
