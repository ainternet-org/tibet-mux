"""
tibet-mux client — connect to a remote mux server.

Usage:
    from tibet_mux.client import MuxClient

    client = MuxClient("https://api.ainternet.org", agent="my_agent")

    # Open channel
    ch = client.open(target="gemini", intent="chat")

    # Send
    result = client.send(ch["channel_id"], {"text": "Hello!"})

    # Close
    client.close(ch["channel_id"])
"""

from typing import Any, Optional


class MuxClient:
    """
    HTTP client for tibet-mux server.

    Zero dependencies beyond stdlib. Falls back to urllib if httpx not available.
    """

    def __init__(self, base_url: str, agent: str, prefix: str = "/api/mux"):
        self.base_url = base_url.rstrip("/")
        self.agent = agent.replace(".aint", "").strip().lower()
        self.prefix = prefix
        self._session = None

    def _url(self, path: str) -> str:
        return f"{self.base_url}{self.prefix}{path}"

    def _post(self, path: str, data: dict) -> dict:
        """POST JSON, return parsed response."""
        import json
        import urllib.request

        req = urllib.request.Request(
            self._url(path),
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def _get(self, path: str, params: dict | None = None) -> dict:
        """GET with optional query params."""
        import json
        import urllib.request
        import urllib.parse

        url = self._url(path)
        if params:
            url += "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def open(
        self,
        target: str,
        intent: str,
        metadata: dict | None = None,
    ) -> dict:
        """Open a channel. Returns channel info dict."""
        return self._post("/open", {
            "agent": self.agent,
            "target": target,
            "intent": intent,
            "metadata": metadata,
        })

    def send(self, channel_id: str, payload: Any) -> dict:
        """Send a frame on a channel."""
        return self._post("/send", {
            "channel_id": channel_id,
            "payload": payload,
        })

    def close(self, channel_id: str, reason: str = "client_close") -> dict:
        """Close a channel."""
        return self._post("/close", {
            "channel_id": channel_id,
            "reason": reason,
        })

    def channels(self) -> dict:
        """List open channels."""
        return self._get("/channels", {"agent": self.agent})

    def channel(self, channel_id: str) -> dict:
        """Get channel detail."""
        return self._get(f"/channel/{channel_id}")

    def intents(self) -> dict:
        """List available intents."""
        return self._get("/intents")

    def status(self) -> dict:
        """Server health."""
        return self._get("/status")
