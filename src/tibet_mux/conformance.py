"""Conformance runner for posture_algebra — load the vectors, prove the laws.

Docs explain; vectors decide. This loads the
`org.ainternet.tibet_mux.posture_algebra.conformance.v1` vector set (shipped in
`vectors/`) and checks an implementation against it:

- compose_vectors          : compose(*postures) == expected (the meet laws)
- verify_tree_vectors      : verify_tree(hops, declared).passed/observed match,
                             and the must_mention drift line appears
- invalid_input_vectors    : compose(bad_input) raises ValueError
- machine_posture_boundary : ONLY the compose half is enforced here — compose stays
                             per-digit min regardless of FMA3/AES-NI evidence. The
                             can_carry() policy half belongs to machine_posture's own
                             runner (hardware is evidence, never a route-digit lift).

Pure stdlib.

    python3 -m tibet_mux.conformance        # run shipped vectors, exit 1 on any fail
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

from . import posture_algebra as pa

DEFAULT_VECTORS = os.path.join(
    os.path.dirname(__file__), "vectors", "posture_algebra_conformance_v1.json"
)


@dataclass
class ConformanceResult:
    passed: int = 0
    failed: int = 0
    failures: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


def run_posture_algebra_conformance(vectors_path: str | None = None) -> ConformanceResult:
    """Run the shipped (or given) vector set against this posture_algebra."""
    path = vectors_path or DEFAULT_VECTORS
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    res = ConformanceResult()

    def check(name, cond, detail=""):
        if cond:
            res.passed += 1
        else:
            res.failed += 1
            res.failures.append(f"{name}: {detail}")

    for v in data.get("compose_vectors", []):
        got = pa.compose(*v["postures"])
        check(f"compose/{v['name']}", got == v["expected"], f"got {got}, want {v['expected']}")

    for v in data.get("verify_tree_vectors", []):
        r = pa.verify_tree(v["hops"], v["declared_expected"])
        ok = (r.ok == v["ok"]) and (r.observed == v["observed"])
        if v.get("must_mention"):
            ok = ok and (v["must_mention"] in r.weakest)
        check(f"verify_tree/{v['name']}", ok,
              f"ok={r.ok} observed={r.observed} weakest={r.weakest!r}")

    for v in data.get("invalid_input_vectors", []):
        try:
            pa.compose(v["input"])
            raised = False
        except ValueError:
            raised = True
        except Exception:
            raised = False
        check(f"invalid/{v['input']!r}", raised, "did not raise ValueError")

    # Machine-posture boundary: enforce ONLY that compose is unaffected by hardware
    # evidence. The policy half (can_carry denies without AES-NI, etc.) is labelled
    # and verified by machine_posture's own runner — not folded into the algebra.
    for v in data.get("machine_posture_boundary_vectors", []):
        got = pa.compose(*v["postures"])
        check(f"machine_boundary(compose-only)/{v['name']}",
              got == v["compose_expected"], f"got {got}, want {v['compose_expected']}")

    return res


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    path = argv[0] if argv else None
    res = run_posture_algebra_conformance(path)
    for f in res.failures:
        print(f"  ⛔ {f}")
    print(f"posture_algebra conformance: {res.passed} passed, {res.failed} failed"
          + (" ✓" if res.ok else ""))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
