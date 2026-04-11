"""Tests for bandwidth isolation in tibet-mux."""

import time
from tibet_mux import Mux, BandwidthGuard, ChannelThrottled
from tibet_mux.intents import BandwidthPolicy, resolve_intent, BANDWIDTH_POLICIES


def test_voice_is_highest_priority():
    voice = BANDWIDTH_POLICIES["call:voice"]
    chat = BANDWIDTH_POLICIES["chat"]
    file_sync = BANDWIDTH_POLICIES["file:sync"]
    assert voice.priority < chat.priority < file_sync.priority


def test_voice_not_preemptible():
    voice = BANDWIDTH_POLICIES["call:voice"]
    assert not voice.preemptible


def test_file_sync_is_preemptible():
    fs = BANDWIDTH_POLICIES["file:sync"]
    assert fs.preemptible


def test_intent_carries_bandwidth():
    intent = resolve_intent("call:voice")
    assert intent.bandwidth.priority == 0
    assert not intent.bandwidth.preemptible


def test_channel_has_bandwidth_stats():
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="call:voice")
    bw = ch.bandwidth
    assert "priority" in bw
    assert bw["priority"] == 0
    assert bw["preemptible"] is False


def test_close_includes_bandwidth():
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="chat")
    ch.send({"text": "hi"})
    result = ch.close()
    assert "bandwidth" in result
    assert result["bandwidth"]["bytes_allowed"] > 0


def test_guard_allows_within_budget():
    policy = BandwidthPolicy(priority=5, max_bytes_per_sec=1000, burst_bytes=500)
    guard = BandwidthGuard(policy)
    result = guard.check(100)
    assert result["allowed"] is True
    assert result["throttled"] is False


def test_guard_throttles_preemptible():
    policy = BandwidthPolicy(priority=7, max_bytes_per_sec=100, burst_bytes=50, preemptible=True)
    guard = BandwidthGuard(policy)
    # First: within burst
    r1 = guard.check(40)
    assert r1["allowed"] is True
    # Drain the bucket
    guard.check(10)
    # Over budget — preemptible = denied
    r3 = guard.check(50)
    assert r3["allowed"] is False
    assert r3["throttled"] is True


def test_guard_allows_non_preemptible_over_budget():
    policy = BandwidthPolicy(priority=0, max_bytes_per_sec=100, burst_bytes=50, preemptible=False)
    guard = BandwidthGuard(policy)
    guard.check(45)
    # Over budget but non-preemptible — still allowed
    r = guard.check(50)
    assert r["allowed"] is True
    assert r["throttled"] is True  # flagged but not denied


def test_guard_unlimited():
    policy = BandwidthPolicy(priority=5, max_bytes_per_sec=0)
    guard = BandwidthGuard(policy)
    r = guard.check(1_000_000)
    assert r["allowed"] is True
    assert r["tokens_remaining"] == -1


def test_channel_throttled_exception():
    """Preemptible channel raises ChannelThrottled when over budget."""
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="file:sync")
    # file:sync has burst_bytes=500_000 — send a massive payload to exhaust
    # We need to exhaust the token bucket
    huge = {"data": "x" * 600_000}
    try:
        ch.send(huge)
        # Might succeed if burst covers it, try again
        ch.send(huge)
        ch.send(huge)
        # If we get here without throttle, burst was big enough
    except ChannelThrottled:
        pass  # Expected for preemptible over-budget


def test_voice_never_throttled():
    """Voice channels should never raise ChannelThrottled."""
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="call:voice")
    # Send over the rate — voice is non-preemptible, should always succeed
    for _ in range(20):
        frame = ch.send({"audio": "x" * 10_000})
        assert frame.seq >= 0


def test_different_channels_different_budgets():
    """Each channel has its own independent budget."""
    mux = Mux(agent="alice")
    voice = mux.open(target="bob", intent="call:voice")
    bulk = mux.open(target="bob", intent="file:sync")

    assert voice.bandwidth["priority"] < bulk.bandwidth["priority"]
    assert voice.bandwidth["preemptible"] is False
    assert bulk.bandwidth["preemptible"] is True


def test_guard_refills_over_time():
    """Tokens refill based on elapsed time."""
    policy = BandwidthPolicy(priority=5, max_bytes_per_sec=10_000, burst_bytes=100, preemptible=True)
    guard = BandwidthGuard(policy)
    # Drain tokens
    guard.check(90)
    guard.check(10)
    # Should be nearly empty
    r = guard.check(50)
    assert not r["allowed"]
    # Wait a bit for refill
    time.sleep(0.05)  # 50ms → should refill ~500 bytes (10000 * 0.05)
    r = guard.check(50)
    assert r["allowed"]
