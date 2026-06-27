"""Workload split — 85% here, the rest elsewhere. Realization: jasper."""
import pytest
from tibet_mux import workload_split as ws


def test_85_10_5_split():
    plan = ws.plan_split(100, [
        ws.Target("local", "local", capacity_units=85),
        ws.Target("ollama@p520", "ollama", capacity_units=10),
        ws.Target("anthropic", "anthropic", capacity_units=None),  # unbounded
    ])
    assert plan["fully_covered"] is True
    fr = {a["target"]: round(a["fraction"] * 100) for a in plan["assignments"]}
    assert fr == {"local": 85, "ollama@p520": 10, "anthropic": 5}


def test_overflow_cascades_ollama_to_gpu_cloud():
    # Ollama caps at 10, the GPU cloud takes the spill before Anthropic.
    plan = ws.plan_split(100, [
        ws.Target("local", "local", capacity_units=80),
        ws.Target("ollama@p520", "ollama", capacity_units=10),
        ws.Target("gpucloud-x", "gpu_cloud", capacity_units=100, cost_per_unit=0.02),
        ws.Target("anthropic", "anthropic"),
    ])
    targets = [a["target"] for a in plan["assignments"]]
    assert targets == ["local", "ollama@p520", "gpucloud-x"]
    assert plan["fully_covered"] is True
    assert plan["total_cost"] > 0  # the cloud share has a price


def test_target_that_cannot_carry_is_skipped():
    plan = ws.plan_split(50, [
        ws.Target("local", "local", capacity_units=20, can_carry=True),
        ws.Target("peer", "peer", capacity_units=100, can_carry=False),  # can't carry route
        ws.Target("anthropic", "anthropic"),
    ])
    targets = [a["target"] for a in plan["assignments"]]
    assert "peer" not in targets
    assert any("peer" in s for s in plan["skipped"])
    assert plan["fully_covered"] is True  # anthropic absorbs the rest


def test_uncovered_when_capacity_insufficient():
    plan = ws.plan_split(100, [ws.Target("local", "local", capacity_units=30)])
    assert plan["fully_covered"] is False
    assert plan["uncovered"] == 70
    assert "UNCOVERED" in ws.describe(plan)


def test_dark_route_assigns_nothing():
    plan = ws.plan_split(100, [ws.Target("local", "local")], route_posture=ws.rp.DARK)
    assert plan["assignments"] == []
    assert plan["uncovered"] == 100
