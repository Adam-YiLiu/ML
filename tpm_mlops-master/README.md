## Goal

Secure ML pipeline leveraging TPM technology for:
- Dataset integrity verification via cryptographic hashing
- Model signing and secure deployment
- Edge device inference with TPM/swtpm-backed verification
- System integrity validation through quote generation

## Project Structure

- **`data_hashing/`** - Dataset integrity verification
- **`tpm_utils/orchestrator/`** - Model signing and deployment preparation
- **`tpm_utils/iot_devices/`** - Edge device inference with cryptographic verification
- **`quote_generation/`** - System integrity attestation
- **`telemetry/`** - Performance and resource monitoring (Prometheus + Grafana)
- **`power_consumption/`** - Power measurement for IoT/edge devices
- **`docs/`** - Platform-specific setup guides ([swtpm/setup.md](docs/swtpm/setup.md) - start here)
- **`evaluation/`** - Performance analysis notebooks

## Quick Start

### 1. Setup (You only need to do this once)
Follow [docs/swtpm/setup.md](docs/swtpm/setup.md) to install swtpm, IBM TPM2.0 TSS, ONNX Runtime, and download MobileNetV2 model.

### 2. Create Python Virtual Environment
```bash
cd tpm_utils

# For standard Linux systems
python3 -m venv .venv

# For Kria boards (include Vitis AI packages)
python3 -m venv --system-site-packages .venv

source .venv/bin/activate
pip install --upgrade pip
pip install -r orchestrator/requirements.txt
pip install -r iot_devices/requirements.txt
```

### 3. Start Software TPM
```bash
./services/startup/start_swtpm.sh
```
> [!IMPORTANT]
> Always ensure swtpm is running before executing TPM operations. Run this script if you encounter TPM connection errors.

### 4. Start Monitoring Stack (Optional)
```bash
cd telemetry
docker-compose up -d
```
Access Grafana at http://localhost:3000 (admin/admin) to visualize metrics from Prometheus and Node Exporter.

### 5. Run Automated Test Suite
The [tpm_utils/iot_devices/run_test.sh](tpm_utils/iot_devices/run_test.sh) script automates the complete pipeline:
```bash
cd tpm_utils/iot_devices
./run_test.sh
```
This script:
- Auto-detects hardware (Kria DPU or standard ONNX)
- Resets dataset integrity state
- Signs models with RSA and ECC algorithms
- Runs insecure and secure inference modes
- Tests all failure scenarios (hash/verify/quote failures)
- Generates performance logs

Configuration options are available at the top of the script for customizing test parameters.

### 6. Logs

The logs will be available in tpm_utils/iot_devices/logs. There are 3 types of logs.

* CPU/Memory/Power usage in a time series CSV
* Time taken per sub-task in a time series CSV
    * The filename have `summary` in its name
* Raw text logs
    * The file extension ends in `.log`

Description of the filename:

* insecure/secure - Whether insecure or secure workflow is used.
* ecc/rsa - If the model is signed with ECC or RSA
* failhash - Hash integrity is intentionally failing
* failquote - Quote verification is intentionally failing
* failverify - Model signature verification is intentionally failing
* nofail - No failure, the normal workflow

### Manual Operations
**Sign a model:**
```bash
cd tpm_utils/orchestrator
python3 main.py ~/ml_models/mobilenetv2-7.onnx ecc  # or rsa
```

**Single image inference:**
```bash
cd tpm_utils/iot_devices
python3 main.py ~/tss_model_sec/orchestrator_output/edge_package/mobilenetv2-7.onnx ../../data_hashing/original_images/1.jpg
```

## Workflow

**Model Signing:** Orchestrator signs ML models with TPM-backed keys (RSA/ECC) → generates deployment package

**Edge Inference:** IoT devices verify model signature → validate dataset integrity → generate system quote → run inference

## Supported Platforms

- Linux with swtpm (recommended for development)
- Raspberry Pi with hardware TPM
- AMD Kria with TPM/DPU
- Jetson Orin with swtpm (GPU-accelerated)
- Standard x86/x64 systems

## Key Technologies

- **TPM/swtpm** - Hardware or software-based trusted computing
- **OpenSSL** - Cryptographic operations
- **Python 3** - Core implementation
- **ONNX Runtime** - ML inference
- **Prometheus + Grafana** - Monitoring (via docker-compose)
