# Orchestrator - TPM Model Signing

## Overview

Orchestrator workflow:

1.  **TPM State Reset**: Clears any stale transient handles from previous runs to ensure a clean state.
2.  **Primary Key Creation**: Ensures a primary key exists in the TPM's owner hierarchy, creating it if necessary.
3.  **OpenSSL Key Import**: Imports a pre-existing OpenSSL-generated RSA private key into the TPM under the primary key.
4.  **Model Hashing**: Computes a SHA-256 hash of the input model file.
5.  **TPM Signing**: Uses the imported key within the TPM to sign the model hash.
6.  **Packaging**: Creates a deployment-ready package containing the model, its signature, and the public key needed for verification.

## Files

- `main.py` - The main entrypoint for the orchestrator.
- `tpm_signing_ops.py` - TPM operations.
- `constants.py` - Defines all essential paths, TPM handles, and file names.

## Usage

The script is run from the command line, with the path to the model file as the sole argument.

**Prerequisites**:

- The script expects to be run from the `tss/utils` directory where the `IBM TPM 2.0 TSS` binaries are located.
- An OpenSSL key pair must already exist in the location defined by `OPENSSL_PRIVATE_KEY_PATH` and `OPENSSL_PUBLIC_KEY_PATH` in `constants.py`. If it doesn't a key pair is created at runtime.

```sh
python3 ~/path/to/orchestrator/main.py ~/path/to/models/model.onnx
```

## Output Structure

The orchestrator generates files in the `~/tss_model_sec/` directory.

```
~/tss_model_sec/
├── orchestrator_output/
│   ├── mobilenetv2-7.sha256    # binary hash of the model
│   ├── mobilenetv2-7.sig       # TPM-generated signature of the hash
│   └── edge_package/
│       ├── mobilenetv2-7.onnx  # the original model, copied for deployment
│       ├── mobilenetv2-7.sig   # the signature, copied for deployment
│       └── public.pem          # the public key, copied for deployment
└── openssl_keys/
    ├── priv.pem                # private key
    └── pub.pem                 # public key
```

## TPM Workflow Details

The orchestrator script automates the following `IBM TPM 2.0 TSS` and `openssl` commands:

### 1. State Cleanup & Key Setup

```sh
# flush known transient handles to prevent conflicts and 'out of memory' errors
./flushcontext -ha 80000000
./flushcontext -ha 80000001
./flushcontext -ha 80000002

# create a primary key under the owner hierarchy. Idempotent.
./createprimary -hi o
```

### 2. Key Import and Loading

```sh
# import the pre-existing OpenSSL private key into the TPM.
# this creates TPM-specific public/private "blobs" in a temporary directory.
./importpem -hp 80000000 -ipem tpm_import_keys/ossl_priv.pem -rsa -si -opu tpm_import_keys/imported_pub.bin -opr tpm_import_keys/imported_priv.bin

# load the imported key blobs into a transient handle (e.g., 80000001) for use.
./load -hp 80000000 -ipu tpm_import_keys/imported_pub.bin -ipr tpm_import_keys/imported_priv.bin
```

### 3. Model Signing

```sh
# compute SHA-256 hash of the model file
openssl dgst -sha256 -binary -out model.sha256 model.onnx

# sign the hash using the loaded transient handle
./sign -hk 80000001 -if model.sha256 -halg sha256 -os model.sig
```

## Requirements

- **SWTPM TPM 2.0**: A software simulator (`swtpm`) set up and running as a service.
- **IBM TPM 2.0 TSS**: IBM's TSS tools, expected to be in `~/tss/utils/`.
- **OpenSSL**: For hashing and key management.
- **Python 3.9+**: With the `pathlib` module.

## Edge Deployment

The `edge_package/` directory contains everything needed for an edge device to verify and use the model.

### Verification on Edge Device

1.  Copy the contents of `edge_package/` to the edge device.
2.  Run the verification script provided by the `iot_devices` module.

```sh
# Example verification command on the edge device
python -m iot_devices.main /path/to/model.onnx
```
