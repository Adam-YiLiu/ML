#!/usr/bin/env bash
set -eou pipefail

# prepare swtpm persistent directory
STATE_DIR="${HOME}/swtpm_state"
mkdir -p "$STATE_DIR"

# launch swtpm
swtpm socket \
    --tpmstate dir="${STATE_DIR}" \
    --tpm2 \
    --ctrl type=tcp,port=2322 \
    --server type=tcp,port=2321 \
    --flags not-need-init &

# let swtpm initialise
sleep 2

# set IBM TSS environment variables
export TPM_INTERFACE_TYPE=socsim
export TPM_SERVER_NAME=localhost
export TPM_SERVER_TYPE=raw
export TPM_COMMAND_PORT=2321
export TPM_PLATFORM_PORT=2322

# start IBM TSS
cd "${HOME}/tss/utils"
./startup

# create primary storage key (SRK) under owner hierarchy
# PRIMARY_PUB="${STATE_DIR}/primary.pub.pem"
# if [ ! -f "${PRIMARY_PUB}" ]; then
#   echo ">> Creating primary (SRK) under the owner hierarchy"
#   ./createprimary \
#     -hi o                 \  # “o” = owner hierarchy
#     -rsa                  \  # RSA key
#     -nalg sha256          \  # nameAlg
#     -halg sha256          \  # scheme hash
#     -opu "${STATE_DIR}/primary.pub"   \  # raw public
#     -opem "${PRIMARY_PUB}"             # PEM-formatted pub
# fi
