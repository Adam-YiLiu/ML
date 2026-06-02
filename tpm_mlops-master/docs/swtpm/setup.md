# Software-Based TPM Installation

## 1. Installing `libtpms`

`libtpms` is a C library providing the core emulation logic for TPM 1.2 & 2.0 specifications. It offers the minimal API needed by hypervisors to integrate a virtual TPM into a VM.

### Installation Steps

1.  **Install from apt:**

    ```sh
    sudo apt update
    sudo apt install libtpms-dev libtpms0 libtss2-tcti-libtpms0t64
    ```
    
---

## 2. Installing `swtpm`

`swtpm` acts as a daemon that uses `libtpms` to provide accessible TPM interfaces. It allows multiple clients or VMs to connect to distinct virtual TPM instances via TCP/Unix sockets or character devices (`/dev/vtpm*`).

### Installation Steps

1.  **Install from apt:**

    ```sh
    sudo apt install  swtpm
    ```

---

## 3. Installing IBM TPM2.0 TSS

The IBM TPM2.0 Trusted Software Stack (TSS) provides the user-space libraries (implementing TCG standards like SAPI, ESAPI, TCTI) and command-line utilities needed for applications to interact with a TPM 2.0 device, whether physical or emulated via `swtpm`.

### Installation Steps

1.  **Download and extract the TSS source code:**

    ```bash
    wget https://sourceforge.net/projects/ibmtpm20tss/files/latest/download -O ibmtss.tar.gz

    mkdir -p ~/tss && cd ~/tss
    tar -zxvf ../ibmtss.tar.gz
    ```

2.  **Build the utility tools:**
    This step compiles the command-line tools located in the `utils` subdirectory. These tools (`startup`, `pcrread`, `createprimary`, `sign`, etc.) will be used for testing.

    ```bash
    cd utils
    # Make sure build essentials and libssl-dev are installed
    # sudo apt-get install build-essential libssl-dev
    make -f makefiletpmc
    cd ~
    ```

    The compiled utilities will be available in the `~/tss/utils` directory. You might want to add this directory to your `$PATH` or invoke the tools using their full path (e.g., `~/tss/utils/startup`).

---

## 4. Running and Testing the Software TPM

### A. Starting the Emulator (`swtpm`)

1.  **Create a directory for the TPM state:**
    `swtpm` needs a directory to store persistent state like keys and NV data. We use `~/swtpm_state` for persistence across reboots.

    ```bash
    mkdir -p ~/swtpm_state
    ```

2.  **Start the `swtpm` socket server:**

    - `--tpmstate dir=...`: Specifies the directory for persistent state (`~/swtpm_state`).
    - `--tpm2`: Selects TPM 2.0 emulation.
    - `--ctrl type=tcp,port=2322`: Exposes a control interface on TCP port 2322 (e.g., for shutdown commands).
    - `--server type=tcp,port=2321`: Listens for standard TPM commands on TCP port 2321.
    - `--flags not-need-init`: Simplifies startup by indicating the TPM doesn't require an explicit initialization signal. You might need `sudo` if using low port numbers or specific device paths.

    ```bash
    swtpm socket \
      --tpmstate dir=~/swtpm_state \
      --tpm2 \
      --ctrl type=tcp,port=2322 \
      --server type=tcp,port=2321 \
      --flags not-need-init &
    ```

    _The `&` runs the process in the background. Note: The setup script adds a `sleep 2` after this command to allow the server a moment to initialize before clients connect._

### B. Setting Environment Variables for IBM TSS to communicate with SWTPM

```bash
export TPM_INTERFACE_TYPE=socsim
export TPM_SERVER_NAME=localhost
export TPM_SERVER_TYPE=raw
export TPM_COMMAND_PORT=2321
export TPM_PLATFORM_PORT=2322
```

### C. Basic TPM Operations using TSS Utilities

Once `swtpm` is running (Section 4.A) and the environment variables are set (Section 4.B), you can use the compiled IBM TSS utilities (from `~/tss/utils`) to interact with the simulated TPM.

**Important:** Run these commands from the `~/tss/utils` directory.

1.  **Prepare Test Data:**
    Create a directory and a simple test file.

    ```bash
    mkdir test
    # Create a file named 'aaa' inside 'test' with some content, e.g., 'aaaaaaaaa'
    echo "aaaaaaaaa" > test/aaa
    ```

2.  **Startup:**
    Sends the TPM2_Startup command.

    ```bash
    ./startup
    ```

3.  **PCR Operations:**
    Demonstrates reading, extending, and resetting a Platform Configuration Register (PCR). PCRs are used for storing measurements (hashes) that reflect the system state.

    ```bash
    # Read PCR 16
    ./pcrread -ha 16

    # Extend PCR 16 with the hash of the contents of 'test/aaa'
    ./pcrextend -ha 16 -if test/aaa

    # Read PCR 16 again to see the new value
    ./pcrread -ha 16

    # Reset PCR 16
    ./pcrreset -ha 16
    ```

4.  **Create Primary Key:**
    Creates a primary key in the Owner hierarchy (`-hi o`). Primary keys are derived from TPM secrets (seeds) and form the root of key hierarchies.

    ```bash
    ./createprimary -hi o
    # The command will output a handle (e.g., 80000000). Use this handle in subsequent commands.
    ```

5.  **Create and Load Standard Key:**
    Creates a standard signing key (`-st`) under the primary key (handle `80000000` assumed here, replace if different). The public (`-opu`) and private (`-opr`) portions are saved to files. Then, it loads this key back into the TPM for use.

    ```bash
    # Create the key (replace 80000000 if your primary key handle is different)
    ./create -hp 80000000 -st -opr test/pr -opu test/pb

    # Load the key back into the TPM (handle 80000001 is assumed, replace if different)
    ./load -hp 80000000 -ipu test/pb -ipr test/pr
    ```

6.  **Create External Keys (using OpenSSL):**
    Generate a standard RSA key pair using OpenSSL for comparison and use with import/verify commands.

    ```bash
    # Generate private key and self-signed certificate
    openssl req -x509 -newkey rsa:2048 -keyout test/private.pem -out test/certificate.pem -nodes -days 365 -subj "/C=GB/ST=London/L=London/O=Global Security/OU=IT Department/CN=test.oxford.com"

    # Extract public key from the private key
    openssl rsa -in test/private.pem -pubout -out test/public.pem
    ```

7.  **Import and Load External Key:**
    Imports the OpenSSL-generated private key into the TPM under the primary key (`-hp 80000000`) and loads it. The TPM never exposes the imported private key directly, but can use it.

    ```bash
    # Flush any potentially conflicting key handle before loading
    ./flushcontext -ha 80000001 # Use the handle from the './load' command

    # Import the PEM private key as an RSA signing key (-rsa -si)
    ./importpem -hp 80000000 -ipem test/private.pem -rsa -si -opu test/pub.bin -opr test/priv.bin

    # Load the imported key (handle 80000001 is assumed again)
    ./load -hp 80000000 -ipu test/pub.bin -ipr test/priv.bin
    ```

8.  **Sign Data:**
    Uses the loaded TPM key (handle `80000001`, the one created by `./load` or imported/loaded) to sign the contents of the test file (`test/aaa`) using SHA-256.

    ```bash
    ./sign -hk 80000001 -if test/aaa -halg sha256 -os test/sign.bin
    ```

9.  **Verify Signature:**
    Verifies the signature generated by the TPM. This can be done using either the public key exported from the TPM (`-hk`) or the corresponding external public key file (`-ipem`).

    ```bash
    # Verify using the external OpenSSL public key
    ./verifysignature -if test/aaa -is test/sign.bin -ipem test/public.pem

    # Verify using the TPM key handle directly
    ./verifysignature -if test/aaa -is test/sign.bin -hk 80000001
    ```

This sequence demonstrates basic TPM initialization, measurement handling (PCRs), key generation within the TPM, key import from external sources, signing, and verification.

# Installing and Securing an ML Model

## 1. Install a Lightweight ML Model

### Choose a Model

- MobileNetV2
- SqueezeNet
- ResNet18

### Install the Model on the VM

We'll be using ONNX as it has good cross-platform support and is easy to hash.

```sh
mkdir -p ~/ml_models && cd ~/ml_models
wget https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-7.onnx -O ~/ml_models/mobilenetv2-7.onnx
```

## 2. Set Up a Minimal Inference Environment

### Install ONNX Runtime

```sh
pip install onnxruntime
```

### Python Script for Basic Inference

```python
# infer.py
import onnxruntime as ort
import numpy as np

# load the model
session = ort.InferenceSession("~/ml_models/mobilenetv2-7.onnx")

# dummy input (MobileNet expects 1x3x224x224)
input_name = session.get_inputs()[0].name
dummy_input = np.random.rand(1, 3, 224, 224).astype(np.float32)

# run inference
outputs = session.run(None, {input_name: dummy_input})
print("Inference done. Output shape:", outputs[0].shape)
```

### Run it

```sh
python infer.py
```

## 3. Generate a Hash of the Model

1.  **Using OpenSSL:**

    ```sh
    cd ~/ml_models
    openssl dgst -sha256 mobilenetv2-7.onnx
    ```

2.  **Using TPM:**

    ```sh
    cd ~/ml_models
    tpm2_hash
    ```

# Automatic TPM Emulator and IBM TSS Startup

This section describes how to set up a shell script that:

1. Starts the `swtpm` emulator.
2. Exports the necessary environment variables for IBM TSS.
3. Runs the TSS `startup` utility.
4. Ensure it runs automatically at startup via a `systemd` service.

---

## 1. Create the Startup Script

Save the following as `/usr/local/bin/start_swtpm.sh` and make it executable:

```sh
#!/usr/bin/env bash
set -eou pipefail

# prepare swtpm persistent directory
STATE_DIR="${HOME}/swtpm_state"
mkdir -p "$STATE_DIR"

# launch swtpm
swtpm socket \
    --tmpstate dir="${STATE_DIR}" \
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

```sh
chmod +x /usr/local/bin/start_swtpm.sh
```

## 2. Create the systemd Service

Save the following as `/etc/systemd/system/swtpm-tss.service`:

```sh
[Unit]
Description=Start swtpm emulator and IBM TSS at boot
After=network.target

[Service]
Type=service
User=prathmesh
Environment=HOME=/home/prathmesh
ExecStart=/usr/local/bin/start_swtpm.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## 3. Enable and Start the Service

```sh
sudo systemctl daemon-reload
sudo systemctl enable swtpm-tss.service
sudo systemctl start swtpm-tss.service
sudo systemctl status swtpm-tss.service
```

Now, on every reboot, the TPM emulator and IBM TSS will be up and running automatically.

# 4. Install tpm2-tools

```sh
sudo apt update
sudo apt install tpm2-tools
```