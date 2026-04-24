import hashlib
import logging
import os
import subprocess
from pathlib import Path

from constants import PUBLIC_KEY_PATH
from utils import run_cmd

log = logging.getLogger(__name__)


def _compute_hash_file(file_path: Path) -> Path:
    """Compute hash of file and return the path to the hash file."""
    hash_path = file_path.with_suffix(".sha256")
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).digest()
        with open(hash_path, "wb") as f:
            f.write(file_hash)
    except (OSError, IOError) as err:
        log.error("Failed to compute hash for %s: %s", file_path, err)
        raise
    return hash_path


def verify_model_signature(
    model_path: Path,
    signature_path: Path,
    public_key_path: Path = PUBLIC_KEY_PATH,
    algorithm: str = "ecc",
) -> bool:
    """Verify the signature of a model file using TPM."""
    hash_path = None
    try:
        hash_path = _compute_hash_file(model_path)
        log.info("Computed SHA256 hash for %s at %s", model_path, hash_path)

        if algorithm.lower() == "ecc":
            verify_cmd = f"./verifysignature -if {hash_path} -is {signature_path} -ipem {public_key_path} -ecc"
        else:
            verify_cmd = f"./verifysignature -if {hash_path} -is {signature_path} -ipem {public_key_path} -rsa"

        _, stderr, return_code = run_cmd(verify_cmd, tpm_cmd=True, check=False)

        if return_code == 0:
            log.info("Signature verification successful.")
            return True
        else:
            log.error("Signature verification failed. Stderr: %s", stderr.strip())
            return False

    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        log.error("An error occurred during verification: %s", err)
        return False
    finally:
        if hash_path and hash_path.exists():
            os.remove(hash_path)
