"""Key management (for the orchestrator only)"""

# fmt: off

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(os.path.expanduser("~"))
OPENSSL_KEYS_PATH = BASE_DIR / "tss_model_sec" / "openssl_keys"
PRIVATE_KEY_PATH = OPENSSL_KEYS_PATH / "priv.pem"
PUBLIC_KEY_PATH = OPENSSL_KEYS_PATH / "pub.pem"

log = logging.getLogger(__name__)


def run_cmd(cmd: str):
    """Run a shell command and return the output along with the return code."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
    return result.stdout, result.returncode


def generate_key_pair():
    """Generate and save EC key pair if they don't exist."""
    os.makedirs(OPENSSL_KEYS_PATH, exist_ok=True)

    # generate EC key pair
    if not os.path.exists(PRIVATE_KEY_PATH):
        # private key
        _, _ = run_cmd(f"openssl ecparam -name prime256v1 -genkey -noout -out {PRIVATE_KEY_PATH}")
        log.info("Private key generated %s", PRIVATE_KEY_PATH)

        # public key
        _, _ = run_cmd(f"openssl ec -in {PRIVATE_KEY_PATH} -pubout -out {PUBLIC_KEY_PATH}")
        log.info("Public key generated %s", PUBLIC_KEY_PATH)
    else:
        log.info("Using existing key pair")


def sign_model(file_path: str):
    """
    1. Hash model file
    2. Sign hash with private key
    3. Return signature
    """
    model_path: Path = Path(file_path)

    hash_path = model_path.with_suffix(".sha256")
    sign_path = model_path.with_suffix(".sig")

    try:
        # compute hash
        log.info("Computing SHA-256 hash: %s", hash_path)
        with open(model_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).digest()
        with open(hash_path, "wb") as f:
            f.write(file_hash)

        # sign the hash
        log.info("Signing with private key: %s", sign_path)
        run_cmd(f"openssl pkeyutl -sign -in {hash_path} -inkey {PRIVATE_KEY_PATH} -out {sign_path}")

        log.info("Model signed successfully")
        log.info("Signature: %s", sign_path)
        log.info("Public key: %s", PUBLIC_KEY_PATH)

        return sign_path
    except Exception as err:
        log.error("Failed to sign model: %s", err)
        return None
    finally:
        if hash_path.exists():
            hash_path.unlink()

def main():
    """Main function for key generation."""
    # redirect print to logging
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s", stream=sys.stdout)

    if len(sys.argv) < 2:
        log.error("Usage: python keygen.py <model_path>")
        sys.exit(1)

    model_path = sys.argv[1]

    log.info("Model: %s", model_path)

    if not Path(model_path).exists():
        log.error("Model file not found: %s", model_path)
        sys.exit(1)

    generate_key_pair()
    signature_path = sign_model(model_path)

    if signature_path:
        log.info("Model signing completed")
        log.info("Files created:")
        log.info("  - Model signature: %s", signature_path)
        log.info("  - Public key: %s", PUBLIC_KEY_PATH)
        log.info("  - Private key: %s", PRIVATE_KEY_PATH)
    else:
        log.error("Model signing failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
