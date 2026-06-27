"""Workload split — "85% here, the rest goes elsewhere" (tibet-mux, 27 Jun 2026).

Realization: jasper. machine_posture answers can-I-carry (yes/no). This answers
the next question: HOW MUCH can run locally, and WHERE does the overflow go?

    "I can do 85% on this machine; the rest must go to Anthropic servers, or to
     Ollama which for 10% extra wants compute from GPU-cloud company X."

That sentence becomes a function. Given a workload and targets in PREFERENCE
order (local first, then remotes), plan_split greedily fills each target up to
its capacity — but only targets that CAN CARRY the route (machine_posture /
negotiate). The overflow cascades down the list, so Ollama running out spills to
the GPU cloud, which spills to Anthropic. A dark route assigns nothing.

Composes machine_posture + carrier negotiation. Capacity estimation itself is an
input (its own concern); this owns the split + overflow + honest 'uncovered'.
Pure stdlib. One love, one fAmIly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import route_posture as rp

SPLIT_KIND = "org.ainternet.mux.workload_split.v1"


@dataclass
class Target:
    """A place work can run. capacity_units=None means unbounded (e.g. a cloud
    API). can_carry comes from machine_posture/negotiate — a target that cannot
    carry the route is skipped, never silently overloaded."""
    name: str
    kind: str  # local | ollama | anthropic | gpu_cloud | peer
    capacity_units: Optional[float] = None
    can_carry: bool = True
    cost_per_unit: float = 0.0
    note: str = ""


@dataclass
class Assignment:
    target: str
    kind: str
    units: float
    fraction: float
    cost: float
    note: str = ""

    def as_dict(self) -> Dict:
        return {"target": self.target, "kind": self.kind, "units": self.units,
                "fraction": round(self.fraction, 4), "cost": round(self.cost, 6),
                "note": self.note}


def plan_split(total_units: float, targets: List[Target], *,
               route_posture: Optional[str] = None) -> Dict:
    """Split a workload across targets in preference order, respecting capacity
    and can_carry. Overflow cascades to the next target. Honest 'uncovered' when
    no target can take the remainder."""
    if total_units <= 0:
        raise ValueError("total_units must be > 0")
    if route_posture == rp.DARK:
        return {"kind": SPLIT_KIND, "total_units": total_units, "assignments": [],
                "covered": 0.0, "uncovered": float(total_units), "fully_covered": False,
                "summary": "dark route — no target opens",
                "reason": "dark route (#00000): nothing assigned"}

    remaining = float(total_units)
    out: List[Assignment] = []
    skipped: List[str] = []
    for t in targets:
        if remaining <= 1e-9:
            break
        if not t.can_carry:
            skipped.append(f"{t.name} (cannot carry route)")
            continue
        cap = remaining if t.capacity_units is None else min(remaining, float(t.capacity_units))
        if cap <= 0:
            continue
        out.append(Assignment(t.name, t.kind, cap, cap / total_units,
                              cap * t.cost_per_unit, t.note))
        remaining -= cap

    covered = total_units - remaining
    return {
        "kind": SPLIT_KIND,
        "total_units": total_units,
        "assignments": [a.as_dict() for a in out],
        "covered": round(covered, 6),
        "uncovered": round(remaining, 6),
        "fully_covered": remaining <= 1e-9,
        "skipped": skipped,
        "total_cost": round(sum(a.cost for a in out), 6),
        "summary": " + ".join(f"{round(a.fraction * 100)}% {a.target}" for a in out)
        or "nothing",
    }


def describe(plan: Dict) -> str:
    """The human sentence: '85% local + 10% ollama@p520 + 5% anthropic'."""
    line = plan["summary"]
    if not plan["fully_covered"]:
        line += f"  (⚠ {round(plan['uncovered'] / plan['total_units'] * 100)}% UNCOVERED)"
    if plan.get("skipped"):
        line += f"  [skipped: {', '.join(plan['skipped'])}]"
    return line


__all__ = ["Target", "Assignment", "plan_split", "describe", "SPLIT_KIND"]
