# SWTPM Startup on Boot Service

## SWTPM Startup Script

Save the following startup script in /usr/local/bin/start_swtpm.sh

```sh
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
export TPM_PLATFORM_PORT=232

# start IBM TSS
cd "${HOME}/tss/utils"
./startup
```

## SWTPM systemd Startup Service

Save the following startup service in /etc/systemd/system/swtpm-tss.service

```sh
[Unit]
Description=Start swtpm emulator and IBM TSS at boot
After=network.target

[Service]
Type=oneshot
User=csc8499
RemainAfterExit=yes
Environment=HOME=/home/csc8499
ExecStart=/usr/local/bin/start_swtpm.sh

[Install]
WantedBy=multi-user.target
```

## systemctl

Upon completing the previous steps:

1. Run `sudo systemctl daemon-reload`
2. Run `sudo systemctl enable swtpm-tss.service`
3. Run `sudo systemctl status swtpm-tss.service`
