"""CPU compute capability — attested, not assumed. Framing: codex.aint."""
from tibet_mux import cpu_capability as cc

# A W2135-like cpuinfo slice (fma + avx512 + aes, no vaes/sha_ni).
_W2135 = """processor\t: 0
model name\t: Intel(R) Xeon(R) W-2135 CPU @ 3.70GHz
flags\t\t: fpu vme fma avx2 avx512f aes pclmulqdq xsave
"""
# A Haswell-like slice (fma + aes, no avx512/vaes/sha_ni).
_HASWELL = """model name\t: Intel(R) Xeon(R) CPU E5-2650 v3 @ 2.30GHz
flags\t\t: fpu fma avx2 aes pclmulqdq
"""


def test_detect_from_text():
    d = cc.detect_cpu_features(_W2135)
    assert "W-2135" in d["cpu"]
    f = d["features"]
    assert f["fma3"] and f["avx512f"] and f["aes_ni"] and f["pclmulqdq"]
    assert not f["vaes"] and not f["sha_ni"]


def test_compute_semantics_single_rounding_when_fma():
    f = cc.detect_cpu_features(_W2135)["features"]
    sem = cc.compute_semantics(f, runner_flags=["-C", "target-feature=+fma"])
    assert sem["fused_multiply_add"] == "enabled"
    assert sem["rounding"] == "single-rounding-fma"  # NOT bit-identical to mul+add


def test_receipt_is_not_a_sixth_digit():
    r = cc.cpu_capability_receipt(cc.detect_cpu_features(_W2135))
    assert r["kind"] == cc.CAPABILITY_KIND
    assert "#RCTAM unchanged" in r["note"]
    # it carries features + semantics, it does not encode a route digit
    assert "route_posture" not in r


def test_runner_gate_no_guessing():
    w = cc.cpu_capability_receipt(cc.detect_cpu_features(_W2135))
    assert cc.fma_permitted(w) is True
    nofma = cc.cpu_capability_receipt({"cpu": "x", "features": {"fma3": False}})
    assert cc.fma_permitted(nofma) is False


def test_lane_labels_are_policy_input():
    w = cc.detect_cpu_features(_W2135)["features"]
    h = cc.detect_cpu_features(_HASWELL)["features"]
    assert cc.compute_lane_label(w) == "fma-avx512"
    assert cc.compute_lane_label(h) == "fma-avx2"
    assert cc.compute_lane_label({"fma3": False}) == "no-fma"
    assert cc.crypto_lane_label(w) == "aesni-gcm"      # aes_ni + pclmulqdq, no vaes
    assert cc.crypto_lane_label({"aes_ni": False}) == "software-crypto"


def test_real_host_detect_runs():
    # Smoke: the real /proc/cpuinfo path works and yields a features dict.
    d = cc.detect_cpu_features()
    assert "features" in d and isinstance(d["features"], dict)
    assert set(d["features"]) >= {"fma3", "aes_ni", "avx512f"}
