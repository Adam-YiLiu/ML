# Quote Generation

This directory contains scripts and resources for generating and verifying TPM quotes using `swtpm` (Software TPM). The process involves measuring system state (file hashes), extending PCRs, and generating a signed quote to attest to the system's integrity.

## Prerequisites

*   **TPM 2.0 Tools**: Ensure `tpm2-tools` is installed.
*   **Software TPM**: `swtpm` must be installed and running.
*   **Environment Variable**: Set `TPM2TOOLS_TCTI` to point to your swtpm instance.
    ```bash
    export TPM2TOOLS_TCTI='swtpm:port=2321'
    ```

## Files

*   `generatequote.py`: The main Python script that orchestrates the quote generation and verification process.
*   `generate_info.sh`: A shell script to generate the `info.txt` file by hashing running executables.
*   `info.txt`: Contains SHA256 hashes and paths of system binaries. This file is used as the input for PCR extension.
*   `*.ctx`, `*.pub`: TPM context and public key files generated during execution (`ek.ctx`, `ak.ctx`, `ak.pub`).

## Usage

### 0. Cleanup (Optional)

If you are running this on a new machine, using a different TPM instance, or want to reset the TPM state, run the cleanup script to remove old keys and contexts.

```bash
./cleanup.sh
```

### 1. Generate System Information

First, generate the `info.txt` file which captures the state of currently running processes for specific users (root, daemon, etc.).

```bash
./generate_info.sh > info.txt
```

### 2. Generate and Verify Quote

Run the `generatequote.py` script. This script performs the following steps:

1.  **Key Setup**: Creates an Endorsement Key (EK) and Attestation Key (AK) if they don't exist.
2.  **Nonce Creation**: Generates a nonce for freshness.
3.  **PCR Extension**:
    *   Resets PCR 16.
    *   Calculates the hash of `info.txt`.
    *   Extends PCR 16 with this hash.
4.  **Quote Generation**: Generates a TPM quote over PCR 16 using the AK and nonce.
5.  **Verification**: Verifies the generated quote to ensure the signature is valid and corresponds to the expected PCR state.

```bash
python3 generatequote.py
```

## Script Details

### `generatequote.py`

*   **`hash_and_extend(info_file, pcr_index)`**: Hashes the `info.txt` file and extends the specified PCR (default 16).
*   **`create_ek(ek_ctx)`**: Creates the Endorsement Key context.
*   **`create_ak(ek_ctx, ak_ctx, ak_pub)`**: Creates the Attestation Key context and public key.
*   **`generate_quote(...)`**: Generates the quote using `tpm2_quote`.
*   **`verify_quote(...)`**: Verifies the quote using `tpm2_verifysignature`.

### `generate_info.sh`

Scans for processes owned by `root`, `daemon`, `messagebus`, `systemd-network`, or `nobody`. It then calculates the SHA256 hash of the executable for each unique process found.
