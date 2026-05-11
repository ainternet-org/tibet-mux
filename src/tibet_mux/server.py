"""
tibet-mux FastAPI server — mount on any ASGI app or run standalone.

Usage:
    # Standalone
    tibet-mux --port 8443 --agent my_node

    # Mount on existing FastAPI app
    from tibet_mux.server import create_router
    app.include_router(create_router())

    # Full standalone app
    from tibet_mux.server import create_app
    app = create_app()
"""

import json
import logging
from typing import Optional, Any

from tibet_mux.core import Mux, ChannelError

logger = logging.getLogger("tibet_mux.server")

# Lazy imports — only needed when server module is used
_fastapi = None
_pydantic = None


def _ensure_deps():
    global _fastapi, _pydantic
    if _fastapi is None:
        try:
            import fastapi as _fastapi
            import pydantic as _pydantic
        except ImportError:
            raise ImportError(
                "tibet-mux server requires FastAPI. "
                "Install with: pip install tibet-mux[server]"
            )


def create_router(mux: Mux | None = None, prefix: str = "/api/mux"):
    """
    Create a FastAPI APIRouter with all mux endpoints.

    Args:
        mux: Optional Mux instance (creates default if None)
        prefix: URL prefix (default: /api/mux)
    """
    _ensure_deps()
    from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
    from pydantic import BaseModel

    if mux is None:
        mux = Mux(agent="node")

    router = APIRouter(tags=["Tibet-Mux"])

    # ─── Models ─────────────────────────────────────────────────────

    class MuxOpenRequest(BaseModel):
        agent: str
        target: str
        intent: str
        metadata: Optional[dict] = None

    class MuxSendRequest(BaseModel):
        channel_id: str
        payload: Any

    class MuxCloseRequest(BaseModel):
        channel_id: str
        reason: Optional[str] = "client_close"

    # ─── REST Endpoints ─────────────────────────────────────────────

    @router.post(f"{prefix}/open")
    async def mux_open(req: MuxOpenRequest):
        try:
            ch = mux.open(
                target=req.target,
                intent=req.intent,
                metadata=req.metadata,
                agent=req.agent,
            )
        except ChannelError as e:
            raise HTTPException(429, str(e))

        return {
            "channel_id": ch.id,
            "intent": ch.intent,
            "route": {
                "backend": ch.resolved_intent.backend,
                "description": ch.resolved_intent.description,
            },
            "state": ch.state,
            "agent": ch.agent,
            "target": ch.target,
            "tbz_hash": ch.tbz_chain[-1],
        }

    @router.post(f"{prefix}/send")
    async def mux_send(req: MuxSendRequest):
        ch = mux.get(req.channel_id)
        if not ch:
            raise HTTPException(404, "Channel not found")

        try:
            frame = ch.send(req.payload)
        except ChannelError as e:
            raise HTTPException(409, str(e))

        return {
            "delivered": True,
            "channel_id": req.channel_id,
            "seq": frame.seq,
            "tbz_hash": frame.tbz_hash,
            "route": {
                "backend": ch.resolved_intent.backend,
                "description": ch.resolved_intent.description,
            },
        }

    @router.post(f"{prefix}/close")
    async def mux_close(req: MuxCloseRequest):
        try:
            result = mux.close(req.channel_id, req.reason or "client_close")
        except ChannelError as e:
            raise HTTPException(404, str(e))
        return result

    @router.get(f"{prefix}/channels")
    async def mux_channels(agent: str = Query(...)):
        channels = mux.channels(agent)
        return {
            "agent": agent.replace(".aint", "").lower(),
            "channels": [
                {
                    "id": ch.id,
                    "target": ch.target,
                    "intent": ch.intent,
                    "route": {
                        "backend": ch.resolved_intent.backend,
                        "description": ch.resolved_intent.description,
                    },
                    "opened_at": ch.opened_at,
                    "last_activity": ch.last_activity,
                    "frames_sent": ch.frames_sent,
                    "bytes_transferred": ch.bytes_transferred,
                }
                for ch in channels
            ],
            "count": len(channels),
        }

    @router.get(f"{prefix}/channel/{{channel_id}}")
    async def mux_channel_detail(channel_id: str):
        ch = mux.get(channel_id)
        if not ch:
            raise HTTPException(404, "Channel not found")
        return {**ch.to_dict(), "recent_frames": ch.recent_frames}

    @router.get(f"{prefix}/by-target")
    async def mux_by_target(
        target: str = Query(...),
        intent: str | None = None,
        include_closed: bool = False,
    ):
        """v1.0.1+ list channels by TARGET (not sender).

        Required for consumer-side polling: a receiver listens
        for channels addressed *to* it. The default `/channels`
        endpoint indexes by sender (= _agent_channels[src]),
        so receivers were invisible to themselves.

        Default include_closed=False (= only state=='open').
        Set true to also return recently-closed channels (= still
        held in core._channels with their recent_frames).
        """
        tgt = target.replace(".aint", "").lower()
        matches = []
        for ch in mux._channels.values():
            if ch.target != tgt:
                continue
            if intent and ch.intent != intent:
                continue
            if not include_closed and ch.state != "open":
                continue
            matches.append({
                "id": ch.id,
                "agent": ch.agent,
                "target": ch.target,
                "intent": ch.intent,
                "state": ch.state,
                "opened_at": ch.opened_at,
                "last_activity": ch.last_activity,
                "frames_sent": ch.frames_sent,
                "bytes_transferred": ch.bytes_transferred,
            })
        return {
            "target": tgt,
            "intent_filter": intent,
            "include_closed": include_closed,
            "channels": matches,
            "count": len(matches),
        }

    @router.get(f"{prefix}/intents")
    async def mux_intents():
        return {
            "intents": mux.intents(),
            "custom_allowed": True,
            "description": "Any intent string is accepted",
        }

    @router.get(f"{prefix}/status")
    async def mux_status():
        return mux.status()

    # ─── WebSocket ──────────────────────────────────────────────────

    @router.websocket(f"{prefix}/ws")
    async def mux_websocket(
        ws: WebSocket,
        agent: str = Query(...),
        token: str = Query(default=""),
    ):
        await ws.accept()
        ws_channels: list[str] = []
        norm_agent = agent.replace(".aint", "").lower()

        try:
            while True:
                data = await ws.receive_json()
                action = data.get("action", "")

                if action == "open":
                    target = data.get("target", "")
                    intent = data.get("intent", "stream")
                    try:
                        ch = mux.open(
                            target=target,
                            intent=intent,
                            metadata=data.get("metadata"),
                            agent=norm_agent,
                        )
                        ws_channels.append(ch.id)
                        await ws.send_json({
                            "event": "channel_opened",
                            "channel_id": ch.id,
                            "intent": intent,
                            "route": {
                                "backend": ch.resolved_intent.backend,
                                "description": ch.resolved_intent.description,
                            },
                            "tbz_hash": ch.tbz_chain[-1],
                        })
                    except ChannelError as e:
                        await ws.send_json({"error": str(e)})

                elif action == "send":
                    channel_id = data.get("channel_id", "")
                    ch = mux.get(channel_id)
                    if not ch or ch.state != "open":
                        await ws.send_json({
                            "error": "channel_not_found",
                            "channel_id": channel_id,
                        })
                        continue

                    frame = ch.send(data.get("payload", ""))
                    await ws.send_json({
                        "event": "frame_ack",
                        "channel_id": channel_id,
                        "seq": frame.seq,
                        "tbz_hash": frame.tbz_hash,
                    })

                elif action == "close":
                    channel_id = data.get("channel_id", "")
                    try:
                        mux.close(channel_id, data.get("reason", "client_close"))
                        if channel_id in ws_channels:
                            ws_channels.remove(channel_id)
                        await ws.send_json({
                            "event": "channel_closed",
                            "channel_id": channel_id,
                        })
                    except ChannelError:
                        await ws.send_json({
                            "error": "channel_not_found",
                            "channel_id": channel_id,
                        })

                elif action == "list":
                    open_chs = []
                    for cid in ws_channels:
                        ch = mux.get(cid)
                        if ch and ch.state == "open":
                            open_chs.append({
                                "id": ch.id,
                                "target": ch.target,
                                "intent": ch.intent,
                                "frames_sent": ch.frames_sent,
                            })
                    await ws.send_json({
                        "event": "channel_list",
                        "channels": open_chs,
                    })

                else:
                    await ws.send_json({
                        "error": "unknown_action",
                        "action": action,
                    })

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            for cid in ws_channels:
                try:
                    mux.close(cid, "ws_disconnect")
                except ChannelError:
                    pass

    return router


def create_app(agent: str = "node", prefix: str = "/api/mux"):
    """Create a standalone FastAPI app with mux endpoints."""
    _ensure_deps()
    from fastapi import FastAPI

    mux_instance = Mux(agent=agent)
    app = FastAPI(
        title="Tibet-Mux",
        description="Single-port channel multiplexer with intent-based routing",
        version="1.0.0",
    )
    app.include_router(create_router(mux=mux_instance, prefix=prefix))
    return app
