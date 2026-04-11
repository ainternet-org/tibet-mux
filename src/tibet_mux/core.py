"""
Core mux engine — channel management, frame signing, lifecycle.

This module is pure Python with zero dependencies.
The server module (FastAPI) and client module (httpx) are optional.
"""

import json
import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Callable
from collections import defaultdict

from tibet_mux.intents import Intent, BandwidthPolicy, resolve_intent, INTENT_ROUTES


class BandwidthGuard:
    """
    Token bucket rate limiter per channel.

    Enforces bandwidth policies:
    - Real-time channels (voice/video): never throttled, priority 0-1
    - Interactive (chat/ping): soft limit, not preemptible
    - Bulk (file sync, VPN): can be throttled to protect real-time

    Uses a token bucket algorithm:
    - Tokens refill at max_bytes_per_sec rate
    - Burst allows temporary spikes up to burst_bytes
    - When tokens run out → frame is marked as throttled (not dropped)
    """

    def __init__(self, policy: BandwidthPolicy):
        self.policy = policy
        self._tokens: float = float(policy.burst_bytes or policy.max_bytes_per_sec or 1_000_000)
        self._max_tokens: float = float(policy.burst_bytes or policy.max_bytes_per_sec or 1_000_000)
        self._last_refill: float = time.monotonic()
        self.bytes_allowed: int = 0
        self.bytes_throttled: int = 0
        self.frames_throttled: int = 0

    def check(self, payload_size: int) -> dict:
        """
        Check if a frame can pass through.

        Returns:
            {"allowed": True/False, "throttled": True/False, "tokens_remaining": N}
        """
        if self.policy.is_unlimited:
            self.bytes_allowed += payload_size
            return {"allowed": True, "throttled": False, "tokens_remaining": -1}

        self._refill()

        if self._tokens >= payload_size:
            self._tokens -= payload_size
            self.bytes_allowed += payload_size
            return {
                "allowed": True,
                "throttled": False,
                "tokens_remaining": int(self._tokens),
            }

        # Over budget
        self.bytes_throttled += payload_size
        self.frames_throttled += 1

        if not self.policy.preemptible:
            # Non-preemptible: allow anyway but log it
            self._tokens = max(0, self._tokens - payload_size)
            self.bytes_allowed += payload_size
            return {
                "allowed": True,
                "throttled": True,
                "tokens_remaining": int(self._tokens),
            }

        # Preemptible: deny the frame
        return {
            "allowed": False,
            "throttled": True,
            "tokens_remaining": int(self._tokens),
        }

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        refill = elapsed * self.policy.max_bytes_per_sec
        self._tokens = min(self._max_tokens, self._tokens + refill)

    @property
    def stats(self) -> dict:
        return {
            "priority": self.policy.priority,
            "max_bytes_per_sec": self.policy.max_bytes_per_sec,
            "burst_bytes": self.policy.burst_bytes,
            "preemptible": self.policy.preemptible,
            "bytes_allowed": self.bytes_allowed,
            "bytes_throttled": self.bytes_throttled,
            "frames_throttled": self.frames_throttled,
            "tokens_remaining": int(self._tokens),
        }


@dataclass
class Frame:
    """A single data frame on a channel."""
    seq: int
    payload: Any
    timestamp: str
    tbz_hash: str
    intent: str
    channel_id: str = ""

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "tbz_hash": self.tbz_hash,
            "intent": self.intent,
            "channel_id": self.channel_id,
        }


@dataclass
class Channel:
    """
    A multiplexed channel between two agents.

    Each channel has:
    - A unique ID
    - An intent (what kind of data flows through)
    - A TBZ provenance chain (every frame is signed)
    - Isolation from other channels
    """
    id: str
    agent: str
    target: str
    intent: str
    resolved_intent: Intent
    state: str = "open"
    metadata: dict = field(default_factory=dict)
    opened_at: str = ""
    closed_at: str = ""
    close_reason: str = ""
    last_activity: str = ""
    frames_sent: int = 0
    frames_received: int = 0
    bytes_transferred: int = 0
    tbz_chain: list[str] = field(default_factory=list)
    _frame_log: list[Frame] = field(default_factory=list, repr=False)
    _on_send: Optional[Callable] = field(default=None, repr=False)
    _bw_guard: Optional[BandwidthGuard] = field(default=None, repr=False)

    def __post_init__(self):
        now = _now()
        if not self.opened_at:
            self.opened_at = now
        if not self.last_activity:
            self.last_activity = now
        # Initial TBZ hash for channel open event
        if not self.tbz_chain:
            self.tbz_chain.append(
                _tbz_hash(self.id, {"event": "open", "intent": self.intent})
            )
        # Initialize bandwidth guard from intent policy
        if self._bw_guard is None:
            self._bw_guard = BandwidthGuard(self.resolved_intent.bandwidth)

    @property
    def bandwidth(self) -> dict:
        """Current bandwidth stats for this channel."""
        return self._bw_guard.stats if self._bw_guard else {}

    def send(self, payload: Any) -> Frame:
        """Send a frame on this channel. Returns the Frame with TBZ hash."""
        if self.state != "open":
            raise ChannelError(f"Channel {self.id} is {self.state}, not open")

        payload_size = len(json.dumps(payload, default=str))

        # Bandwidth check
        if self._bw_guard:
            bw_result = self._bw_guard.check(payload_size)
            if not bw_result["allowed"]:
                raise ChannelThrottled(
                    f"Channel {self.id} throttled (intent={self.intent}, "
                    f"priority={self._bw_guard.policy.priority})"
                )

        frame_hash = _tbz_hash(self.id, payload)
        frame = Frame(
            seq=self.frames_sent,
            payload=payload,
            timestamp=_now(),
            tbz_hash=frame_hash,
            intent=self.intent,
            channel_id=self.id,
        )

        self.frames_sent += 1
        self.bytes_transferred += payload_size
        self.last_activity = frame.timestamp
        self.tbz_chain.append(frame_hash)

        # Keep recent frames (max 100)
        self._frame_log.append(frame)
        if len(self._frame_log) > 100:
            self._frame_log = self._frame_log[-100:]

        # Callback for server integration
        if self._on_send:
            self._on_send(frame)

        return frame

    def receive(self, payload: Any) -> Frame:
        """Record a received frame."""
        frame_hash = _tbz_hash(self.id, payload)
        frame = Frame(
            seq=self.frames_received,
            payload=payload,
            timestamp=_now(),
            tbz_hash=frame_hash,
            intent=self.intent,
            channel_id=self.id,
        )

        self.frames_received += 1
        self.bytes_transferred += len(json.dumps(payload, default=str))
        self.last_activity = frame.timestamp
        self.tbz_chain.append(frame_hash)
        self._frame_log.append(frame)

        return frame

    def close(self, reason: str = "client_close") -> dict:
        """Close this channel."""
        self.state = "closed"
        self.closed_at = _now()
        self.close_reason = reason
        close_hash = _tbz_hash(self.id, {"event": "close", "reason": reason})
        self.tbz_chain.append(close_hash)

        return {
            "channel_id": self.id,
            "state": "closed",
            "reason": reason,
            "duration_frames": self.frames_sent + self.frames_received,
            "bytes_transferred": self.bytes_transferred,
            "tbz_chain_length": len(self.tbz_chain),
            "bandwidth": self.bandwidth,
        }

    @property
    def recent_frames(self) -> list[dict]:
        return [f.to_dict() for f in self._frame_log[-10:]]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent": self.agent,
            "target": self.target,
            "intent": self.intent,
            "route": {
                "backend": self.resolved_intent.backend,
                "description": self.resolved_intent.description,
            },
            "state": self.state,
            "metadata": self.metadata,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "last_activity": self.last_activity,
            "frames_sent": self.frames_sent,
            "frames_received": self.frames_received,
            "bytes_transferred": self.bytes_transferred,
            "tbz_chain": self.tbz_chain,
            "bandwidth": self.bandwidth,
        }


class ChannelError(Exception):
    """Raised when a channel operation fails."""
    pass


class ChannelThrottled(ChannelError):
    """Raised when a frame exceeds the channel's bandwidth policy."""
    pass


class Mux:
    """
    Channel multiplexer — the core engine.

    Manages channel lifecycle, routing, and TBZ signing.
    Can be used standalone (library mode) or with the server module.

    Usage:
        mux = Mux(agent="root_idd")
        ch = mux.open(target="gemini", intent="chat")
        frame = ch.send({"text": "Hello!"})
        ch.close()
    """

    MAX_CHANNELS_PER_AGENT = 32

    def __init__(self, agent: str, max_channels: int = 32):
        self.agent = _normalize(agent)
        self.max_channels = max_channels
        self._channels: dict[str, Channel] = {}
        self._agent_channels: dict[str, list[str]] = defaultdict(list)
        self._custom_intents: dict[str, dict] = {}
        self._stats = {
            "channels_opened": 0,
            "channels_closed": 0,
            "messages_routed": 0,
            "bytes_transferred": 0,
            "started": _now(),
        }

    def open(
        self,
        target: str,
        intent: str,
        metadata: dict | None = None,
        agent: str | None = None,
    ) -> Channel:
        """
        Open a new channel.

        Args:
            target: Target agent (.aint domain or bare name)
            intent: Intent string (e.g. "chat", "call:voice")
            metadata: Optional intent-specific params
            agent: Override source agent (for multi-agent mux)

        Returns:
            Channel object ready for send/receive
        """
        src = _normalize(agent or self.agent)
        tgt = _normalize(target)

        # Rate limit
        open_count = sum(
            1 for cid in self._agent_channels[src]
            if self._channels.get(cid, Channel(
                id="", agent="", target="", intent="",
                resolved_intent=resolve_intent(""), state="closed"
            )).state == "open"
        )
        if open_count >= self.max_channels:
            raise ChannelError(f"Max {self.max_channels} open channels per agent")

        # Resolve intent
        resolved = self._resolve(intent)

        # Generate channel ID
        channel_id = _channel_id(src, tgt, intent)

        channel = Channel(
            id=channel_id,
            agent=src,
            target=tgt,
            intent=intent,
            resolved_intent=resolved,
            metadata=metadata or {},
        )

        self._channels[channel_id] = channel
        self._agent_channels[src].append(channel_id)
        self._stats["channels_opened"] += 1

        return channel

    def get(self, channel_id: str) -> Channel | None:
        """Get a channel by ID."""
        return self._channels.get(channel_id)

    def close(self, channel_id: str, reason: str = "client_close") -> dict:
        """Close a channel by ID."""
        ch = self._channels.get(channel_id)
        if not ch:
            raise ChannelError(f"Channel {channel_id} not found")

        result = ch.close(reason)

        agent = ch.agent
        if channel_id in self._agent_channels[agent]:
            self._agent_channels[agent].remove(channel_id)

        self._stats["channels_closed"] += 1
        return result

    def channels(self, agent: str | None = None) -> list[Channel]:
        """List open channels for an agent."""
        agent = _normalize(agent or self.agent)
        result = []
        for cid in self._agent_channels.get(agent, []):
            ch = self._channels.get(cid)
            if ch and ch.state == "open":
                result.append(ch)
        return result

    def register_intent(self, name: str, backend: str, description: str):
        """Register a custom intent route."""
        self._custom_intents[name] = {
            "backend": backend,
            "description": description,
        }

    def intents(self) -> dict[str, dict]:
        """All known intents (built-in + custom)."""
        return {**INTENT_ROUTES, **self._custom_intents}

    def status(self) -> dict:
        """Mux health and statistics."""
        active = sum(1 for ch in self._channels.values() if ch.state == "open")
        total_bytes = sum(ch.bytes_transferred for ch in self._channels.values())
        total_frames = sum(ch.frames_sent + ch.frames_received for ch in self._channels.values())

        return {
            "status": "operational",
            "version": "1.0.0",
            "agent": self.agent,
            "channels": {
                "active": active,
                "total_opened": self._stats["channels_opened"],
                "total_closed": self._stats["channels_closed"],
            },
            "messages_routed": total_frames,
            "bytes_transferred": total_bytes,
            "known_intents": len(self.intents()),
            "uptime_since": self._stats["started"],
            "security": {
                "transport": "TLS 1.3",
                "isolation": "channel-segmented",
                "signing": "TBZ (TIBET provenance per frame)",
            },
        }

    def _resolve(self, intent_str: str) -> Intent:
        """Resolve intent, checking custom intents first."""
        if intent_str in self._custom_intents:
            route = self._custom_intents[intent_str]
            return Intent(
                name=intent_str,
                backend=route["backend"],
                description=route["description"],
            )
        return resolve_intent(intent_str)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Strip .aint suffix for internal use."""
    return name.replace(".aint", "").strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _channel_id(agent: str, target: str, intent: str) -> str:
    seed = f"{agent}:{target}:{intent}:{time.time_ns()}"
    return f"ch-{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


def _tbz_hash(channel_id: str, payload: Any) -> str:
    raw = json.dumps(
        {"ch": channel_id, "payload": payload, "t": time.time_ns()},
        default=str, sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
