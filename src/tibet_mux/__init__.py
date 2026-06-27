"""
tibet-mux: Single-port channel multiplexer with intent-based routing.

One TLS connection, infinite channels. Each channel is:
- Opened with an intent (chat, call:voice, call:video, vpn:tunnel, ...)
- Isolated from other channels (no cross-channel data leakage)
- Signed with TBZ per message (TIBET provenance on every frame)
- Routable via AINS resolve (services map → where to connect)

Architecture:
    Client ──TLS──→ :443 ──intent──→ Channel Registry ──→ Backend
                                                           ├─ I-Poll (chat)
                                                           ├─ Voice (call)
                                                           ├─ WebRTC (video)
                                                           ├─ overlay (vpn)
                                                           └─ any (custom)

Three security layers:
    1. TLS (transport)      — encryption in transit
    2. Channel isolation    — logical separation per intent
    3. TBZ signing          — every frame cryptographically signed

Usage:
    from tibet_mux import Mux, Channel

    # Create a mux instance
    mux = Mux(agent="root_idd")

    # Open a channel
    ch = mux.open(target="gemini", intent="chat")

    # Send data
    ch.send({"text": "Hello via tibet-mux!"})

    # Close
    ch.close()

    # Or use the server
    from tibet_mux.server import create_app
    app = create_app()  # FastAPI app with /api/mux/* endpoints

Part of the TIBET ecosystem — Traceable Intent-Based Event Tokens.
Part of the AInternet — The AI Network with .aint domains.
Born April 2026.
"""

__version__ = "1.1.0"
__all__ = [
    "Mux", "Channel", "Frame", "BandwidthGuard",
    "ChannelError", "ChannelThrottled",
    "Intent", "BandwidthPolicy", "INTENT_ROUTES", "BANDWIDTH_POLICIES",
    # v1.1.0 — the one verifier family (#109 contract)
    "VerifyDecision", "canonical_without", "sign_canonical", "verify_canonical",
    "verify_bytes", "verify_actor_challenge", "verify_ipoll_headers",
    "verify_mux_frame", "verify_relation", "verify_arena_probe", "vector_check",
]

from tibet_mux.core import Mux, Channel, Frame, BandwidthGuard, ChannelError, ChannelThrottled
from tibet_mux.intents import Intent, BandwidthPolicy, INTENT_ROUTES, BANDWIDTH_POLICIES
from tibet_mux.verify import (
    VerifyDecision, canonical_without, sign_canonical, verify_canonical, verify_bytes,
    verify_actor_challenge, verify_ipoll_headers, verify_mux_frame, verify_relation,
    verify_arena_probe, vector_check,
)
