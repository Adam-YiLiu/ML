"""
Constants for the Model Signing Orchestrator.
"""

import os
from pathlib import Path

# base directories
BASE_DIR = Path(os.path.expanduser("~"))
TSS_MODEL_SEC_DIR = BASE_DIR / "tss_model_sec"
OPENSSL_KEYS_DIR = TSS_MODEL_SEC_DIR / "openssl_keys"
OPENSSL_CERTIFICATE_PATH = OPENSSL_KEYS_DIR / "cert.pem"
OPENSSL_PRIVATE_KEY_PATH = OPENSSL_KEYS_DIR / "priv.pem"
OPENSSL_PUBLIC_KEY_PATH = OPENSSL_KEYS_DIR / "pub.pem"
OUTPUT_DIR = TSS_MODEL_SEC_DIR / "orchestrator_output"

# TPM handles
TPM_HIERARCHY = "o"
TPM_PRIMARY_HANDLE = "80000000"
TPM_SIGNING_HANDLE = "80000001"

# TSS utilities directory (TPM tools location)
TSS_UTILS_DIR = BASE_DIR / "tss" / "utils"

os.makedirs(TSS_MODEL_SEC_DIR, exist_ok=True)
os.makedirs(OPENSSL_KEYS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
