import hashlib
import logging
import os
import subprocess
from pathlib import Path

from constants import KEY_CONTEXT_PATH, PRIVATE_KEY_PATH, PUBLIC_KEY_PATH
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
    key_context_path: Path = KEY_CONTEXT_PATH,
    algorithm: str = "ecc",
) -> bool:
    """Verify the signature of a model file using TPM."""
    hash_path = None
    try:
        hash_path = _compute_hash_file(model_path)
        log.info("Computed SHA256 hash for %s at %s", model_path, hash_path)
        
        # If hardware TPM is used and key context does not exist, import from PEM keys
        if not key_context_path.exists() and key_context_path == KEY_CONTEXT_PATH:
            log.error("Key context file not found, will try to import from PEM key.")
            import_cmd = f"sudo tpm2_loadexternal -C n -G {algorithm} -u {PUBLIC_KEY_PATH} -r {PRIVATE_KEY_PATH} -c {key_context_path}"
            stdout, stderr, return_code = run_cmd(import_cmd, tpm_cmd=True, check=False)
            if return_code != 0:
                log.error("Failed to import key context. Stdout: %s, Stderr: %s", stdout.strip(), stderr.strip())
                return False

        verify_cmd = f"sudo tpm2_verifysignature -m {hash_path} -s {signature_path} -c {key_context_path}"

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
