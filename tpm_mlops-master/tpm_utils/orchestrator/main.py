"""
Orchestrator Main Script.

Workflow:
1. Create & load signing key hierarchy
2. Hash the model
3. Sign the digest in the TPM
4. Export the public key (PEM)
6. Package everything for edge deployment

Usage:
    python main.py <model_path>
"""

import argparse
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from constants import OUTPUT_DIR
from dotenv import load_dotenv
from tpm_signing_ops import TPMManualFlowOps

load_dotenv()

log = logging.getLogger(__name__)


def package_for_edge(
    model_path: Path, signature_path: str, public_key_path: str, output_dir: str
) -> Path:
    """
    Package files for edge deployment.

    Files to transfer:
    - model.onnx (the model)
    - model.sig (the signature)
    - pub.pem (the public key)
    """
    package_dir = Path(output_dir) / "edge_package"
    os.makedirs(package_dir, exist_ok=True)

    try:
        # copy model file
        model_dest = package_dir / model_path.name
        shutil.copy2(model_path, model_dest)
        log.info("Packaged model: %s", model_dest)

        # if a compiled .xmodel exists alongside the .onnx, package it too
        xmodel_path = model_path.with_suffix(".xmodel")
        if xmodel_path.exists():
            xmodel_dest = package_dir / xmodel_path.name
            shutil.copy2(xmodel_path, xmodel_dest)
            log.info("Packaged compiled xmodel: %s", xmodel_dest)

        # copy signature file (rename to match model name with .sig extension)
        sig_dest = package_dir / model_path.with_suffix(".sig").name
        shutil.copy2(signature_path, sig_dest)
        log.info("Packaged signature: %s", sig_dest)

        # copy public key
        key_dest = package_dir / "public.pem"
        shutil.copy2(public_key_path, key_dest)
        log.info("Packaged public key: %s", key_dest)

        return package_dir

    except Exception as err:
        log.error("Failed to package files: %s", err)
        return None


def main():
    """Main orchestrator function."""
    parser = argparse.ArgumentParser(
        description="TPM Model Signing Orchestrator - Sign models for secure edge deployment"
    )
    parser.add_argument("model_path", help="Path to the model file to sign")
    parser.add_argument("algo", help="Signing algorithm to use", choices=["rsa", "ecc"], default="ecc")

    args = parser.parse_args()
    model_path = Path(args.model_path)

    # validate inputs
    if not model_path.exists():
        log.error("Model file not found: %s", model_path)
        return 1

    log.info("Orchestrator starting")
    log.info("Model: %s", model_path)
    log.info("Output directory: %s", OUTPUT_DIR)

    # initialize TPM operations
    tpm = TPMManualFlowOps(algorithm=args.algo)

    # 1. initialize TPM and keys
    if not tpm.setup():
        log.error("Failed to set up TPM and signing key. Aborting.")
        return 1
    log.info("TPM is ready for signing operations")

    # 2. sign the model
    result = tpm.sign_model(str(model_path))
    if not result:
        log.error("Failed to sign the model.")
        return 1
    signature_file, hash_file = result
    log.info("Model signing complete. Signature: %s, Hash: %s", signature_file, hash_file)

    # 3. get the public key
    public_key_file = tpm.get_public_key_path()
    if not public_key_file:
        log.error("Failed to get public key.")
        return 1
    log.info("Public key available at %s", public_key_file)

    # 4. package everything for edge deployment
    log.info("Packaging files for edge deployment")
    package_path = package_for_edge(model_path, signature_file, public_key_file, OUTPUT_DIR)
    if not package_path:
        log.error("Failed to package files for edge")
        return 1

    log.info("SUCCESS: Model signed and packaged at %s", package_path)
    return 0


def main_wrapper():
    """Wrapper function to add timing information."""
    start = datetime.now(timezone.utc)

    # redirect print to logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] [%(module)s] %(message)s",
        stream=sys.stdout,
    )

    result = main()

    end = datetime.now(timezone.utc)
    log.info("--------------------------------")
    log.info("Summary:")
    log.info("Start: %s", start)
    log.info("End: %s", end)
    log.info("Duration: %s milliseconds", (end - start).total_seconds() * 1000)
    log.info("Result: %s", "SUCCESS" if result == 0 else "FAILURE")

    return result


if __name__ == "__main__":
    sys.exit(main_wrapper())
