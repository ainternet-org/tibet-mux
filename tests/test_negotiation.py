"""Capability negotiation — route on what the machines CAN do. Realization: jasper."""
from tibet_mux import negotiation as neg


def _machine(*, gpu=True, aes_ni=True, iommu=True, tpm=True, avx512f=True, sha_ni=False):
    return {
        "cpu": {"cpu": "test", "features": {
            "fma3": True, "avx2": True, "avx512f": avx512f, "aes_ni": aes_ni,
            "pclmulqdq": True, "sha_ni": sha_ni, "vaes": False}},
        "gpu": {"present": gpu}, "kernel": {"iommu": iommu},
        "identity": {"tpm": tpm}, "memory": {}, "storage": {}, "network": {}, "audit": {},
    }


def test_both_capable_offers_full_carrier():
    full = _machine()
    n = neg.negotiate("#24348", "hot_transfer", full, full)
    assert n["offered_carrier"] == "gpu_mailbox_capsule"
    assert n["downgraded"] is False


def test_receiver_without_gpu_downgrades_to_cmail():
    # Jasper's case: "ik mag geen A2A, maar cmail van die kant openen wél."
    sender = _machine()
    receiver = _machine(gpu=False, iommu=False)  # cannot carry the A2A hot lane
    n = neg.negotiate("#24348", "hot_transfer", sender, receiver)
    assert n["desired_carrier"] == "gpu_mailbox_capsule"
    assert n["offered_carrier"] in ("cap_bus.event", "phantom.diff_merge", "cmail.capsule")
    assert n["offered_carrier"] != "gpu_mailbox_capsule"
    assert n["downgraded"] is True


def test_no_aes_downgrades_to_unsealed_floor():
    sender = _machine()
    receiver = _machine(gpu=False, iommu=False, aes_ni=False)  # can't even seal fast
    n = neg.negotiate("#24348", "hot_transfer", sender, receiver)
    # cmail/cap_bus need aes_ni from both -> floor is the unsealed signed message
    assert n["offered_carrier"] in ("cmail.capsule", "ipoll.message")
    assert n["downgraded"] is True


def test_dark_route_when_no_common_ground():
    # A dark route posture: nobody opens a carrier.
    n = neg.negotiate(neg.rp.DARK, "control", _machine(), _machine())
    assert n["offered_carrier"] == "dark_route"


def test_reason_explains_the_downgrade():
    n = neg.negotiate("#24348", "hot_transfer", _machine(), _machine(gpu=False))
    assert "downgraded" in n["reason"]
    assert "receiver_missing" in n["reason"]
