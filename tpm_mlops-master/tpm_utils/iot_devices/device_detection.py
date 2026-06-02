import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Minimum CMA free memory (kB) required to attempt DPU inference.
# MobileNetV2 needs ~30-60 MB; 64 MB gives a comfortable margin.
MIN_CMA_FREE_KB = int(os.environ.get("MIN_CMA_FREE_KB", "65536"))


def is_raspberry_pi() -> bool:
    """Check if the device is a Raspberry Pi."""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f.readlines():
                if "Raspberry Pi" in line:
                    return True
    except Exception:
        return False
    return False


def is_kria_board() -> bool:
    """Check if the device is an AMD Kria board."""
    try:
        return "xilinx" in os.uname().release
    except Exception:
        return False
    return False


def has_dpu() -> bool:
    """Check if a Xilinx DPU accelerator is available.

    Detection strategy (any match → True):
    1. /dev/dpu   – Vitis AI 3.x+ character device
    2. /dev/fpga0 – generic FPGA fabric device (older flows)
    3. /sys/class/xrt – Xilinx Runtime sysfs entries
    4. ``xir`` and ``vart`` Python packages importable
    """
    # Check device files
    for dev in ("/dev/dpu", "/dev/fpga0"):
        if Path(dev).exists():
            log.info("DPU detected via device file: %s", dev)
            return True

    # Check Xilinx Runtime sysfs
    if Path("/sys/class/xrt").exists():
        log.info("DPU detected via /sys/class/xrt")
        return True

    # Check if Vitis AI runtime libraries are importable
    try:
        import xir  # noqa: F401
        import vart  # noqa: F401
        log.info("DPU detected via xir/vart Python packages")
        return True
    except ImportError:
        pass

    return False


def check_cma_available(min_kb: int = 0) -> tuple[bool, int]:
    """Check whether enough CMA (contiguous) memory is free for DPU DMA.

    Returns ``(ok, free_kb)`` where *ok* is True if ``free_kb >= min_kb``.
    If ``/proc/meminfo`` cannot be read (e.g. non-Linux), returns ``(True, -1)``
    so the caller can proceed (fail-open).
    """
    if min_kb <= 0:
        min_kb = MIN_CMA_FREE_KB

    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("CmaFree"):
                    m = re.search(r"(\d+)", line)
                    if m:
                        free_kb = int(m.group(1))
                        ok = free_kb >= min_kb
                        if not ok:
                            log.warning(
                                "CMA memory too low for DPU: %d kB free < %d kB required",
                                free_kb, min_kb,
                            )
                        else:
                            log.info("CMA memory OK: %d kB free (need %d kB)", free_kb, min_kb)
                        return ok, free_kb
    except OSError:
        pass

    return True, -1  # fail-open on non-Linux


def is_dpu_firmware_loaded() -> bool:
    """Check whether DPU firmware (bitstream) is currently loaded on Kria."""
    import subprocess as _sp
    try:
        r = _sp.run(["xmutil", "listapps"], capture_output=True, text=True, timeout=5)
        # Any active app containing "dpu" or "smartcam" is a good sign
        for line in r.stdout.lower().splitlines():
            if ("active" in line or "*" in line) and ("dpu" in line or "smartcam" in line):
                log.info("DPU firmware is loaded: %s", line.strip())
                return True
    except (FileNotFoundError, _sp.TimeoutExpired):
        pass
    # If xmutil is unavailable, fall through to has_dpu() results
    return True  # fail-open


def determine_inference_backend() -> str:
    """Determine the best inference backend for this device.

    Returns:
        "dpu"  – Kria board with DPU available and enough CMA → use Vitis AI runner
        "onnx" – everything else                               → use ONNX Runtime (CPU/CUDA)
    """
    if is_kria_board() and has_dpu():
        cma_ok, cma_free = check_cma_available()
        if not cma_ok:
            log.warning(
                "DPU available but CMA memory insufficient (%d kB free). "
                "Falling back to ONNX Runtime.",
                cma_free,
            )
            return "onnx"
        log.info("Inference backend: DPU (Kria board with DPU detected)")
        return "dpu"

    log.info("Inference backend: ONNX Runtime")
    return "onnx"


def determine_hashing_type():
    """Determine the hashing type for the device."""
    if is_raspberry_pi():
        return "openssl"
    elif is_kria_board():
        return "tpm"
    else:
        log.warning("Couldn't determine device")
        return "openssl"
