#!/usr/bin/env python3

import os
import subprocess
import sys
import argparse
import tempfile
import time

# Helper to run shell commands
def run(cmd, check=True):
    """Run a shell command and optionally exit on error."""
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        sys.exit(result.returncode)
    return result.stdout.strip()

def flush_transient_objects():
    """Flush all transient objects from the TPM to free up memory slots."""
    run("tpm2_flushcontext --transient-object", check=False)

# Detect whether we should expect swtpm (no physical TPM nodes found or explicit TCTI mentions swtpm)
def using_swtpm():
    tcti = os.environ.get("TPM2TOOLS_TCTI", "")
    if "swtpm" in tcti.lower():
        return True
    return not (os.path.exists("/dev/tpmrm0") or os.path.exists("/dev/tpm0"))

# Only ask for TPM2TOOLS_TCTI when swtpm is the expected TCTI
if "TPM2TOOLS_TCTI" not in os.environ and using_swtpm():
    print("Please set TPM2TOOLS_TCTI, e.g., export TPM2TOOLS_TCTI='swtpm:port=2321'")
    sys.exit(1)

# Function to generate hash and extend PCR
def hash_and_extend(info_file, pcr_index):
    if not os.path.exists(info_file):
        print(f"Error: info file {info_file} not found")
        sys.exit(1)
    hash_val = run(f"sha256sum {info_file} | awk '{{print $1}}'")
    print(f"Generated hash: {hash_val}")
    run(f"tpm2_pcrextend {pcr_index}:sha256={hash_val}")
    current_pcr = run(f"tpm2_pcrread sha256:{pcr_index}")
    print(f"PCR {pcr_index} after extend: {current_pcr}")
    return hash_val, current_pcr

# Function to create EK if not exists
def create_ek(ek_ctx):
    if not os.path.exists(ek_ctx):
        print("Creating EK...")
        run(f"tpm2_createek --ek-context {ek_ctx}")
    else:
        print("Using existing EK.")

# Function to create AK if not exists
def create_ak(ek_ctx, ak_ctx, ak_pub, algo="ecc"):
    if not os.path.exists(ak_ctx) or not os.path.exists(ak_pub):
        print("Creating AK...")
        if algo == "rsa":
            run(f"tpm2_createak --ek-context {ek_ctx} --ak-context {ak_ctx} "
                f"--key-alg rsa --hash-alg sha256 --signing-alg rsassa --public {ak_pub}")
        else:
            run(f"tpm2_createak --ek-context {ek_ctx} --ak-context {ak_ctx} "
                f"--key-alg ecc --hash-alg sha256 --signing-alg ecdsa --public {ak_pub}")
        # Note: --ak-context already saves the context to file, no need for tpm2_contextsave
    else:
        print("Using existing AK.")

# Function to generate nonce if not exists
def create_nonce(nonce_file):
    if not os.path.exists(nonce_file):
        print("Generating nonce...")
        run(f"echo -n 11223344 > {nonce_file}")
    else:
        print("Using existing nonce.")

# Function to generate TPM quote
def generate_quote(ak_ctx, ek_ctx, ak_pub, pcr_index, info_file, nonce_file, quote, sig):
    # Reset PCR before new quote
    run(f"tpm2_pcrreset {pcr_index}")
    hash_val, current_pcr = hash_and_extend(info_file, pcr_index)

    try:
        out = run(f"tpm2_quote --key-context {ak_ctx} --pcr-list sha256:{pcr_index} "
                  f"--message {quote} --signature {sig} --qualification {nonce_file}")
        print(out)
    except SystemExit:
        print("Existing AK cannot sign. Flushing transient objects and recreating AK...")
        flush_transient_objects()
        create_ak(ek_ctx, ak_ctx, ak_pub)
        out = run(f"tpm2_quote --key-context {ak_ctx} --pcr-list sha256:{pcr_index} "
                  f"--message {quote} --signature {sig} --qualification {nonce_file}")
        print(out)

    return quote, sig, current_pcr

def compute_expected_pcr(info_file):
    """
    Compute the expected PCR digest that would appear in a TPM quote.
    
    PCR extend: pcr_value = SHA256(old_pcr || hash_of_data)
    Starting from a reset PCR (all zeros for SHA256).
    
    The pcrDigest in a quote is SHA256 of all selected PCR values concatenated.
    Since we only select one PCR, pcrDigest = SHA256(pcr_value).
    """
    import hashlib
    # Get hash of the info file
    hash_obj = hashlib.sha256()
    with open(info_file, "rb") as f:
        while chunk := f.read(8192):
            hash_obj.update(chunk)
    info_hash = hash_obj.hexdigest()
    
    # PCR starts as all zeros (32 bytes for SHA256)
    initial_pcr = bytes(32)
    # PCR extend operation: new_value = SHA256(old_value || extend_value)
    extend_value = bytes.fromhex(info_hash)
    pcr_value = hashlib.sha256(initial_pcr + extend_value).digest()
    
    # The pcrDigest in the quote is SHA256 of all selected PCR values
    # Since we select only one PCR, it's SHA256(pcr_value)
    pcr_digest = hashlib.sha256(pcr_value).hexdigest()
    return pcr_digest.upper()

def verify_quote(ak_ctx, expected_info_file, pcr_index, quote, sig):
    """
    Verify a TPM quote by:
    1. Checking the signature on the original quote using the AK context
    2. Comparing the attested PCR value against the expected hash from info_file

    Parameters:
    - ak_ctx            : Attestation Key context file
    - expected_info_file: The info file containing expected process hashes
    - pcr_index         : PCR index used in the quote
    - quote             : Path to the quote message file
    - sig               : Path to the signature file
    """
    if not os.path.exists(quote) or not os.path.exists(sig):
        print(f"Error: quote ({quote}) or signature ({sig}) file not found")
        return False

    # Step 1: Verify the signature on the original quote using the AK context
    try:
        run(f"tpm2_verifysignature --key-context {ak_ctx} "
            f"--message {quote} --signature {sig} --hash-algorithm sha256")
        print("Signature verification passed")
    except SystemExit:
        print("Signature verification failed")
        return False

    # Step 2: Extract PCR digest from the quote and compare with expected value
    # Use tpm2_print to parse the quote structure
    try:
        quote_info = run(f"tpm2_print -t TPMS_ATTEST {quote}")
        print(f"Quote attestation info:\n{quote_info}")
    except SystemExit:
        print("Failed to parse quote")
        return False

    # Compute expected PCR digest from the info file
    expected_pcr = compute_expected_pcr(expected_info_file)
    print(f"Expected PCR digest (from {expected_info_file}): {expected_pcr}")

    # Extract the pcrDigest from quote_info
    # The PCR digest in the quote is a hash of all selected PCR values
    pcr_digest_line = None
    lines = quote_info.split('\n')
    for i, line in enumerate(lines):
        if 'pcrDigest' in line:
            # The digest value is typically on the next line or same line
            if ':' in line and line.split(':')[1].strip():
                pcr_digest_line = line.split(':')[1].strip()
            elif i + 1 < len(lines):
                pcr_digest_line = lines[i + 1].strip()
            break

    if pcr_digest_line:
        # Clean up the hex string (remove spaces, 0x prefix if present)
        attested_pcr = pcr_digest_line.replace(' ', '').replace('0x', '').upper()
        print(f"Attested PCR digest from quote: {attested_pcr}")

        if expected_pcr == attested_pcr:
            print("PCR value matches expected value - Quote verified successfully!")
            return True
        else:
            print("PCR value mismatch - Quote verification FAILED!")
            print(f"  Expected: {expected_pcr}")
            print(f"  Attested: {attested_pcr}")
            return False
    else:
        print("Could not extract PCR digest from quote")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TPM Quote Generation and Verification")
    parser.add_argument("--algo", choices=["rsa", "ecc"], default="ecc", help="Algorithm to use (rsa or ecc)")
    parser.add_argument("--fail", action="store_true", default=False, help="Intentionally fail the quote verification by generating random bytes as info file")
    args = parser.parse_args()
    tpm_dir = os.getcwd()
    ek_ctx = os.path.join(tpm_dir, "ek.ctx")
    ak_ctx = os.path.join(tpm_dir, "ak.ctx")
    ak_pub = os.path.join(tpm_dir, "ak.pub")
    nonce_file = os.path.join(tpm_dir, "nonce.dat")
    info_file = os.path.join(tpm_dir, "info.txt")
    quote = os.path.join(tpm_dir, "quote.out")
    sig = os.path.join(tpm_dir, "sig.out")
    pcr_index = 16

    # Flush transient objects once at startup to clear any stale loaded contexts
    flush_transient_objects()

    # Ensure EK, AK, nonce exist
    create_ek(ek_ctx)
    create_ak(ek_ctx, ak_ctx, ak_pub, args.algo)
    create_nonce(nonce_file)

    # Generate first quote
    print("\nGenerating first quote...")
    start = time.time()
    generate_quote(ak_ctx, ek_ctx, ak_pub, pcr_index, info_file, nonce_file, quote, sig)
    end = time.time()
    print(f"First quote generation took {end - start:.4f} seconds")

    print("\nVerifying the quote...")
    start = time.time()
    if args.fail:
        with tempfile.NamedTemporaryFile(delete=True) as tmp_info:
            print("Intentionally failing the quote verification by using random bytes as expected info file")
            tmp_info.write(os.urandom(64))
            tmp_info.flush()
            # Verify original quote against a different (random) expected info_file
            result = verify_quote(ak_ctx, tmp_info.name, pcr_index, quote, sig)
    else:
        # Verify the original quote against the expected info_file
        result = verify_quote(ak_ctx, info_file, pcr_index, quote, sig)
    end = time.time()
    print(f"Quote verification took {end - start:.4f} seconds")
    sys.exit(0 if result else 1)
 
