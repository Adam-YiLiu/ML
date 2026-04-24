from __future__ import annotations

import logging
from typing import List, Optional
import shutil
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import openssl_ops
import swtpm_ops
import tpm_ops
import argparse
from constants import KEY_CONTEXT_PATH, PUBLIC_KEY_PATH, EDGE_PACKAGE_DIR, discover_model, signature_path_for

# Signature paths are derived dynamically from the model in the edge package.
# These module-level variables are set lazily by _init_model_paths() so that
# tamper_signature / restore_signature can reference them even when called via
# infer_secure.py (which imports main.py functions).
SIGNATURE_PATH: Path = Path()
SIGNATURE_BACKUP_PATH: Path = Path()


def _init_signature_paths(model_path: Path):
    """Set the module-level SIGNATURE_PATH from the given model file."""
    global SIGNATURE_PATH, SIGNATURE_BACKUP_PATH
    SIGNATURE_PATH = signature_path_for(model_path)
    SIGNATURE_BACKUP_PATH = SIGNATURE_PATH.with_suffix(".sig.bak")
from device_detection import determine_hashing_type, determine_inference_backend
from inference_utils import (
    create_session,
    load_labels,
    postprocess_output,
    preprocess_image,
    run_inference,
    run_inference_with_session,
)

log = logging.getLogger(__name__)


def tamper_signature():
    """Tamper with the signature file to simulate an attack."""
    log = logging.getLogger(__name__)
    if SIGNATURE_PATH is None or not SIGNATURE_PATH.exists():
        log.error("Signature file not found for tampering: %s", SIGNATURE_PATH)
        return False
    
    # Backup the original signature
    shutil.copy2(SIGNATURE_PATH, SIGNATURE_BACKUP_PATH)
    log.info("Backed up original signature to %s", SIGNATURE_BACKUP_PATH)
    
    # Tamper with the signature by flipping some bytes
    with open(SIGNATURE_PATH, "rb") as f:
        sig_data = bytearray(f.read())
    
    # Flip bytes in the middle of the signature
    if len(sig_data) > 10:
        for i in range(5, min(15, len(sig_data))):
            sig_data[i] ^= 0xFF  # XOR to flip all bits
    
    with open(SIGNATURE_PATH, "wb") as f:
        f.write(sig_data)
    
    log.info("Tampered signature file: %s", SIGNATURE_PATH)
    return True


def restore_signature():
    """Restore the original signature file from backup."""
    log = logging.getLogger(__name__)
    if SIGNATURE_BACKUP_PATH.exists():
        shutil.copy2(SIGNATURE_BACKUP_PATH, SIGNATURE_PATH)
        SIGNATURE_BACKUP_PATH.unlink()
        log.info("Restored original signature from backup")
        return True
    else:
        log.warning("No signature backup found to restore")
        return False


def verify_model_integrity(model_path: Path, use_swtpm: bool = True, algo: str = "ecc") -> bool:
    """Verify model integrity using TPM-based signature verification."""
    # Derive signature path from the model being verified
    sig_path = signature_path_for(model_path)
    if not sig_path.exists():
        log.error("Signature file not found: %s", sig_path)
        return False

    if not PUBLIC_KEY_PATH.exists():
        log.error("Public key not found at %s", PUBLIC_KEY_PATH)
        return False

    log.info("Verifying model: %s", model_path)
    log.info("Using signature: %s", sig_path)
    log.info("Using public key: %s", PUBLIC_KEY_PATH)

    if determine_hashing_type() == "tpm" or use_swtpm:
        if use_swtpm:
            return swtpm_ops.verify_model_signature(model_path, sig_path, PUBLIC_KEY_PATH, algo)
        else:
            return tpm_ops.verify_model_signature(model_path, sig_path, KEY_CONTEXT_PATH, algo)
    else:
        # openssl can detect signature type automatically. no need to specify algo
        return openssl_ops.verify_model_signature(model_path, sig_path, PUBLIC_KEY_PATH)


def integrity_check(model_path: Path, use_swtpm: bool = True, algo: str = "ecc") -> bool:
    """Main function to verify model integrity with a single model path argument."""
    # Check if model file exists
    if not model_path.exists():
        log.error("Model file not found: %s", model_path)
        return False

    # verify the model integrity
    log.info("Starting Model Verification")
    if verify_model_integrity(model_path, use_swtpm, algo):
        log.info("VALID - Model signature is authentic")
        return True
    else:
        log.info("INVALID - Model signature verification failed")
        return False


def _resolve_model_for_backend(model_path: Path, backend: str) -> Path:
    """Return the correct model file for the chosen backend.

    If the caller already passed the right file (e.g. an ``.xmodel`` for DPU)
    it is returned as-is.  Otherwise we try to discover a matching model in
    the edge package directory.
    """
    expected_ext = ".xmodel" if backend == "dpu" else ".onnx"

    # Already the right type?
    if model_path.suffix == expected_ext and model_path.exists():
        return model_path

    # Try discovering the correct model from the edge package
    discovered = discover_model(backend)
    if discovered is not None:
        log.info("Resolved model for %s backend: %s", backend, discovered)
        return discovered

    # Last resort – use whatever was given
    log.warning(
        "Could not find a %s model for %s backend – using %s as-is",
        expected_ext, backend, model_path,
    )
    return model_path


def main_batch(model_path: Path, image_dir: Path, check_integrity: bool = True,
               use_swtpm: bool = True, algo: str = "ecc", fail_verify: bool = False,
               exclude_images: Optional[List[str]] = None):
    """Load the model once and run inference on all .jpg images in a directory.

    Prints one JSON object per line to stdout for each image with per-image
    timing.  The integrity check (if enabled) is performed once before the
    batch.

    Parameters
    ----------
    exclude_images : list[str], optional
        If given, skip these filenames during batch inference.
        Otherwise all .jpg files in the directory are used.
    """
    import time as _time

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] [%(module)s] %(message)s",
        handlers=[
            logging.FileHandler("pipeline.log"),
            logging.StreamHandler(sys.stderr),   # keep stdout clean for JSON
        ]
    )

    backend = determine_inference_backend()
    inference_model_path = _resolve_model_for_backend(model_path, backend)
    if backend == "dpu" and inference_model_path.suffix != ".xmodel":
        raise ValueError(f"DPU backend requires an .xmodel file, but got {inference_model_path}")
    log.info("Inference backend: %s  model: %s", backend, inference_model_path)

    _init_signature_paths(inference_model_path)
    labels = load_labels()

    # -- integrity check (once) ---------------------------------------------
    if fail_verify and check_integrity:
        log.info("Tampering with signature to simulate verification failure...")
        tamper_signature()

    try:
        if check_integrity:
            int_start = datetime.now(timezone.utc)
            integrity_result = integrity_check(model_path, use_swtpm, algo)
            int_end = datetime.now(timezone.utc)
        else:
            int_start = int_end = datetime.now(timezone.utc)
            integrity_result = True
    finally:
        if fail_verify and check_integrity:
            restore_signature()

    integrity_summary = {
        "start": int_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "end": int_end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "duration": (int_end - int_start).total_seconds() * 1000,
        "result": "VALID" if integrity_result else "INVALID",
        "check_integrity": check_integrity,
        "algorithm": algo,
        "use_swtpm": use_swtpm,
    }

    if not integrity_result:
        log.error("Model integrity check failed. Abort inference")
        print(json.dumps({"integrity": integrity_summary, "inferences": None}))
        return integrity_summary, None

    # -- load model session once --------------------------------------------
    log.info("Creating inference session for backend %s...", backend)
    session = create_session(inference_model_path, backend=backend)

    # -- iterate images -----------------------------------------------------
    images = sorted(image_dir.glob("*.jpg"))
    if exclude_images:
        exclude_set = set(exclude_images)
        images = [img for img in images if img.name not in exclude_set]
    results = []
    for image_path in images:
        inf_start = datetime.now(timezone.utc)
        inf_start_ns = _time.time_ns()
        input_data = preprocess_image(image_path, backend=backend)
        inf_res = "ERR"
        try:
            log.info("Inferencing %s [backend=%s]", image_path, backend)
            output = run_inference_with_session(session, input_data)
            inf_res = postprocess_output(output, labels)
        except Exception as err:
            log.error(str(err))

        inf_end = datetime.now(timezone.utc)
        inf_duration_ms = (_time.time_ns() - inf_start_ns) / 1_000_000
        inference_summary = {
            "start": inf_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "end": inf_end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "duration": inf_duration_ms,
            "result": inf_res,
            "image": image_path.name,
        }
        results.append(inference_summary)

    # emit all results as a single JSON object to stdout
    print(json.dumps({"integrity": integrity_summary, "inferences": results}))
    return integrity_summary, results


def main_wrapper(model_path: Path, image_path: Path, check_integrity: bool = True, use_swtpm: bool = True, algo: str = "ecc", fail_verify: bool = False):
    """Wrapper function to add timing information."""
    # redirect print to logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] [%(module)s] %(message)s",
        handlers= [
            logging.FileHandler("pipeline.log"),
            logging.StreamHandler()
        ]
    )

    # Auto-detect inference backend (DPU on Kria, ONNX everywhere else)
    backend = determine_inference_backend()
    inference_model_path = _resolve_model_for_backend(model_path, backend)
    # If xmodel wasn't found, fall back to onnx backend
    if backend == "dpu" and inference_model_path.suffix != ".xmodel":
        raise ValueError(f"DPU backend requires an .xmodel file, but got {inference_model_path}")
    log.info("Inference backend: %s  model: %s", backend, inference_model_path)

    # Initialise signature paths based on the actual model being used
    _init_signature_paths(inference_model_path)

    labels = load_labels()
    
    # If fail_verify is set, tamper with the signature before verification
    if fail_verify and check_integrity:
        tamper_signature()

    try:
        if check_integrity:
            int_start = datetime.now(timezone.utc)
            integrity_result = integrity_check(model_path, use_swtpm, algo)
            int_end = datetime.now(timezone.utc)
        else:
            int_start = int_end = datetime.now(timezone.utc)
            integrity_result = True
    finally:
        # Always restore the signature after verification attempt
        if fail_verify and check_integrity:
            restore_signature()

    integrity_summary = {
        "start": int_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "end": int_end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "duration": (int_end - int_start).total_seconds() * 1000,
        "result": "VALID" if integrity_result else "INVALID",
        "check_integrity": check_integrity,
        "algorithm": algo,
        "use_swtpm": use_swtpm,
    }

    inf_res = "ERR"
    if not integrity_result:
        log.error("Model integrity check failed. Abort inference")
        return integrity_summary, None
    
    inf_start = datetime.now(timezone.utc)
    input_data = preprocess_image(image_path, backend=backend)
    try:
        log.info(f"Inferencing {image_path} [backend={backend}]")
        output = run_inference(inference_model_path, input_data, backend=backend)
        inf_res = postprocess_output(output, labels)
    except Exception as err:
        log.error(str(err))
    #if integrity_result:
    #    input_data = preprocess_image(image_path)
    #    try:
    #        log.info(f"Inferencing {image_path} ...")
    #        output = run_inference(model_path, input_data)
    #        inf_res = postprocess_output(output, labels)
    #    except Exception as err:
    #        log.error(str(err))
    #else:
    #    log.error("Model integrity check failed.")
    inf_end = datetime.now(timezone.utc)
    inference_summary = {
        "start": inf_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "end": inf_end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "duration": (inf_end - inf_start).total_seconds() * 1000,
        "result": inf_res,
        "image": image_path.name,
    }

    return integrity_summary, inference_summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IoT Device Model Inference with TPM Integrity Check")
    parser.add_argument("model_path", type=Path, help="Path to the ONNX model file")
    parser.add_argument("image_path", type=Path, nargs='?', default=None, help="Path to the input image file")
    parser.add_argument(
        "--no-integrity-check",
        action="store_true",
        dest="no_integrity_check",
        help="Skip the model integrity check (default false)",
    )
    parser.add_argument(
        "--no-swtpm",
        action="store_true",
        dest="no_use_swtpm",
        default=False,
        help="Do not use swtpm for TPM operations (default false)",
    )
    parser.add_argument(
        "--algo",
        type=str,
        choices=["rsa", "ecc"],
        default="ecc",
        help="Signing algorithm to use (default ecc)",
    )
    parser.add_argument(
        "--fail",
        action="store_true",
        dest="fail_verify",
        default=False,
        help="Tamper with signature to simulate verification failure (for testing)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        dest="verify_only",
        default=False,
        help="Only verify model integrity, skip inference",
    )
    parser.add_argument(
        "--batch-dir",
        type=Path,
        default=None,
        help="Directory of .jpg images for batch inference (load model once)",
    )
    parser.add_argument(
        "--exclude-images",
        nargs="*",
        default=None,
        help="Image filenames to exclude from batch inference in --batch-dir (default: none excluded)",
    )

    args = parser.parse_args()

    if args.verify_only:
        logging.basicConfig(
            level=logging.INFO,
            format="[%(levelname)s] [%(module)s] %(message)s",
            handlers=[
                logging.FileHandler("pipeline.log", mode="a"),
                logging.StreamHandler()
            ]
        )

        # Initialise signature paths from the model being verified
        _init_signature_paths(args.model_path)

        if args.fail_verify:
            tamper_signature()

        try:
            int_start = datetime.now(timezone.utc)
            result = integrity_check(
                args.model_path,
                use_swtpm=not args.no_use_swtpm,
                algo=args.algo
            )
            int_end = datetime.now(timezone.utc)
        finally:
            if args.fail_verify:
                restore_signature()

        summary = {
            "start": int_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "end": int_end.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "duration": (int_end - int_start).total_seconds() * 1000,
            "result": "VALID" if result else "INVALID",
            "algorithm": args.algo,
            "use_swtpm": not args.no_use_swtpm,
        }

        log.info("Integrity Check Summary: %s", json.dumps(summary))
        sys.exit(0 if result else 1)

    if args.image_path is None and args.batch_dir is None:
        parser.error("image_path or --batch-dir is required unless --verify-only is specified")

    log.info("Model path: %s", args.model_path)
    if args.batch_dir is not None:
        log.info("Dataset directory for batch inference: %s", args.batch_dir)
        log.info("Signing algorithm: %s", args.algo)
        main_batch(
            args.model_path,
            args.batch_dir,
            check_integrity=not args.no_integrity_check,
            use_swtpm=not args.no_use_swtpm,
            algo=args.algo,
            fail_verify=args.fail_verify,
            exclude_images=args.exclude_images,
        )
        sys.exit(0)

    integrity_summary, inference_summary = main_wrapper(
        args.model_path,
        args.image_path,
        check_integrity=not args.no_integrity_check,
        use_swtpm=not args.no_use_swtpm,
        algo=args.algo,
        fail_verify=args.fail_verify,
    )

    log.info("Integrity Check Summary: %s", json.dumps(integrity_summary))
    log.info("Inference Summary: %s", json.dumps(inference_summary))
