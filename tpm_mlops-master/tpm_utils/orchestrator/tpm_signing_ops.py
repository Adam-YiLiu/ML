"""TPM Signing Operations."""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple, Union

from constants import (
    OPENSSL_CERTIFICATE_PATH,
    OPENSSL_PRIVATE_KEY_PATH,
    OPENSSL_PUBLIC_KEY_PATH,
    OUTPUT_DIR,
    TPM_HIERARCHY,
    TPM_PRIMARY_HANDLE,
    TSS_UTILS_DIR,
)

log = logging.getLogger(__name__)


class TPMManualFlowOps:
    """Implements TPM signing workflow."""

    def __init__(self, algorithm: str = "ecc"):
        self.algorithm = algorithm
        self.tss_utils_path = TSS_UTILS_DIR
        self.output_dir = OUTPUT_DIR

        self.tpm_keys_dir_name = "tpm_import_keys"
        self.tpm_keys_dir_path = os.path.join(
            self.tss_utils_path, self.tpm_keys_dir_name
        )
        os.makedirs(self.tpm_keys_dir_path, exist_ok=True)

        self.pem_cert_path = OPENSSL_CERTIFICATE_PATH
        self.pem_priv_key_path = OPENSSL_PRIVATE_KEY_PATH
        self.pem_pub_key_path = OPENSSL_PUBLIC_KEY_PATH

        # paths for TPM imported key blobs, inside the new directory
        self.tpm_pub_blob_path = os.path.join(
            self.tpm_keys_dir_path, "imported_pub.bin"
        )
        self.tpm_priv_blob_path = os.path.join(
            self.tpm_keys_dir_path, "imported_priv.bin"
        )

        self.primary_key_handle = TPM_PRIMARY_HANDLE
        self.loaded_signing_key_handle = None

    def setup(self) -> bool:
        """Main setup function to prepare TPM and import the signing key."""
        if not self.ensure_openssl_keys_exist():
            return False

        self._cleanup_transient_state()

        if not self._ensure_primary_key():
            return False

        if not self._import_and_load_signing_key():
            return False

        return True

    def ensure_openssl_keys_exist(self) -> bool:
        """
        Checks if the OpenSSL key pair exists. If not, generates them.
        """
        if os.path.exists(self.pem_priv_key_path) and os.path.exists(
            self.pem_pub_key_path
        ):
            log.info("Found existing OpenSSL keys.")
            return True

        log.info("OpenSSL keys not found. Generating new key pair")

        subj = "/C=GB/ST=England/L=Newcastle upon Tyne/O=Newcastle University/OU=CSC8499/CN=prathmeshnaik"

        if self.algorithm.lower() == "rsa":
            gen_key_cmd = [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(self.pem_priv_key_path),
                "-out",
                str(self.pem_cert_path),
                "-nodes",
                "-days",
                "365",
                "-subj",
                subj,
            ]
        else:  # ECC
            gen_key_cmd = [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:prime256v1",
                "-keyout",
                str(self.pem_priv_key_path),
                "-out",
                str(self.pem_cert_path),
                "-nodes",
                "-days",
                "365",
                "-subj",
                subj,
            ]

        _, err, code = self._run_openssl_command(gen_key_cmd)
        if code != 0:
            log.error("Failed to generate OpenSSL private key. Stderr: %s", err)
            return False
        log.info(
            "Successfully generated new OpenSSL private key at: %s",
            self.pem_priv_key_path,
        )


        extract_pub_cmd = []
        if self.algorithm.lower() == "rsa":
            extract_pub_cmd = [
                "openssl",
                "rsa",
                "-in",
                str(self.pem_priv_key_path),
                "-pubout",
                "-out",
                str(self.pem_pub_key_path),
            ]
        else:  # ECC
            extract_pub_cmd = [
                "openssl",
                "ec",
                "-in",
                str(self.pem_priv_key_path),
                "-pubout",
                "-out",
                str(self.pem_pub_key_path),
            ]
            
        _, err, code = self._run_openssl_command(extract_pub_cmd)
        if code != 0:
            log.error("Failed to extract OpenSSL public key. Stderr: %s", err)
            return False
        log.info("Successfully extracted public key at: %s", self.pem_pub_key_path)

        return True

    def _cleanup_transient_state(self):
        """Flushes known transient handles to ensure a clean start."""
        log.info("Flushing known transient handles (80000000, 80000001, 80000002)")
        for handle in ["80000000", "80000001", "80000002"]:
            self._run_tpm_command(["./flushcontext", "-ha", handle])

    def _ensure_primary_key(self) -> bool:
        """Ensures that primary key is loaded."""
        log.info("Ensuring primary key is loaded at handle %s", self.primary_key_handle)
        cmd_create = [
            "./createprimary",
            "-hi",
            TPM_HIERARCHY,
        ]
        out, err, code = self._run_tpm_command(cmd_create)
        if code != 0:
            log.error(
                "Failed to create or load the primary key at handle %s.",
                self.primary_key_handle,
            )
            log.error("Stdout from createprimary: %s", out)
            log.error("Stderr from createprimary: %s", err)
            return False
        log.info(
            "Successfully created or loaded primary key at handle %s.",
            self.primary_key_handle,
        )
        return True

    def _import_and_load_signing_key(self) -> bool:
        """Imports existing OpenSSL private key and loads it into the TPM."""
        if not os.path.exists(self.pem_priv_key_path):
            log.error("OpenSSL private key not found at: %s", self.pem_priv_key_path)
            return False

        log.info(
            "Importing OpenSSL private key from %s into TPM", self.pem_priv_key_path
        )
        temp_pem_priv_key_path = os.path.join(
            self.tpm_keys_dir_path, os.path.basename(self.pem_priv_key_path)
        )
        shutil.copy(self.pem_priv_key_path, temp_pem_priv_key_path)

        pem_priv_key_relative = os.path.relpath(
            temp_pem_priv_key_path, self.tss_utils_path
        )
        tpm_pub_blob_relative = os.path.join(
            self.tpm_keys_dir_name, os.path.basename(self.tpm_pub_blob_path)
        )
        tpm_priv_blob_relative = os.path.join(
            self.tpm_keys_dir_name, os.path.basename(self.tpm_priv_blob_path)
        )

        if self.algorithm.lower() == "rsa":
            import_cmd = [
                "./importpem",
                "-hp",
                self.primary_key_handle,
                "-ipem",
                pem_priv_key_relative,
                "-rsa",
                "-si",
                "-opu",
                tpm_pub_blob_relative,
                "-opr",
                tpm_priv_blob_relative,
            ]
        else:  # ECC
            import_cmd = [
                "./importpem",
                "-hp",
                self.primary_key_handle,
                "-ipem",
                pem_priv_key_relative,
                "-ecc",
                "-si",
                "-opu",
                tpm_pub_blob_relative,
                "-opr",
                tpm_priv_blob_relative,
            ]
        _, err, code = self._run_tpm_command(import_cmd)
        if code != 0:
            log.error("Failed to import PEM key into TPM. Stderr: %s", err)
            return False

        # Load the newly created blobs
        log.info("Loading imported key into TPM")
        load_cmd = [
            "./load",
            "-hp",
            self.primary_key_handle,
            "-ipu",
            tpm_pub_blob_relative,
            "-ipr",
            tpm_priv_blob_relative,
        ]
        out, err, code = self._run_tpm_command(load_cmd)
        if code != 0:
            log.error("Failed to load imported key blobs. Stderr: %s", err)
            return False

        match = re.search(r"Handle\s+(80[0-9a-fA-F]{6})", out)
        if not match:
            log.error("Could not parse transient handle from 'load' output.")
            return False

        self.loaded_signing_key_handle = match.group(1)
        log.info(
            "Signing key loaded into transient handle %s",
            self.loaded_signing_key_handle,
        )
        return True

    def sign_model(self, model_path: str) -> Optional[Tuple[str, str]]:
        """
        Hashes a model and signs the hash with the loaded TPM key.
        """
        if not self.loaded_signing_key_handle:
            log.error("Cannot sign: No signing key is loaded.")
            return None

        log.info("Computing SHA-256 hash of model")
        hash_file_path = self._compute_hash(model_path)
        if not hash_file_path:
            return None

        log.info("Signing hash %s with TPM", hash_file_path)
        model_filename = os.path.splitext(os.path.basename(model_path))[0]
        sig_file_path = os.path.join(self.output_dir, f"{model_filename}.sig")

        try:
            hash_relative_path = os.path.relpath(hash_file_path, self.tss_utils_path)
            sig_relative_path = os.path.relpath(sig_file_path, self.tss_utils_path)
        except ValueError:
            log.error("Could not compute relative paths for signing.")
            return None

        if self.algorithm.lower() == "rsa":
            sign_cmd = [
                "./sign",
                "-hk",
                self.loaded_signing_key_handle,
                "-if",
                hash_relative_path,
                "-halg",
                "sha256",
                "-os",
                sig_relative_path,
            ]
        else:  # ECC
            sign_cmd = [
                "./sign",
                "-hk",
                self.loaded_signing_key_handle,
                "-if",
                hash_relative_path,
                "-halg",
                "sha256",
                "-scheme",
                "ecdsa",
                "-os",
                sig_relative_path,
            ]
        _, err, code = self._run_tpm_command(sign_cmd)
        if code != 0:
            log.error("Failed to sign hash with TPM. Stderr: %s", err)
            return None

        log.info("Signature created: %s", sig_file_path)
        return sig_file_path, hash_file_path

    def get_public_key_path(self) -> Optional[Union[str, Path]]:
        """Returns the path to the pre-existing public PEM key."""
        if not os.path.exists(self.pem_pub_key_path):
            log.error("OpenSSL public key not found at: %s", self.pem_pub_key_path)
            return None
        return self.pem_pub_key_path

    def _compute_hash(self, model_path: str) -> Optional[str]:
        """Computes and saves the SHA-256 hash of a file."""
        model_filename = os.path.splitext(os.path.basename(model_path))[0]
        hash_file_path = os.path.join(self.output_dir, f"{model_filename}.sha256")
        cmd = [
            "openssl",
            "dgst",
            "-sha256",
            "-binary",
            "-out",
            hash_file_path,
            model_path,
        ]
        _, err, code = self._run_openssl_command(cmd)
        if code != 0:
            log.error("Failed to compute hash. Stderr: %s", err)
            return None
        return hash_file_path

    def _run_tpm_command(self, command: List[str]) -> Tuple[str, str, int]:
        return self._run_command(command, cwd=self.tss_utils_path)

    def _run_openssl_command(self, command: List[str]) -> Tuple[str, str, int]:
        return self._run_command(command, cwd=None)

    def _run_command(
        self, command: List[str], cwd: Optional[Union[str, Path]]
    ) -> Tuple[str, str, int]:
        """Run a command."""
        try:
            log.debug("Running command: %s", " ".join(command))
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate()
            log.debug("Command finished with exit code %s", process.returncode)
            if stderr:
                log.debug("stderr:\n%s", stderr)
            return stdout, stderr, process.returncode
        except FileNotFoundError:
            log.error("Command not found: %s.", command[0])
        except Exception as err:
            log.error("An unexpected error occurred: %s", err)

        return "", "Client-side error", -1
