# Hardware TPM Setup

## 1. Install Required Libraries

```sh
sudo apt update
sudo apt install -y tpm2-tools
```

## 2. Generate a Primary Key

Create a primary key in the TPM that will serve as the parent for other operations:

```sh
sudo tpm2_createprimary -C o -c primary.ctx
```

**Parameters:**

- `-C o`: Use owner hierarchy
- `-c primary.ctx`: Save primary key context to file

## 3. Import Your OpenSSL Key to TPM

### Convert OpenSSL Keys

Convert PEM format keys:

```sh
openssl pkey -in priv.pem -out priv.key
openssl rsa -pubin -in pub.pem -out pub.key
```

### Load External Key into TPM

Load the existing OpenSSL keys into the TPM:

```sh
sudo tpm2_loadexternal -C n -G rsa -u ~/tss_model_sec/openssl_keys/pub.key -r ~/tss_model_sec/openssl_keys/priv.key -c key.ctx
```

**Parameters:**

- `-C n`: Use NULL hierarchy (for external keys)
- `-u`: Path to public key file
- `-r`: Path to private key file
- `-c key.ctx`: Save key context for future operations

## 4. Verify Signature

Use the loaded key to verify a signature:

```sh
sudo tpm2_verifysignature -s ~/ml_models/mobilenetv2-7.sig -m ~/ml_models/mobilenetv2-7.sha256 -c key.ctx
```

**Parameters:**

- `-s`: Path to signature file
- `-m`: Path to message/hash file to verify
- `-c key.ctx`: Use the loaded key context

After this, you should be able to run TPM commands without sudo.

## Key Points

- **Primary Key**: Acts as a parent for TPM operations, stored in `primary.ctx`
- **External Key Loading**: Uses `tpm2_loadexternal` to import existing OpenSSL keys
- **Context Files**: `.ctx` files serve as handles to reference loaded keys
- **NULL Hierarchy**: External keys are loaded under NULL hierarchy (`-C n`)
- **Signature Verification**: Final step confirms the signature matches the message using the loaded key

## Troubleshooting

- **Permission Issues**: Add user to `tss` group to avoid sudo
- **Key Format Issues**: Use `openssl rsa -pubin` for public key conversion
- **Missing Options**: `tpm2_import` requires `-G` and `-i` flags; use `tpm2_loadexternal` for OpenSSL keys instead
