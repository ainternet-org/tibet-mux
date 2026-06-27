"""Machine posture — which routes may this machine carry? Framing: jasper + codex."""
from tibet_mux import machine_posture as mp


def _receipt(*, fma3=True, avx2=True, avx512f=True, aes_ni=True, pclmulqdq=True,
             sha_ni=False, vaes=False, gpu=True, tpm=True, iommu=True):
    return {
        "kind": mp.POSTURE_KIND,
        "cpu": {"cpu": "test", "features": {
            "fma3": fma3, "avx2": avx2, "avx512f": avx512f, "aes_ni": aes_ni,
            "pclmulqdq": pclmulqdq, "sha_ni": sha_ni, "vaes": vaes}},
        "memory": {"total_gb": 64, "ecc": True, "pressure_stall_info": True},
        "storage": {"at_rest_encryption": True, "fsync": True},
        "gpu": {"present": gpu, "count": 2 if gpu else 0},
        "kernel": {"kvm": True, "iommu": iommu, "userfaultfd": True,
                   "namespaces": True, "seccomp": True},
        "identity": {"tpm": tpm, "key_custody": "tpm" if tpm else "software"},
        "network": {}, "audit": {"can_emit": True},
    }


def test_w2135_like_carries_hot_transfer():
    r = _receipt()  # full P520/W2135-like box
    v = mp.can_carry(r, "#24358", "hot_transfer")
    assert v["can_carry"] is True
    assert v["band"] == "P4"
    assert "supports route #24358" in v["verdict"]


def test_no_aes_ni_cannot_carry_sealed():
    v = mp.can_carry(_receipt(aes_ni=False), "#24348", "session_diff")
    assert v["can_carry"] is False
    assert any("aes_ni" in m for m in v["missing"])


def test_a5_sign_ahead_needs_sha_or_avx512():
    # asks A5 (sign-ahead) but no sha_ni and no avx512 -> missing
    v = mp.can_carry(_receipt(sha_ni=False, avx512f=False), "#24358", "control")
    assert v["can_carry"] is False
    assert any("A5 sign-ahead" in m for m in v["missing"])
    # same box but a non-sign-ahead route (A4) is fine
    v2 = mp.can_carry(_receipt(sha_ni=False, avx512f=False), "#24348", "control")
    assert v2["can_carry"] is True


def test_hot_transfer_needs_gpu_and_iommu():
    v = mp.can_carry(_receipt(gpu=False), "#24348", "hot_transfer")
    assert v["can_carry"] is False
    assert any("gpu" in m for m in v["missing"])
    v2 = mp.can_carry(_receipt(iommu=False), "#24348", "hot_transfer")
    assert any("iommu" in m for m in v2["missing"])


def test_no_tpm_not_sealed_multi_actor():
    v = mp.can_carry(_receipt(tpm=False), "#24348", "control")
    assert v["sealed_multi_actor"] is False


def test_posture_statements_codex_lines():
    lines = mp.posture_statements(_receipt(aes_ni=True, fma3=True, sha_ni=False,
                                           avx512f=False, tpm=False, iommu=True, gpu=True))
    blob = " | ".join(lines)
    assert "encrypts at line rate with AES-NI" in blob
    assert "cannot support A5 sign-ahead under load" in blob
    assert "not for sealed multi-actor runtime" in blob


def test_real_machine_detect_smoke():
    r = mp.machine_posture_receipt()
    assert r["kind"] == mp.POSTURE_KIND
    for dim in ("cpu", "memory", "storage", "gpu", "kernel", "identity", "audit"):
        assert dim in r
    # the real question answers without crashing
    v = mp.can_carry(r, "#24348", "control")
    assert "can_carry" in v
