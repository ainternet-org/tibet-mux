"""The shipped posture_algebra conformance vectors must all pass.

docs explain; vectors decide. If this fails, the implementation drifted from the
agreed meet laws — not the other way around.
"""
from tibet_mux.conformance import run_posture_algebra_conformance


def test_shipped_vectors_all_pass():
    res = run_posture_algebra_conformance()
    assert res.ok, f"{res.failed} conformance failures: {res.failures}"
    assert res.passed >= 20  # compose + verify_tree + invalid + machine-boundary(compose)
