# tibet-mux

**Single-port channel multiplexer with intent-based routing, route posture and TBZ signing.**

One TLS connection. Infinite channels. Chat, voice, video, VPN, file sync — all through port 443.

```
Client ──TLS 1.3──> :443 ──intent──> ┌─ chat       (I-Poll)
                                      ├─ call:voice (SIP/Voice)
                                      ├─ call:video (WebRTC)
                                      ├─ vpn:tunnel (tibet-overlay)
                                      ├─ file:sync  (sync backend)
                                      ├─ session    (Phantom)
                                      └─ custom:*   (anything)
```

## Why

Traditional networking: one port per service. SIP on 5060, STUN on 3478, HTTPS on 443, WireGuard on 51820. Firewalls, NAT, corporate proxies — every device configured differently.

tibet-mux: **one TLS connection, intent routes everything**. Port 443 is open everywhere. Every firewall, every network, every device.

For AInternet, MUX also carries a stricter rule:

```text
Do not score the actor.
Number the proven route.
```

An AI runtime is often temporary. A key binds, a consent relation opens, a route
materializes over a specific machine lane, and the window closes again. That is
not a stable "trust score". It is a route posture: `#RCTAM`.

```text
#54359
│││││
││││└─ MUX: verified partituur
│││└── Audit: sign-ahead
││└─── Lane: scheduler-free cadence
│└──── Consent: active parent relation
└───── Family: composite actor (.caint)
```

## Route Posture Algebra

Route postures compose as a meet: per-digit minimum. A path is only as strong as
the weakest proven hop.

```python
from tibet_mux import posture_algebra as pa

pa.compose("#23856", "#12093", "#88347")
# "#12043"
```

This is not addition and not scoring. If any hop is dark, the whole path is dark:

```python
pa.compose("#54359", "#00000", "#54359")
# "#00000"
```

You can smoke-test a declared route by folding the observed hops:

```python
r = pa.verify_tree(["#24358", "#24258", "#24359"], expected="#24358")
print(r.ok)       # False
print(r.weakest)  # T timing-lane: declared 3, observed 2 (weaker)
```

## Bifurcated Airlock

Some lanes claim reproducible compute, not just reachability. `tibet-mux` 1.3
ships a small bifurcated airlock primitive: run two cells with the same attested
compute semantics and pass only if the output bytes match.

FMA3 is the useful edge case. Fused multiply-add uses one rounding; separate
multiply plus add uses two. Both can be legitimate, but they are different
planes. The airlock compares bytes, not "close enough".

```python
from tibet_mux import bifurcated_airlock as airlock
from tibet_mux import cpu_capability

receipt = cpu_capability.cpu_capability_receipt()
cell_a = airlock.Cell("a", receipt)
cell_b = airlock.Cell("b", receipt)

verdict = airlock.run_bifurcated(
    airlock.fused_accumulate,
    ([(1e16, 1.0000000000000002), (-1e16, 1.0)],),
    cell_a,
    cell_b,
)

print(verdict.passed)
print(verdict.reason)
```

The route number proves the route. Machine posture proves which routes this box
may carry. Airlock proves the claimed compute lane byte-for-byte.

## Three Security Layers

| Layer | What it does |
|-------|-------------|
| **TLS 1.3** | Transport encryption — nobody sees what flows through |
| **Channel isolation** | Logical separation per intent — voice can't access file:sync |
| **TBZ signing** | Every frame cryptographically signed with TIBET provenance |

## Install

```bash
# Core library (zero dependencies)
pip install tibet-mux

# With server (FastAPI + uvicorn)
pip install tibet-mux[server]

# Full (server + tibet-core integration)
pip install tibet-mux[full]
```

## Quick Start — Library

```python
from tibet_mux import Mux

# Create a mux
mux = Mux(agent="my_agent")

# Open a chat channel
ch = mux.open(target="gemini", intent="chat")
print(ch.id)  # ch-a1b2c3...

# Send a message (TBZ-signed automatically)
frame = ch.send({"text": "Hello via tibet-mux!"})
print(frame.tbz_hash)  # cryptographic hash of this frame

# Open a voice channel on the same mux
voice = mux.open(target="vandemeent", intent="call:voice",
                 metadata={"codec": "opus", "samplerate": 48000})

# Channels are isolated — voice data stays on voice channel
voice.send({"type": "sdp-offer", "sdp": "v=0..."})

# Close channels
ch.close()
voice.close(reason="call_ended")

# Check stats
print(mux.status())
```

## Quick Start — Server

```bash
# Standalone
tibet-mux serve --port 8443 --agent my_node

# Or mount on existing FastAPI app
```

```python
from fastapi import FastAPI
from tibet_mux.server import create_router

app = FastAPI()
app.include_router(create_router())
# Adds: /api/mux/open, /api/mux/send, /api/mux/close,
#        /api/mux/channels, /api/mux/intents, /api/mux/status,
#        /api/mux/ws (WebSocket)
```

## Quick Start — Client

```python
from tibet_mux.client import MuxClient

client = MuxClient("https://api.ainternet.org", agent="my_agent")

# Open channel
ch = client.open(target="gemini", intent="chat")

# Send
client.send(ch["channel_id"], {"text": "Hello!"})

# List channels
print(client.channels())

# Close
client.close(ch["channel_id"])
```

## CLI

```bash
# Server
tibet-mux serve --port 8443 --agent my_node

# Status
tibet-mux status --url http://localhost:8000

# List intents
tibet-mux intents

# Open/send/close
tibet-mux open --agent me --target them --intent chat
tibet-mux send --channel ch-xxx --payload '{"text":"hi"}'
tibet-mux close --channel ch-xxx
```

## WebSocket Multiplexing

One WebSocket, many channels:

```javascript
const ws = new WebSocket("wss://api.ainternet.org/api/mux/ws?agent=my_agent");

// Open multiple channels on one connection
ws.send(JSON.stringify({
    action: "open", target: "gemini", intent: "chat"
}));
ws.send(JSON.stringify({
    action: "open", target: "vandemeent", intent: "call:voice",
    metadata: { codec: "opus" }
}));

// Send on any channel
ws.send(JSON.stringify({
    action: "send", channel_id: "ch-xxx",
    payload: { text: "Hello!" }
}));

// Receive
ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    // msg.event: "channel_opened", "frame_ack", "channel_closed"
    // msg.channel_id: which channel this belongs to
};
```

## Built-in Intents

| Intent | Backend | Description |
|--------|---------|------------|
| `chat` | ipoll | Text messaging |
| `call:voice` | voice | Voice call (SIP/Voice Pipeline) |
| `call:video` | webrtc | Video call |
| `vpn:tunnel` | overlay | VPN via tibet-overlay |
| `file:sync` | sync | File synchronization |
| `session` | phantom | Phantom session resume/fork |
| `tibet:ping` | tping | Identity-based ping |
| `tibet:token` | tibet | TIBET token operations |
| `mail` | mail | Email delivery |
| `task` | ipoll | Task assignment |
| `sync` | ipoll | State synchronization |
| `stream` | stream | Generic data stream |
| `push` | ipoll | Push notification |

Custom intents are always accepted — unknown intents route to a generic stream backend.

```python
# Register custom intent
mux.register_intent("iot:sensor", backend="mqtt", description="IoT sensor data")
```

## Works Everywhere

- **Browsers:** WebSocket or fetch — no plugins needed
- **Smartphones:** One HTTPS connection — battery friendly
- **Smartwatches (tlex-edge):** Minimal footprint, one socket
- **IoT:** Lightweight intent routing over TLS
- **VPN:** `intent:"vpn:tunnel"` — no separate app needed

## Part of the AInternet Ecosystem

tibet-mux works with:
- **AINS** — resolve `.aint` domains to find mux endpoints
- **I-Poll** — messaging backend for chat/task/push intents
- **TIBET** — provenance tokens, TBZ signing
- **Phantom** — session resume via `session` intent
- **tibet-overlay** — NAT traversal for `vpn:tunnel` intent
- **tibet-ping** — identity pings via `tibet:ping` intent

## License

MIT — J. van de Meent & R. AI @ Humotica


## Credits

Designed by [Jasper van de Meent](https://github.com/jaspertvdm). Built by Jasper and [Root AI](https://humotica.com) as part of [HumoticaOS](https://humotica.com).

---

**Stack-positie:** Groep `agentic` · Bootstrap = OSAPI-handshake naar [`tibet`](https://pypi.org/project/tibet-core/) + [`jis`](https://pypi.org/project/jis-core/) (fail → snaft-rule + tibet-pol-rapport) · ← [`ainternet`](https://pypi.org/project/ainternet/) · See `STACK.md` · See `demo/golden-path/` for the spine end-to-end.
---

## Enterprise

For private hub hosting, SLA support, custom integrations, or compliance guidance:

| | |
|---|---|
| **Enterprise** | enterprise@humotica.com |
| **Support** | support@humotica.com |
| **Security** | security@humotica.com |

See [ENTERPRISE.md](ENTERPRISE.md) for details.
