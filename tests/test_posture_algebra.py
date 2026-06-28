"""Tests for posture algebra and composition of proof (lattice meet).
Validates that postures do not add, they intersect/constrain (weakest-link).
"""

import pytest
from tibet_mux import posture_algebra as pa

def test_posture_algebra_compose_weakest_link():
    # Intersection/meet of postures: per-digit minimum
    # #23856 ⊕ #12093 ⊕ #88347 = #12043
    # Index 0: min(2, 1, 8) = 1
    # Index 1: min(3, 2, 8) = 2
    # Index 2: min(8, 0, 3) = 0
    # Index 3: min(5, 9, 4) = 4
    # Index 4: min(6, 3, 7) = 3
    res = pa.compose("#23856", "#12093", "#88347")
    assert res == "#12043"

def test_posture_algebra_absorbing_dark():
    # Dark posture (#00000) is the bottom element and absorbing
    res = pa.compose("#23856", pa.DARK, "#88347")
    assert res == pa.DARK

def test_explain_fold_human_readable():
    explanation = pa.explain_fold("#23856", "#12093", "#88347")
    assert "23856 ⊕ #12093 ⊕ #88347 = #12043" in explanation
    assert "R route-family" in explanation
    assert "T timing-lane: -> 0" in explanation

def test_verify_tree_matching():
    hops = ["#24358", "#34358", "#24359"]
    expected = "#24358" # min digits of all hops
    r = pa.verify_tree(hops, expected)
    assert r.ok is True
    assert r.observed == expected

def test_verify_tree_mismatch():
    hops = ["#24358", "#24258", "#24359"]
    # expected has T=3, but one hop fell back to T=2 (reactive/batched wait)
    expected = "#24358"
    r = pa.verify_tree(hops, expected)
    assert r.ok is False
    assert "T timing-lane: declared 3, observed 2 (weaker)" in r.weakest

def test_pipeline_smoke_testing():
    p = pa.Pipeline(
        name="gpu-mailbox-hot-path",
        hops=["#24358", "#24358"],
        expected="#24358"
    )
    r = p.smoke()
    assert r.name == "gpu-mailbox-hot-path"
    assert r.ok is True

def test_run_smoke_multiple_pipelines():
    p1 = pa.Pipeline("p1", ["#24358", "#24358"], "#24358")
    p2 = pa.Pipeline("p2", ["#24358", "#24258"], "#24258")
    
    all_ok, results = pa.run_smoke([p1, p2])
    assert all_ok is True
    assert len(results) == 2
    assert results[0].ok is True
    assert results[1].ok is True
