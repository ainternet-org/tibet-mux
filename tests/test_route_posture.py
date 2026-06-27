"""Route posture number — not a trust score. Design: codex.aint; build: root_idd."""
import pytest

from tibet_mux import route_posture as rp


def test_encode_decode_roundtrip():
    f = rp.PostureFields(2, 4, 3, 4, 8)
    num = rp.encode_posture(f)
    assert num == "#24348"
    assert rp.decode_posture(num) == f


def test_explain_is_human_readable():
    e = rp.explain("#24348")
    assert "saint" in e["route_family"]
    assert "scheduler-free" in e["timing_lane"]  # ties to the cadence ladder
    assert "MUX knows the partituur" == e["mux_posture"]


def test_timing_lane_is_the_cadence_ladder():
    # The lane digit is a live readout of the real timing posture we measured.
    assert "reactive" in rp.TIMING_LANE[0]
    assert "RDTSC" in rp.TIMING_LANE[3]
    assert "CPU out" in rp.TIMING_LANE[4]


def test_transition_reports_weakening():
    t = rp.posture_transition("#24348", "#24247")
    assert t["dark"] is False
    axes = {c["axis"]: c for c in t["changes"]}
    assert axes["timing_lane"]["direction"] == "weakened"
    assert axes["mux_posture"]["direction"] == "weakened"


def test_dark_route_is_flagged():
    t = rp.posture_transition("#24348", rp.DARK)
    assert t["dark"] is True
    assert "dark route" in t["changes"][0]["reason"]


def test_receipt_is_causal_first_walls_clock_distrusted():
    f = rp.PostureFields(2, 4, 3, 4, 8)
    r = rp.make_receipt("jasper.aint", f, causal_seq=4096,
                        wall_clock_advisory="2026-06-27T14:02:00Z (P520, may drift)")
    d = r.as_dict()
    # Jasper's point: a 2h-drifted P520 means wall-clock can never be authority.
    assert d["wall_clock_trusted"] is False
    assert d["causal_seq"] == 4096
    assert d["route_posture"] == "#24348"
    assert d["actor_class"].startswith("saint")
    assert d["mux_known"] is True


def test_no_such_thing_as_a_trust_score():
    # There is no scalar 'trust' anywhere — only the proven route posture.
    assert not hasattr(rp, "trust_score")
    assert "trust_score" not in rp.PostureReceipt.__dataclass_fields__


def test_invalid_digit_rejected():
    with pytest.raises(ValueError):
        rp.encode_posture(rp.PostureFields(route_family=9))
    with pytest.raises(ValueError):
        rp.decode_posture("#999")  # wrong length


def test_dark_constant():
    assert rp.DARK == "#00000"
    assert rp.explain(rp.DARK)["mux_posture"].startswith("dark")


# --- Codex's contract: A2..A7 evidence-origin, the gate, the three edges ------

def test_audit_is_evidence_origin_ladder():
    assert "mirrored" in rp.AUDIT_MODE[2]      # A2 camera on the door
    assert "native seam" in rp.AUDIT_MODE[4]   # A4 signs in-path
    assert "sign-ahead" in rp.AUDIT_MODE[5]    # A5 signed before your hand
    assert "cadenced" in rp.AUDIT_MODE[6]


def test_posture_is_a_gate():
    # A2 mirrored: measured, NOT hot-path.
    mirrored = rp.PostureFields(2, 4, 3, 2, 8)
    p = rp.lane_permissions(mirrored)
    assert p["hot_path"] is False
    assert "not hot-path" in p["throughput_class"]
    # A5 sign-ahead on a spin lane the MUX knows: hot-path + cadence locked.
    sign_ahead = rp.PostureFields(2, 4, 3, 5, 8)
    p2 = rp.lane_permissions(sign_ahead)
    assert p2["hot_path"] is True
    assert p2["cadence_locked"] is True
    assert p2["throughput_class"] == "hot-path allowed"


def test_three_state_edges_refine_the_number():
    # Edge 1: relation materialized — T and A not measured yet.
    f1 = rp.at_relation_materialization(route_family=2, consent_class=4)
    assert rp.encode_posture(f1) == "#24008"
    # Edge 2: lane admission sets T (CBR spin, scheduler-free).
    f2 = rp.at_lane_admission(f1, timing_lane=3)
    assert rp.encode_posture(f2) == "#24308"
    # Edge 3: audit surface binding sets A (sign-ahead).
    f3 = rp.at_audit_surface_binding(f2, audit_mode=5)
    assert rp.encode_posture(f3) == "#24358"
    assert rp.lane_permissions(f3)["hot_path"] is True


def test_mux_frame_carries_the_four_fields():
    f = rp.at_audit_surface_binding(
        rp.at_lane_admission(rp.at_relation_materialization(2, 4), 3), 5)
    r = rp.make_receipt("jasper.aint", f, causal_seq=4096, transition_reason="initial")
    frame = rp.mux_frame_fields(r)
    assert set(frame) == {"route_posture", "expanded_posture", "causal_seq", "transition_reason"}
    assert frame["route_posture"] == "#24358"
    assert frame["causal_seq"] == 4096


def test_posture_map_who_where_what_when():
    rs = [
        rp.make_receipt("a.aint", rp.PostureFields(1, 4, 3, 5, 8), causal_seq=10),
        rp.make_receipt("b.waint", rp.PostureFields(4, 5, 3, 5, 9), causal_seq=11),
        rp.make_receipt("b.waint", rp.PostureFields(4, 5, 2, 2, 7), causal_seq=20,
                        transition_reason="lane fallback"),
    ]
    m = rp.posture_map(rs)
    # snapshot = latest by causal_seq (NOT wall-clock)
    assert m["snapshot"]["b.waint"].causal_seq == 20
    assert len(m["trace"]["b.waint"]) == 2  # the causal path
    out = rp.render_map(rs)
    assert "who / where / what / when" in out
    assert "a.aint" in out and "b.waint" in out


def test_reconstruct_retrace_not_rate():
    r = [
        rp.make_receipt("controller.saint", rp.PostureFields(2, 4, 3, 5, 8), causal_seq=5003),
        rp.make_receipt("storm.aint", rp.PostureFields(1, 4, 0, 2, 8), causal_seq=5004),
        rp.make_receipt("jasper.aint", rp.PostureFields(1, 4, 3, 4, 8), causal_seq=5005,
                        transition_reason="rm -rf (dirname looked like working path)"),
    ]
    rec = rp.reconstruct_event(r, "jasper.aint", at_seq=5005)
    assert rec["incident"]["route_posture"] == "#14348"
    assert "storm.aint" in rec["witnesses"]      # lane-1: who was there
    assert any("controller" in b["actor"] for b in rec["before"])  # what was said before
    assert "no trust score" in rec["note"]
    assert set(rec["by_lane"]) >= {"who (R)", "what-evidence (A)", "where/how (T)"}
