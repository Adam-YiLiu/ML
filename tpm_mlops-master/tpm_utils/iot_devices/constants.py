from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(os.path.expanduser("~"))
TSS_UTILS_DIR = BASE_DIR / "tss" / "utils"

PUBLIC_KEY_PATH = BASE_DIR / "tss_model_sec" / "openssl_keys" / "pub.pem"
PRIVATE_KEY_PATH = BASE_DIR / "tss_model_sec" / "openssl_keys" / "priv.pem"
KEY_CONTEXT_PATH = BASE_DIR / "tss_model_sec" / "openssl_keys" / "key.ctx"

# Edge deployment package produced by the orchestrator
EDGE_PACKAGE_DIR = BASE_DIR / "tss_model_sec" / "orchestrator_output" / "edge_package"

# Known model file extensions in order of preference per backend
_MODEL_EXTENSIONS = {
    "dpu":  [".xmodel"],
    "onnx": [".onnx"],
}


def discover_model(backend: str = "onnx") -> Path | None:
    """Find the deployed model inside the edge package directory.

    Searches ``EDGE_PACKAGE_DIR`` for a file matching the preferred extension
    for the given *backend*.  Returns the first match, or ``None``.
    """
    if not EDGE_PACKAGE_DIR.is_dir():
        log.warning("Edge package directory not found: %s", EDGE_PACKAGE_DIR)
        return None

    for ext in _MODEL_EXTENSIONS.get(backend, _MODEL_EXTENSIONS["onnx"]):
        candidates = sorted(EDGE_PACKAGE_DIR.glob(f"*{ext}"))
        if candidates:
            log.info("Discovered model for %s backend: %s", backend, candidates[0])
            return candidates[0]

    # Fallback: try any known extension
    for exts in _MODEL_EXTENSIONS.values():
        for ext in exts:
            candidates = sorted(EDGE_PACKAGE_DIR.glob(f"*{ext}"))
            if candidates:
                log.info("Fallback model discovery: %s", candidates[0])
                return candidates[0]

    log.warning("No model found in %s", EDGE_PACKAGE_DIR)
    return None


def signature_path_for(model_path: Path) -> Path:
    """Derive the ``.sig`` path that corresponds to a model file."""
    return model_path.with_suffix(".sig")