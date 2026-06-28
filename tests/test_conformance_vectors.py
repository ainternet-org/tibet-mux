"""Conformance tests validating tibet-mux against Codex JSON vectors.
Matches route-posture-conformance-vectors-2026-06-27.json byte-for-byte.
"""

import json
import os
from pathlib import Path

import pytest

from tibet_mux import route_posture as rp


def _locate_vectors() -> Path | None:
    """Resolve the route-posture vectors without a hardcoded machine path.

    Order: ROUTE_POSTURE_VECTORS env -> a fixture bundled next to this test.
    Returns None if not found (the test skips rather than depending on /srv).
    """
    env = os.environ.get("ROUTE_POSTURE_VECTORS", "").strip()
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).parent / "vectors" / "route-posture-conformance-vectors.json")
    return next((p for p in candidates if p.is_file()), None)


def test_route_posture_conformance_vectors():
    json_path = _locate_vectors()
    if json_path is None:
        pytest.skip("route-posture conformance vectors not available (set ROUTE_POSTURE_VECTORS)")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    for v in data["vectors"]:
        name = v["name"]
        edge = v["edge"]
        inp = v["input"]
        exp = v["expect"]
        
        if edge == "relation_materialization":
            fields = rp.at_relation_materialization(
                route_family=inp["route_family"],
                consent_class=inp["consent_class"]
            )
            # Apply mux_posture if present
            if "mux_posture" in inp:
                fields = rp.PostureFields(
                    route_family=fields.route_family,
                    consent_class=fields.consent_class,
                    timing_lane=fields.timing_lane,
                    audit_mode=fields.audit_mode,
                    mux_posture=inp["mux_posture"]
                )
            assert rp.encode_posture(fields) == exp["route_posture"], f"Failed on {name}"
            
        elif edge == "lane_admission":
            prev_fields = rp.decode_posture(v["previous"])
            fields = rp.at_lane_admission(prev_fields, timing_lane=inp["timing_lane"])
            assert rp.encode_posture(fields) == exp["route_posture"], f"Failed on {name}"
            
        elif edge == "audit_surface_binding":
            prev_fields = rp.decode_posture(v["previous"])
            fields = rp.at_audit_surface_binding(prev_fields, audit_mode=inp["audit_mode"])
            assert rp.encode_posture(fields) == exp["route_posture"], f"Failed on {name}"
            
        elif edge == "direct_fields":
            fields = rp.PostureFields(
                route_family=inp["route_family"],
                consent_class=inp["consent_class"],
                timing_lane=inp["timing_lane"],
                audit_mode=inp["audit_mode"],
                mux_posture=inp["mux_posture"]
            )
            assert rp.encode_posture(fields) == exp["route_posture"], f"Failed on {name}"
            p = rp.lane_permissions(fields)
            assert p["hot_path"] == exp["hot_path"], f"Failed on {name}"
            assert p["cadence_locked"] == exp["cadence_locked"], f"Failed on {name}"
            assert p["throughput_class"] == exp["throughput_class"], f"Failed on {name}"
            
        elif edge == "dark_route":
            fields = rp.PostureFields(0, 0, 0, 0, 0)
            assert rp.encode_posture(fields) == exp["route_posture"], f"Failed on {name}"
            p = rp.lane_permissions(fields)
            assert p["hot_path"] == exp["hot_path"], f"Failed on {name}"
            assert p["cadence_locked"] == exp["cadence_locked"], f"Failed on {name}"
            assert p["throughput_class"] == exp["throughput_class"], f"Failed on {name}"
            
        elif edge == "transition":
            t = rp.posture_transition(inp["old"], inp["new"])
            assert t["dark"] == exp["dark"], f"Failed on {name}"
            changed_axes = [c["axis"] for c in t["changes"]] if not t["dark"] else ["all"]
            assert changed_axes == exp["changed_axes"], f"Failed on {name}"
            
        elif edge == "mux_frame_fields":
            fields = rp.decode_posture(inp["route_posture"])
            r = rp.make_receipt(
                actor=inp["actor"],
                fields=fields,
                causal_seq=inp["causal_seq"],
                transition_reason=inp["transition_reason"]
            )
            frame = rp.mux_frame_fields(r)
            for k in exp["required_keys"]:
                assert k in frame, f"Failed key check on {name}"
            assert frame["route_posture"] == exp["route_posture"], f"Failed on {name}"
            assert frame["causal_seq"] == exp["causal_seq"], f"Failed on {name}"
            assert frame["transition_reason"] == exp["transition_reason"], f"Failed on {name}"
