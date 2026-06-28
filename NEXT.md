# tibet-mux — Volgende stap: Overlay MUX sync + QUIC transport

## Wat er is (Python, dit package)

tibet-mux v1.0.0 heeft:
- Intent-based routing: 12 built-in intents (chat, call:voice, call:video, etc.)
- BandwidthPolicy per intent (priority 0-9, rate limiting, burst)
- Channel isolation + TBZ signing per frame
- Server mode (FastAPI) + Client mode
- WebSocket transport

## Wat er is (Rust, trust-kernel)

`overlay_mux.rs` in tibet-trust-kernel implementeert dezelfde concepten in Rust
met QUIC transport. **Bewezen**: 1.7ms per intent, 3ms voor 3 parallel.

StreamIntent types in Rust:
```
Chat, Voice, Video, File, LlmSync, Control, Finance, Industrial, Custom(String)
```

## Wat er moet komen

### 1. Intent synchronisatie

De Python intents (intents.py) en Rust StreamIntent moeten 1:1 mappen.

| Python (tibet-mux) | Rust (overlay_mux) | Status |
|---------------------|---------------------|--------|
| `chat` | `Chat` | ✅ match |
| `call:voice` | `Voice` | ⚠️ naam verschil |
| `call:video` | `Video` | ⚠️ naam verschil |
| `file:sync` | `File` | ⚠️ naam verschil |
| `sync` | `LlmSync` | ⚠️ semantisch anders |
| `tibet:ping` | `Control` | ⚠️ kan mappen |
| — | `Finance` | ❌ mist in Python |
| — | `Industrial` | ❌ mist in Python |
| `vpn:tunnel` | — | ❌ mist in Rust |
| `mail` | — | ❌ mist in Rust |
| `session` | — | ❌ mist in Rust |

Actie: `intents.py` uitbreiden met `finance` en `industrial`.
Rust `StreamIntent` uitbreiden met `Vpn`, `Mail`, `Session`.
Wire format afstemmen: Python `call:voice` = Rust `voice` op het netwerk.

### 2. QUIC transport backend

Nieuw bestand: `src/tibet_mux/quic_backend.py`

tibet-mux v1.0 gebruikt WebSocket. v2.0 kan QUIC als alternatieve transport
via de Rust trust-kernel (FFI of HTTP bridge naar brain_api).

```python
class QuicMuxBackend:
    """QUIC transport via overlay_mux (calls Rust via brain_api)."""
    
    async def connect(self, idd: str) -> "QuicConnection":
        """Resolve IDD → endpoint, establish QUIC."""
        # POST /api/overlay/mux/connect {idd}
    
    async def send(self, conn, intent: str, payload: bytes) -> dict:
        """Send intent over existing QUIC connection."""
        # POST /api/overlay/mux/send {intent, payload}
```

### 3. BandwidthPolicy in Rust

De Python BandwidthPolicy (priority, rate limit, burst, preemptible) is
uitgebreider dan de Rust StreamIntent. Dit kan:
- Rust-side: priority hints meegeven in IntentFrame.metadata
- Python-side: BandwidthGuard draait client-side rate limiting

### 4. Version bump

Volgende release: v1.1.0 met finance/industrial intents + intent mapping docs.
Daarna v2.0.0 met QUIC backend optie.

## Prioriteit

1. Intent sync (finance + industrial toevoegen) — **voor hackathon**
2. QUIC backend — post-hackathon
3. Wire format alignment — post-hackathon

## Gerelateerd

- `tibet-overlay` — Python identity resolver (IDD → endpoint)
- `tibet-trust-kernel` (crates.io) — Rust overlay_mux + quic_mux
- Benchmark: 1.7ms/intent Rust, vergelijk met 150ms+ traditioneel
