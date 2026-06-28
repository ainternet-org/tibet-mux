"""Posture algebra — compose postures along a tree and check the mapping.

Jasper's leap: lay a posture next to a model, fire a dummy through the tree, and
see whether the tree checks out. Postures compose. The composition of a path is
not free addition — it is the **meet** (per-digit minimum) of its hops, because:

    A route is only as strong as its weakest proven hop.

That single law gives us everything:

- per-digit min is the lattice meet; `#00000` (DARK) is the bottom element, so it
  is naturally *absorbing*: one dark hop darkens the whole path. Fail-closed and
  dark-by-default expressed as arithmetic, no special case.
- you can DECLARE the expected end-to-end posture of a tree (the mapping), fire a
  dummy through the real hops, FOLD them, and compare. Match = mapping correct.
  Mismatch = some hop is weaker (or stronger) than declared → the tree is wrong,
  drifted, or tampered. That is a checksum over the route tree.

So `#23856 ⊕ #12093 ⊕ #88347` is not 124296; it is `#12043` — and the 3rd digit
collapsing to 0 is the point: you cannot claim CBR-isochrone end-to-end when one
hop is reactive. The algebra refuses the lie.

This is the engine under route-posture (route trees), doc-posture (doc trees) and
repo-posture (deploy trees): a smoke pipeline fires a dummy and asserts the fold.

Pure stdlib. For the commons. Van de Meent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

DARK = "#00000"
_DIGITS = 5

# Digit meaning, for explanations (mirrors route_posture #RCTAM).
AXES = ("R route-family", "C consent-class", "T timing-lane",
        "A audit-origin", "M mux-posture")


def _body(p: str) -> str:
    """Strip the leading '#', validate, return the 5-char body."""
    s = p[1:] if p.startswith("#") else p
    if len(s) != _DIGITS or not s.isdigit():
        raise ValueError(f"not a posture: {p!r} (expected #NNNNN)")
    return s


def compose(*postures: str) -> str:
    """Fold postures into the path posture: the meet (per-digit minimum).

    DARK is the bottom element and is absorbing automatically (min with 0 is 0).
    Composing nothing is undefined; composing one returns it unchanged.
    """
    if not postures:
        raise ValueError("compose() needs at least one posture")
    bodies = [_body(p) for p in postures]
    folded = "".join(min(col) for col in zip(*bodies))
    return "#" + folded


def explain_fold(*postures: str) -> str:
    """Human line showing which hop pinned each digit (where the path is weakest)."""
    bodies = [_body(p) for p in postures]
    out = []
    for idx, axis in enumerate(AXES):
        col = [b[idx] for b in bodies]
        lo = min(col)
        pinned = [i for i, c in enumerate(col) if c == lo]
        out.append(f"  {axis}: -> {lo}  (pinned by hop {pinned})")
    return f"{ ' ⊕ '.join(postures) } = {compose(*postures)}\n" + "\n".join(out)


@dataclass
class SmokeResult:
    name: str
    expected: str
    observed: str
    ok: bool
    weakest: str = ""          # which axis/hop dragged it down, if mismatch
    note: str = ""


def verify_tree(hops: Iterable[str], expected: str) -> SmokeResult:
    """Fire a dummy through `hops`, fold, and compare to the declared `expected`.

    ok == True  -> the tree carries what the mapping claims.
    ok == False -> a hop is weaker/stronger than declared; the mapping is wrong.
    """
    hops = list(hops)
    observed = compose(*hops)
    ok = observed == expected
    weakest = ""
    if not ok:
        eb, ob = _body(expected), _body(observed)
        diffs = []
        for idx, axis in enumerate(AXES):
            if ob[idx] != eb[idx]:
                direction = "weaker" if ob[idx] < eb[idx] else "STRONGER-than-declared"
                diffs.append(f"{axis}: declared {eb[idx]}, observed {ob[idx]} ({direction})")
        weakest = "; ".join(diffs)
    return SmokeResult(name="", expected=expected, observed=observed, ok=ok,
                       weakest=weakest)


@dataclass
class Pipeline:
    """A declared posture tree: a named path of hops with an expected fold."""
    name: str
    hops: list[str]
    expected: str

    def smoke(self) -> SmokeResult:
        r = verify_tree(self.hops, self.expected)
        r.name = self.name
        return r


def run_smoke(pipelines: Iterable[Pipeline]) -> tuple[bool, list[SmokeResult]]:
    """Run every pipeline's dummy and report. all_ok == every tree checked out."""
    results = [p.smoke() for p in pipelines]
    return all(r.ok for r in results), results
