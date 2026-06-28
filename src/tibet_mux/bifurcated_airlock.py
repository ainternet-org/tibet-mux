"""Bifurcated airlock — pass only if two forks reproduce byte-identically.

Jasper's closing stone (28 June): FMA3 fits on top for numerical/cadence
stability. Single-rounding FMA (`a*b+c` with ONE rounding) makes a float
computation deterministic; without a consistent FMA semantics two forks drift
in the low bits. So FMA3 attestation is the evidence that a machine can
*reliably run a lane* — and that is exactly what a bifurcated airlock demands:

    Run the workload in two independent cells. Pass only if they agree
    byte-for-byte. Determinism is the gate.

The link to posture:

- A cadence lane (#RCTAM T-digit) claims reproducible timing/compute. That claim
  is only PROVEN once the bifurcated airlock passes — the verdict is the audit
  evidence (A-digit) behind the cadence claim.
- If the two cells declare *different* compute semantics (one single-rounding-fma,
  one separate-mul-add), the airlock refuses up front: the planes are not
  comparable. This is why `cpu_capability` attests the rounding mode.
- A hop that has not passed cannot carry the cadence lane; under
  `posture_algebra.compose` (the meet) it floors the whole path.

Pure stdlib. Needs Python 3.13+ for single-rounding `math.fma`. For the commons.
"""
from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Callable, Sequence, Tuple

from . import cpu_capability as cc

HAS_FMA = hasattr(math, "fma")

Pair = Tuple[float, float]


def fused_accumulate(pairs: Sequence[Pair], init: float = 0.0, *, use_fma: bool) -> float:
    """An FMA-sensitive kernel: accumulate x*y into acc, fused or separate.

    With `use_fma` each step is one rounding (`math.fma`); without it each step
    is two roundings (`x*y` then `+acc`). For ill-conditioned inputs the two
    paths differ in the last bit — which is precisely what the airlock detects.
    """
    acc = float(init)
    for x, y in pairs:
        if use_fma:
            if not HAS_FMA:
                raise RuntimeError(
                    "single-rounding FMA requested but math.fma is unavailable "
                    "(needs Python 3.13+); cannot honestly attest the cadence lane"
                )
            acc = math.fma(x, y, acc)      # one rounding
        else:
            acc = x * y + acc              # two roundings
    return acc


def digest(x: float) -> str:
    """Byte-exact digest of a double. The airlock compares bytes, not 'close enough'."""
    return hashlib.sha256(struct.pack("<d", x)).hexdigest()[:16]


@dataclass
class Cell:
    """One isolated fork, carrying its CPU capability attestation."""
    name: str
    capability_receipt: dict

    @property
    def use_fma(self) -> bool:
        return cc.fma_permitted(self.capability_receipt)

    @property
    def rounding(self) -> str:
        sem = self.capability_receipt.get("compute_semantics", {})
        return sem.get("rounding", "?")


@dataclass
class BifurcationVerdict:
    passed: bool
    reason: str
    digest_a: str = ""
    digest_b: str = ""
    rounding_a: str = ""
    rounding_b: str = ""


def run_bifurcated(
    kernel: Callable[..., float],
    inputs: tuple,
    cell_a: Cell,
    cell_b: Cell,
) -> BifurcationVerdict:
    """Run `kernel(*inputs, use_fma=...)` in both cells. Pass iff same compute
    semantics AND byte-identical output."""
    ra, rb = cell_a.rounding, cell_b.rounding
    if ra != rb:
        return BifurcationVerdict(
            False,
            f"compute planes diverge: fork A is {ra}, fork B is {rb} — not comparable",
            rounding_a=ra, rounding_b=rb,
        )
    out_a = kernel(*inputs, use_fma=cell_a.use_fma)
    out_b = kernel(*inputs, use_fma=cell_b.use_fma)
    da, db = digest(out_a), digest(out_b)
    if da != db:
        return BifurcationVerdict(
            False,
            "nondeterminism / tamper: same semantics, divergent bytes",
            digest_a=da, digest_b=db, rounding_a=ra, rounding_b=rb,
        )
    return BifurcationVerdict(
        True,
        f"reproducible under {ra}: two forks agree byte-for-byte",
        digest_a=da, digest_b=db, rounding_a=ra, rounding_b=rb,
    )


def lane_provable(verdict: BifurcationVerdict) -> bool:
    """A cadence/audit lane is only provable once the bifurcated airlock passes."""
    return verdict.passed
