"""CPU compute capability — attested, not assumed (tibet-mux, 27 Jun 2026).

Framing: codex.aint. FMA3 (and the crypto ISA) is NOT a security primitive and
NOT a 6th #RCTAM digit. It is an *attested compute capability* the posture
CARRIES alongside the route number:

    trust-kernel   -> attests FMA3 capability + compute semantics
    carrier-policy -> reads it as lane / posture input (compute_lane_label)
    runner         -> may use FMA3 only if the receipt/policy allows (fma_permitted)
    audit / trail  -> keeps the feature-set for later reconstruction

Why it must be attested, not guessed:
- Lane choice: an FMA3 route may get a different compute lane than one without.
- Reproducibility: FMA does a*b+c with ONE rounding — not bit-identical to a
  separate multiply + add. The receipt records that so a reconstruction knows.
- Sign-ahead budget: faster compute shrinks the audit/crypto shadow, so the
  scheduler must know FMA3 is active.
- No guessing: the MUX/carrier-policy reads features from a trust-kernel
  receipt, it does not assume the host has them.

Pure stdlib (reads /proc/cpuinfo). One love, one fAmIly.
"""
from __future__ import annotations

from typing import Dict, List, Optional

CAPABILITY_KIND = "org.ainternet.trust_kernel.cpu_capability.v1"

# /proc/cpuinfo flag -> our capability name
_FLAG_MAP = {
    "fma": "fma3",
    "avx2": "avx2",
    "avx512f": "avx512f",
    "aes": "aes_ni",
    "pclmulqdq": "pclmulqdq",
    "vaes": "vaes",
    "sha_ni": "sha_ni",
}


def detect_cpu_features(cpuinfo_text: Optional[str] = None) -> Dict[str, object]:
    """Read CPU model + the capability flags from /proc/cpuinfo (or given text)."""
    if cpuinfo_text is None:
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as fh:
                cpuinfo_text = fh.read()
        except OSError:
            cpuinfo_text = ""
    flags: set = set()
    model = "unknown"
    for line in cpuinfo_text.splitlines():
        low = line.lower()
        if low.startswith("flags") and ":" in line:
            flags |= set(line.split(":", 1)[1].split())
        elif low.startswith("model name") and ":" in line and model == "unknown":
            model = line.split(":", 1)[1].strip()
    features = {name: (flag in flags) for flag, name in _FLAG_MAP.items()}
    return {"cpu": model, "features": features}


def compute_semantics(features: Dict[str, bool],
                      runner_flags: Optional[List[str]] = None) -> Dict[str, str]:
    """The compute-semantics block — what FMA3 does to numerics (reproducibility)."""
    fma = bool(features.get("fma3"))
    return {
        "fused_multiply_add": "enabled" if fma else "disabled",
        # FMA single-rounding is NOT bit-identical to separate mul+add.
        "rounding": "single-rounding-fma" if fma else "separate-mul-add",
        "determinism_scope": "same feature set + same runner flags",
        "runner_flags": ",".join(runner_flags or []),
    }


def cpu_capability_receipt(detected: Optional[Dict] = None, *,
                           runner_flags: Optional[List[str]] = None) -> Dict:
    """The trust-kernel's attested CPU-capability receipt (codex's schema)."""
    d = detected if detected is not None else detect_cpu_features()
    feats = d["features"]
    return {
        "kind": CAPABILITY_KIND,
        "cpu": d["cpu"],
        "features": feats,
        "compute_semantics": compute_semantics(feats, runner_flags),
        # Explicitly NOT a #RCTAM digit: a separate attested object the posture carries.
        "note": "attested compute capability; carrier-policy reads it, #RCTAM unchanged",
    }


def fma_permitted(capability_receipt: Dict) -> bool:
    """Runner gate: FMA3 may be used only if the trust-kernel attested it."""
    return bool(capability_receipt.get("features", {}).get("fma3"))


def compute_lane_label(features: Dict[str, bool]) -> str:
    """Carrier-policy lane input: which compute-semantics lane this CPU offers.
    A label, not a rating — 'this route can fuse MAC on AVX-512' etc."""
    if features.get("fma3") and features.get("avx512f"):
        return "fma-avx512"
    if features.get("fma3") and features.get("avx2"):
        return "fma-avx2"
    if features.get("fma3"):
        return "fma-scalar"
    return "no-fma"


def crypto_lane_label(features: Dict[str, bool]) -> str:
    """Companion: which crypto-ISA lane (for the AES-NI onion / hashing)."""
    if features.get("vaes") and features.get("aes_ni"):
        return "vaes"
    if features.get("aes_ni") and features.get("pclmulqdq"):
        return "aesni-gcm"
    if features.get("aes_ni"):
        return "aesni"
    return "software-crypto"


__all__ = [
    "CAPABILITY_KIND", "detect_cpu_features", "compute_semantics",
    "cpu_capability_receipt", "fma_permitted", "compute_lane_label",
    "crypto_lane_label",
]
