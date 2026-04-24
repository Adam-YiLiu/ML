import logging
import os
import subprocess
import hashlib
from pathlib import Path

from constants import PUBLIC_KEY_PATH
from utils import run_cmd

log = logging.getLogger(__name__)


def _compute_hash_file(file_path: Path) -> Path:
    """
    Compute double SHA256 hash of file and return the path to the hash file.
    
    This matches the TPM signing behavior: TPM sign command with -halg sha256
    hashes the input (which is already a hash), resulting in a double hash.
    """
    hash_path = file_path.with_suffix(".double.sha256")
    with open(hash_path, "wb") as hash_file:
        # First SHA256 (of the model file)
        sha256_first = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256_first.update(chunk)
        first_hash = sha256_first.digest()
        
        # Second SHA256 (what TPM does internally when signing)
        sha256_second = hashlib.sha256()
        sha256_second.update(first_hash)
        hash_file.write(sha256_second.digest())
    return hash_path


def _strip_tpm_header_to_der(sig_path: Path) -> Path:
    """
    Convert TPM ECDSA signature (raw R||S with headers) to DER format.
    
    TPM signature format for ECDSA P-256:
    - 6 bytes header
    - 32 bytes R
    - 2 bytes length prefix (00 20)
    - 32 bytes S
    
    OpenSSL expects DER-encoded ECDSA signature.
    """
    der_sig_path = sig_path.with_suffix(".der")
    
    with open(sig_path, "rb") as f:
        sig_data = f.read()
    
    # Skip 6-byte TPM header, extract R (32 bytes)
    r = sig_data[6:38]
    # Skip 2-byte length prefix (00 20), extract S (32 bytes)
    s = sig_data[40:72]
    
    # Convert R and S to DER format
    def int_to_der_int(value: bytes) -> bytes:
        """Convert a big-endian integer to DER INTEGER."""
        # Remove leading zeros but keep at least one byte
        value = value.lstrip(b'\x00') or b'\x00'
        # Add leading zero if high bit is set (to keep positive)
        if value[0] & 0x80:
            value = b'\x00' + value
        return b'\x02' + bytes([len(value)]) + value
    
    r_der = int_to_der_int(r)
    s_der = int_to_der_int(s)
    
    # SEQUENCE of R and S
    seq_content = r_der + s_der
    der_sig = b'\x30' + bytes([len(seq_content)]) + seq_content
    
    with open(der_sig_path, "wb") as f:
        f.write(der_sig)
    
    return der_sig_path


def _strip_tpm_header_rsa(sig_path: Path) -> Path:
    """
    Strip TPM header from RSA signature.
    
    TPM signature format for RSA-2048:
    - 6 bytes header (TPM2B structure: 2 bytes size + 4 bytes scheme info)
    - 256 bytes raw RSA signature
    
    OpenSSL expects raw RSA signature for verification.
    """
    raw_sig_path = sig_path.with_suffix(".raw")
    
    with open(sig_path, "rb") as f:
        sig_data = f.read()
    
    # Skip 6-byte TPM header, extract raw RSA signature (256 bytes for RSA-2048)
    raw_sig = sig_data[6:262]
    
    with open(raw_sig_path, "wb") as f:
        f.write(raw_sig)
    
    return raw_sig_path


def _detect_signature_type(sig_path: Path) -> str:
    """
    Detect whether the TPM signature is RSA or ECC based on file size.
    
    TPM signature sizes:
    - ECDSA P-256: ~72 bytes (6 header + 32 R + 2 length + 32 S)
    - RSA-2048: ~262 bytes (6 header + 256 raw signature)
    
    Returns 'rsa' or 'ecc'.
    """
    sig_size = sig_path.stat().st_size
    
    # RSA-2048 signature with TPM header is ~262 bytes
    # ECDSA P-256 signature with TPM header is ~72 bytes
    if sig_size > 200:
        return "rsa"
    else:
        return "ecc"


def verify_model_signature(
    model_path: Path,
    signature_path: Path,
    public_key_path: Path = PUBLIC_KEY_PATH,
) -> bool:
    """Verify the signature of a model file using OpenSSL.
    
    Supports both RSA-2048 and ECDSA P-256 signatures from TPM.
    The signature type is auto-detected based on file size.
    """
    hash_path = None
    processed_sig_path = None
    try:
        # Detect signature type
        sig_type = _detect_signature_type(signature_path)
        log.info("Detected signature type: %s", sig_type)
        
        hash_path = _compute_hash_file(model_path)
        log.info("Computed double SHA256 hash for %s at %s", model_path, hash_path)
        
        if sig_type == "ecc":
            processed_sig_path = _strip_tpm_header_to_der(signature_path)
            log.info("Converted TPM ECDSA signature to DER format at %s", processed_sig_path)
        else:  # RSA
            processed_sig_path = _strip_tpm_header_rsa(signature_path)
            log.info("Stripped TPM header from RSA signature at %s", processed_sig_path)
            
        verify_cmd = (
            f"openssl pkeyutl -verify -inkey {public_key_path} -pubin "
            f"-sigfile {processed_sig_path} -in {hash_path} "
            "-pkeyopt digest:sha256"
        )

        stdout, stderr, return_code = run_cmd(verify_cmd, tpm_cmd=True, check=False)

        if return_code == 0:
            log.info("Signature verification successful.")
            return True
        else:
            log.error("Signature verification failed. Stderr: %s", stderr.strip())
            log.error("Stdout: %s", stdout.strip())
            return False

    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        log.error("An error occurred during verification: %s", err)
        return False
    finally:
        if hash_path and hash_path.exists():
            os.remove(hash_path)
        if processed_sig_path and processed_sig_path.exists():
            os.remove(processed_sig_path)
