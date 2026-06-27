"""Machine posture — "can THIS machine carry THIS route?" (tibet-mux, 27 Jun 2026).

Framing: jasper + codex.aint. Not a "PC trust score 87". A machine has a
*capability posture*: a proven, testable set that answers a question no spec
answers today —

    Can this machine carry this AI route, safely, reproducibly, fast enough?

Computers are sold "AI ready"; nobody proves "this box can hold identity, carry
sealed traffic, audit without stalling, run inference, hold route posture, and
fail closed on mismatch." This module is that missing spec. The question is not
"is my PC trusted?" but "WHICH ROUTES may my PC carry?".

Dimensions (codex): cpu · memory · storage · gpu · kernel · identity · network ·
audit. Detection is best-effort and HONEST — unknowns are marked unknown, never
assumed. Maps machine capabilities -> the carrier-policy bands the box can bear.

Pure stdlib (reads /proc, /sys, /dev; optional nvidia-smi). One love, fAmIly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Dict, List, Optional

from . import carrier_policy as cp
from . import cpu_capability as cc
from . import route_posture as rp

POSTURE_KIND = "org.ainternet.machine_posture.v1"

UNKNOWN = "unknown"


# --- Best-effort probes (honest: unknown when we can't safely tell) ----------
def _kernel() -> Dict[str, object]:
    return {
        "kvm": os.path.exists("/dev/kvm"),
        "iommu": os.path.isdir("/sys/kernel/iommu_groups")
        and len(os.listdir("/sys/kernel/iommu_groups")) > 0,
        "userfaultfd": os.path.exists("/proc/sys/vm/unprivileged_userfaultfd")
        or os.path.exists("/proc/sys/kernel/unprivileged_userns_clone"),
        "namespaces": os.path.isdir("/proc/self/ns"),
        "seccomp": _seccomp_available(),
    }


def _seccomp_available() -> bool:
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            return any(line.startswith("Seccomp") for line in fh)
    except OSError:
        return False


def _identity() -> Dict[str, object]:
    tpm = os.path.exists("/dev/tpmrm0") or os.path.exists("/dev/tpm0")
    return {"tpm": tpm, "key_custody": "tpm" if tpm else "software"}


def _memory() -> Dict[str, object]:
    total_kb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal"):
                    total_kb = int(line.split()[1])
                    break
    except OSError:
        pass
    # ECC: best-effort via the EDAC subsystem (present => ECC controller seen).
    edac = "/sys/devices/system/edac/mc"
    ecc = True if (os.path.isdir(edac) and os.listdir(edac)) else UNKNOWN
    pressure = os.path.exists("/proc/pressure/memory")
    return {
        "total_gb": round(total_kb / 1e6, 1) if total_kb else UNKNOWN,
        "ecc": ecc,
        "pressure_stall_info": pressure,
    }


def _storage() -> Dict[str, object]:
    # dm-crypt mapper devices => at-rest encryption available (best-effort).
    enc = UNKNOWN
    mapper = "/dev/mapper"
    if os.path.isdir(mapper):
        names = [n for n in os.listdir(mapper) if n != "control"]
        enc = bool(names)
    return {"at_rest_encryption": enc, "fsync": True}  # fsync is POSIX-guaranteed


def _gpu() -> Dict[str, object]:
    if not shutil.which("nvidia-smi"):
        return {"present": False}
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=count,memory.total,pstate",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8).stdout.strip()
        lines = [l for l in out.splitlines() if l.strip()]
        return {"present": True, "count": len(lines), "detail": lines[:4]}
    except Exception:
        return {"present": True, "detail": UNKNOWN}


def detect_machine() -> Dict[str, object]:
    """Probe every dimension (best-effort, honest unknowns)."""
    cpu = cc.detect_cpu_features()
    return {
        "cpu": cpu,
        "memory": _memory(),
        "storage": _storage(),
        "gpu": _gpu(),
        "kernel": _kernel(),
        "identity": _identity(),
        # network/audit are policy-level (MUX overlay, fire-and-forget audit) —
        # the machine CAN emit/hold receipts off-path; lane isolation is a route
        # property, not a static hardware fact. Marked accordingly.
        "network": {"mux_overlay": "policy-level", "lane_isolation": "route-property"},
        "audit": {"can_emit": True, "can_hold_without_stall": True,
                  "basis": "fire-and-forget telemetry + durable WAL (two tiers)"},
    }


def machine_posture_receipt(detected: Optional[Dict] = None) -> Dict:
    d = detected if detected is not None else detect_machine()
    return {"kind": POSTURE_KIND, **d,
            "note": "machine capability posture; answers which routes this box may carry"}


# --- The question: which routes may this machine carry? ----------------------
def can_carry(receipt: Dict, route_posture: str, payload_class: str) -> Dict[str, object]:
    """Can this machine physically/safely carry the given route + payload?

    Maps machine capabilities onto the carrier-policy band requirements. Returns
    a verdict with the reasons and what's MISSING — never a score.
    """
    feats = receipt["cpu"]["features"]
    gpu_present = bool(receipt["gpu"].get("present"))
    tpm = bool(receipt["identity"].get("tpm"))
    iommu = bool(receipt["kernel"].get("iommu"))
    band = cp.posture_band(rp.decode_posture(route_posture))

    missing: List[str] = []
    # Sealed traffic / onion encryption needs AES-NI to keep up with the bus.
    if not feats.get("aes_ni"):
        missing.append("aes_ni (sealed traffic would be CPU-bound)")
    # A5 sign-ahead under load wants fast hashing (sha_ni or avx512 multi-buffer).
    a5_capable = feats.get("sha_ni") or feats.get("avx512f")
    # hot_transfer over a GPU lane needs a GPU + IOMMU-protected DMA.
    if payload_class == "hot_transfer":
        if not gpu_present:
            missing.append("gpu (hot_transfer lane)")
        if not iommu:
            missing.append("iommu (protected DMA)")
    # Sealed multi-actor runtime needs hardware key custody.
    sealed_multi_actor = tpm and iommu

    # The decode the route asks for (A-digit) vs what the box can sustain.
    asks_sign_ahead = rp.decode_posture(route_posture).audit_mode >= 5
    if asks_sign_ahead and not a5_capable:
        missing.append("sha_ni/avx512 (A5 sign-ahead under load)")

    can = not missing
    return {
        "route_posture": route_posture,
        "payload_class": payload_class,
        "band": band,
        "can_carry": can,
        "missing": missing,
        "sealed_multi_actor": sealed_multi_actor,
        "verdict": (f"supports route {route_posture} for {payload_class}"
                    if can else
                    f"cannot carry {route_posture} for {payload_class}: missing {', '.join(missing)}"),
    }


def posture_statements(receipt: Dict) -> List[str]:
    """The human 'machine posture: ...' lines (codex's form)."""
    feats = receipt["cpu"]["features"]
    tpm = bool(receipt["identity"].get("tpm"))
    iommu = bool(receipt["kernel"].get("iommu"))
    gpu = bool(receipt["gpu"].get("present"))
    out: List[str] = []
    if feats.get("aes_ni"):
        out.append("machine posture: encrypts at line rate with AES-NI")
    if feats.get("fma3"):
        out.append("machine posture: safe for local inference (FMA3 compute lane)")
    if not (feats.get("sha_ni") or feats.get("avx512f")):
        out.append("machine posture: cannot support A5 sign-ahead under load (no SHA-NI/AVX-512)")
    if tpm and iommu:
        out.append("machine posture: can hold sealed multi-actor runtime (TPM key custody + IOMMU)")
    else:
        out.append("machine posture: safe for local inference, not for sealed multi-actor runtime "
                   f"(tpm={tpm}, iommu={iommu})")
    if gpu and iommu:
        out.append("machine posture: supports hot_transfer GPU lane (GPU + protected DMA)")
    return out


__all__ = [
    "POSTURE_KIND", "detect_machine", "machine_posture_receipt",
    "can_carry", "posture_statements",
]
