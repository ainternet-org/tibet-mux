"""
Intent definitions, routing table, and bandwidth policies.

An intent is a semantic label for what kind of communication a channel carries.
Known intents map to specific backends; unknown intents are still accepted
and routed to a generic stream handler.

Each intent has a bandwidth policy:
- priority: 0 (highest) to 9 (lowest) — real-time > messaging > bulk
- max_bytes_per_sec: soft cap per channel (0 = unlimited)
- burst_bytes: how much can spike above the rate
- preemptible: can this channel be throttled to protect higher-priority?
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BandwidthPolicy:
    """Per-intent bandwidth allocation rules."""
    priority: int = 5              # 0=highest (voice), 9=lowest (bulk sync)
    max_bytes_per_sec: int = 0     # 0 = no limit
    burst_bytes: int = 0           # allowed burst above rate
    preemptible: bool = True       # can be throttled for higher-priority

    @property
    def is_realtime(self) -> bool:
        return self.priority <= 2

    @property
    def is_unlimited(self) -> bool:
        return self.max_bytes_per_sec == 0


# ─── Default Bandwidth Policies ────────────────────────────────────────────
# Priority tiers:
#   0-1: Critical real-time (voice, video) — never throttled
#   2-3: Interactive (chat, ping) — low latency preferred
#   4-5: Standard (tasks, sync, sessions) — fair share
#   6-7: Bulk (file sync, mail) — can be throttled
#   8-9: Background (VPN tunnel, stream) — best effort

BANDWIDTH_POLICIES: dict[str, BandwidthPolicy] = {
    "call:voice":  BandwidthPolicy(priority=0, max_bytes_per_sec=128_000,  burst_bytes=32_000,    preemptible=False),
    "call:video":  BandwidthPolicy(priority=1, max_bytes_per_sec=2_000_000, burst_bytes=500_000,   preemptible=False),
    "tibet:ping":  BandwidthPolicy(priority=2, max_bytes_per_sec=10_000,   burst_bytes=5_000,     preemptible=False),
    "chat":        BandwidthPolicy(priority=3, max_bytes_per_sec=50_000,   burst_bytes=20_000,    preemptible=False),
    "push":        BandwidthPolicy(priority=3, max_bytes_per_sec=50_000,   burst_bytes=20_000,    preemptible=False),
    "task":        BandwidthPolicy(priority=4, max_bytes_per_sec=100_000,  burst_bytes=50_000,    preemptible=True),
    "sync":        BandwidthPolicy(priority=4, max_bytes_per_sec=200_000,  burst_bytes=100_000,   preemptible=True),
    "session":     BandwidthPolicy(priority=5, max_bytes_per_sec=500_000,  burst_bytes=200_000,   preemptible=True),
    "tibet:token": BandwidthPolicy(priority=5, max_bytes_per_sec=50_000,   burst_bytes=20_000,    preemptible=True),
    "mail":        BandwidthPolicy(priority=6, max_bytes_per_sec=500_000,  burst_bytes=200_000,   preemptible=True),
    "file:sync":   BandwidthPolicy(priority=7, max_bytes_per_sec=1_000_000, burst_bytes=500_000,   preemptible=True),
    "vpn:tunnel":  BandwidthPolicy(priority=8, max_bytes_per_sec=0,        burst_bytes=0,         preemptible=True),
    "stream":      BandwidthPolicy(priority=8, max_bytes_per_sec=0,        burst_bytes=0,         preemptible=True),
}

# Default for unknown intents
DEFAULT_POLICY = BandwidthPolicy(priority=5, max_bytes_per_sec=200_000, burst_bytes=100_000, preemptible=True)


@dataclass
class Intent:
    """A resolved intent with backend routing info and bandwidth policy."""
    name: str
    backend: str
    description: str
    parent: Optional[str] = None
    bandwidth: BandwidthPolicy = field(default_factory=lambda: DEFAULT_POLICY)

    @property
    def parts(self) -> list[str]:
        return self.name.split(":")

    @property
    def is_realtime(self) -> bool:
        return self.bandwidth.priority <= 2

    @property
    def is_messaging(self) -> bool:
        return self.backend in ("ipoll", "mail")


# ─── Built-in Intent Routes ────────────────────────────────────────────────
# Maps intent string → (backend, description)
# Extensible: register custom intents via Mux.register_intent()

INTENT_ROUTES: dict[str, dict] = {
    # Messaging
    "chat":        {"backend": "ipoll",   "description": "Text messaging via I-Poll"},
    "mail":        {"backend": "mail",    "description": "Email delivery"},
    "push":        {"backend": "ipoll",   "description": "Push notification"},
    "task":        {"backend": "ipoll",   "description": "Task assignment via I-Poll"},
    "sync":        {"backend": "ipoll",   "description": "State synchronization via I-Poll"},

    # Real-time
    "call:voice":  {"backend": "voice",   "description": "Voice call via Voice Pipeline / SIP"},
    "call:video":  {"backend": "webrtc",  "description": "Video call via WebRTC"},
    "stream":      {"backend": "stream",  "description": "Generic data stream"},

    # Infrastructure
    "vpn:tunnel":  {"backend": "overlay", "description": "VPN tunnel via tibet-overlay"},
    "file:sync":   {"backend": "sync",    "description": "File synchronization"},
    "session":     {"backend": "phantom", "description": "Phantom session resume/fork"},

    # TIBET
    "tibet:ping":  {"backend": "tping",   "description": "Identity-based ping"},
    "tibet:token": {"backend": "tibet",   "description": "TIBET token operations"},
}


def get_bandwidth_policy(intent_str: str) -> BandwidthPolicy:
    """Get bandwidth policy for an intent. Falls back to default."""
    if intent_str in BANDWIDTH_POLICIES:
        return BANDWIDTH_POLICIES[intent_str]
    # Prefix match
    parts = intent_str.split(":")
    while parts:
        key = ":".join(parts)
        if key in BANDWIDTH_POLICIES:
            return BANDWIDTH_POLICIES[key]
        parts.pop()
    return DEFAULT_POLICY


def resolve_intent(intent_str: str) -> Intent:
    """
    Resolve an intent string to its backend route + bandwidth policy.

    Supports exact match and prefix matching:
        "chat"           → exact match
        "call:voice"     → exact match
        "call:voice:opus" → prefix match to "call:voice"
        "custom:thing"   → generic fallback

    Args:
        intent_str: The intent string (e.g. "chat", "call:voice")

    Returns:
        Intent with backend routing info
    """
    bw = get_bandwidth_policy(intent_str)

    # Exact match
    if intent_str in INTENT_ROUTES:
        route = INTENT_ROUTES[intent_str]
        return Intent(
            name=intent_str,
            backend=route["backend"],
            description=route["description"],
            bandwidth=bw,
        )

    # Prefix match (e.g. "call:voice:opus" → "call:voice")
    parts = intent_str.split(":")
    while parts:
        key = ":".join(parts)
        if key in INTENT_ROUTES:
            route = INTENT_ROUTES[key]
            return Intent(
                name=intent_str,
                backend=route["backend"],
                description=route["description"],
                parent=key,
                bandwidth=bw,
            )
        parts.pop()

    # Unknown intent → generic stream
    return Intent(
        name=intent_str,
        backend="generic",
        description=f"Custom intent: {intent_str}",
        bandwidth=bw,
    )
