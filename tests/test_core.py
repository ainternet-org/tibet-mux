"""Tests for tibet-mux core."""

from tibet_mux import Mux, Channel, Frame
from tibet_mux.intents import resolve_intent, INTENT_ROUTES


def test_mux_create():
    mux = Mux(agent="test_agent")
    assert mux.agent == "test_agent"


def test_mux_strips_aint():
    mux = Mux(agent="test.aint")
    assert mux.agent == "test"


def test_open_channel():
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="chat")
    assert ch.state == "open"
    assert ch.agent == "alice"
    assert ch.target == "bob"
    assert ch.intent == "chat"
    assert ch.id.startswith("ch-")
    assert len(ch.tbz_chain) == 1  # open event


def test_send_frame():
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="chat")
    frame = ch.send({"text": "hello"})
    assert frame.seq == 0
    assert frame.tbz_hash
    assert ch.frames_sent == 1
    assert len(ch.tbz_chain) == 2  # open + send


def test_multiple_frames():
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="stream")
    for i in range(10):
        frame = ch.send({"seq": i})
        assert frame.seq == i
    assert ch.frames_sent == 10
    assert len(ch.tbz_chain) == 11  # open + 10 sends


def test_close_channel():
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="chat")
    ch.send({"text": "bye"})
    result = ch.close()
    assert result["state"] == "closed"
    assert result["duration_frames"] == 1
    assert result["tbz_chain_length"] == 3  # open + send + close


def test_channel_isolation():
    """Channels don't share state."""
    mux = Mux(agent="alice")
    chat = mux.open(target="bob", intent="chat")
    voice = mux.open(target="bob", intent="call:voice")

    chat.send({"text": "hi"})
    chat.send({"text": "there"})
    voice.send({"type": "sdp"})

    assert chat.frames_sent == 2
    assert voice.frames_sent == 1
    assert chat.id != voice.id


def test_list_channels():
    mux = Mux(agent="alice")
    mux.open(target="bob", intent="chat")
    mux.open(target="charlie", intent="call:voice")

    channels = mux.channels()
    assert len(channels) == 2


def test_close_removes_from_listing():
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="chat")
    mux.close(ch.id)

    channels = mux.channels()
    assert len(channels) == 0


def test_max_channels():
    mux = Mux(agent="alice", max_channels=3)
    mux.open(target="a", intent="chat")
    mux.open(target="b", intent="chat")
    mux.open(target="c", intent="chat")

    try:
        mux.open(target="d", intent="chat")
        assert False, "Should have raised"
    except Exception as e:
        assert "Max" in str(e)


def test_resolve_exact_intent():
    intent = resolve_intent("chat")
    assert intent.backend == "ipoll"
    assert intent.name == "chat"


def test_resolve_prefix_intent():
    intent = resolve_intent("call:voice:opus")
    assert intent.backend == "voice"
    assert intent.parent == "call:voice"


def test_resolve_unknown_intent():
    intent = resolve_intent("custom:weird:thing")
    assert intent.backend == "generic"


def test_custom_intent():
    mux = Mux(agent="alice")
    mux.register_intent("iot:sensor", "mqtt", "IoT sensor data")

    ch = mux.open(target="hub", intent="iot:sensor")
    assert ch.resolved_intent.backend == "mqtt"


def test_tbz_chain_integrity():
    """Each frame gets a unique hash in the chain."""
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="chat")

    hashes = set()
    for i in range(5):
        frame = ch.send({"n": i})
        assert frame.tbz_hash not in hashes
        hashes.add(frame.tbz_hash)

    assert len(ch.tbz_chain) == 6  # open + 5 sends
    assert len(set(ch.tbz_chain)) == 6  # all unique


def test_status():
    mux = Mux(agent="test")
    mux.open(target="a", intent="chat")
    mux.open(target="b", intent="call:voice")

    status = mux.status()
    assert status["status"] == "operational"
    assert status["channels"]["active"] == 2
    assert status["security"]["signing"] == "TBZ (TIBET provenance per frame)"


def test_closed_channel_cant_send():
    mux = Mux(agent="alice")
    ch = mux.open(target="bob", intent="chat")
    ch.close()

    try:
        ch.send({"text": "should fail"})
        assert False, "Should have raised"
    except Exception as e:
        assert "closed" in str(e).lower()
