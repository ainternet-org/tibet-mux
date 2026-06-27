"""Carrier policy (upper grammar). Design: codex.aint; build: root_idd.

Covers codex's 'conformance vectors to add later' from the v0 grammar note.
The route number proves posture; orchestration chooses the carrier.
"""
import pytest

from tibet_mux import route_posture as rp
from tibet_mux import carrier_policy as cp


def _num(R, C, T, A, M):
    return rp.encode_posture(rp.PostureFields(R, C, T, A, M))


def test_p0_any_payload_dark_route():
    for payload in ("control", "hot_transfer", "session_diff", "evidence"):
        d = cp.choose_carrier(rp.DARK, payload)
        assert d.decision == "dark"
        assert d.carrier == "dark_route"
        assert d.lane_skipping is False


def test_a2_hot_transfer_never_hot_path():
    # A2 mirrored = observed band P2; hot_transfer is request-only, no hot path.
    d = cp.choose_carrier(_num(2, 4, 3, 2, 8), "hot_transfer", has_receipt=True)
    assert d.band == "P2"
    assert d.carrier != "gpu_mailbox_capsule"
    assert d.lane_skipping is False


def test_a5_t3_m8_hot_transfer_gpu_mailbox_allowed():
    d = cp.choose_carrier(_num(2, 4, 3, 5, 8), "hot_transfer",
                          has_receipt=True, causal_seq=8201)
    assert d.band == "P4"
    assert d.carrier == "gpu_mailbox_capsule"
    assert d.lane_skipping is True
    assert d.receipt_required is True


def test_p3_session_diff_phantom_diff_merge():
    # P3 (A4, M8, C3) but not P4 (A<5).
    d = cp.choose_carrier(_num(2, 3, 2, 4, 8), "session_diff", has_receipt=True)
    assert d.band == "P3"
    assert d.carrier == "phantom.diff_merge"


def test_upip_slot_expired_triage_or_dark():
    d = cp.choose_carrier(_num(2, 4, 3, 5, 8), "process_instruction",
                          slot_valid=False, has_receipt=True)
    assert d.decision == "triage"
    assert "slot missed" in d.reason


def test_lane_skip_without_receipt_invalid():
    d = cp.choose_carrier(_num(2, 4, 3, 5, 8), "control", has_receipt=False)
    assert d.lane_skipping is False  # no receipt, no skip
    # the carrier still opens, just without skipping
    assert d.carrier == "cap_bus.event"


def test_capsule_observed_below_required_hold():
    d = cp.choose_carrier(_num(2, 4, 3, 2, 8), "session_diff",
                          required_posture=_num(2, 4, 3, 5, 8))
    assert d.decision == "hold"
    assert d.carrier == "cmail.capsule"


def test_continuityd_overflow_m7_is_triage_band():
    # M7 = exception posture -> band P1 (triage-only).
    d = cp.choose_carrier(_num(2, 4, 3, 5, 7), "control")
    assert d.band == "P1"
    assert d.decision in ("allow", "triage")
    assert d.lane_skipping is False


def test_does_not_extend_rctam():
    # The policy READS the five digits; it never adds a sixth.
    f = rp.PostureFields(2, 4, 3, 5, 8)
    before = rp.encode_posture(f)
    cp.choose_carrier(before, "hot_transfer", has_receipt=True)
    assert rp.encode_posture(f) == before  # unchanged
    assert len(before.lstrip("#")) == 5


def test_lane_skip_rule_needs_full_posture():
    f = rp.PostureFields(2, 4, 3, 5, 8)
    assert cp.lane_skip_allowed(f, has_receipt=True) is True
    assert cp.lane_skip_allowed(f, has_receipt=False) is False
    assert cp.lane_skip_allowed(f, has_receipt=True, relation_active=False) is False
    weak = rp.PostureFields(2, 3, 3, 5, 8)  # C<4
    assert cp.lane_skip_allowed(weak, has_receipt=True) is False
