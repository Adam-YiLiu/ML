#!/bin/bash

set -e

export TPM2TOOLS_TCTI='swtpm:port=2321'

# Use swtpm for model validation and quote generation, leave variable empty for hardware TPM (if available)
# Note that the model deployment still uses swtpm for signing
SWTPM="--use-swtpm"
#SWTPM=""

# Collect power from Tasmota smart plug via polling on HTTP (Leave variable empty to skip power collection)
#COLLECT_POWER="--collect-power"
COLLECT_POWER=""

# Number of runs per test variant
NUM_RUNS=10

# ---------------------------------------------------------------------------
# Model selection: auto-detect Kria DPU or fall back to ONNX
# On a Kria board with DPU we sign & deploy the pre-compiled xmodel from the
# Vitis AI Model Zoo.  On any other device we use the ONNX model.
# ---------------------------------------------------------------------------
if [ -e /dev/dpu ] || [ -e /dev/fpga0 ] || [ -d /sys/class/xrt ]; then
    MODEL_PATH="$HOME/ml_models/mobilenet_v2_1_4_224_tf.xmodel"
    echo "Kria DPU detected – using xmodel: $MODEL_PATH"
else
    MODEL_PATH="$HOME/ml_models/mobilenetv2-7.onnx"
    echo "No DPU detected – using ONNX model: $MODEL_PATH"
fi

if [ ! -f "$MODEL_PATH" ]; then
    echo "ERROR: Model file not found at $MODEL_PATH"
    exit 1
fi

function cleanup_quotes {
    echo "Cleaning up existing quote files..."
    pushd . > /dev/null
    cd ../../quote_generation
    ./cleanup.sh
    popd > /dev/null
}

echo "Clearing up existing logs..."
rm -rf logs

echo "Reset dataset to baseline integrity state..."
pushd . > /dev/null
cd ../../data_hashing
python3 hash_integrity.py --setup-only
popd > /dev/null

cleanup_quotes
echo "Starting test runs..."
echo

echo "=== Running infer_insecure.py ==="
echo "Removing existing tss_model_sec directory..."
rm -rf ~/tss_model_sec
# Still need to sign the model just to prepare the model
echo "Redeploying model with ECC signature..."
pushd . > /dev/null
cd ../orchestrator
python3 main.py "$MODEL_PATH" ecc
popd > /dev/null
echo "Model ready. Sleeping for cleaner performance metrics..."
sleep 3

function run_insecure {
    for i in $(seq 1 $1); do
        echo "Run $i/$1 - infer_insecure.py"
        rm -f pipeline.log
        python3 infer_insecure.py $COLLECT_POWER
        if [ $i -lt $1 ]; then
            echo "Sleeping for 60 seconds..."
            sleep 60
        fi
    done
}

run_insecure $NUM_RUNS
echo "Sleeping for 60 seconds..."
sleep 60
echo

# Function to run a test permutation
function run_permutation {
    local algo=$1
    local fail_hash=$2
    local fail_verify=$3
    local fail_quote=$4
    local runs=$5
    
    # Build description and flags
    local desc="infer_secure.py --algo $algo"
    local flags="--algo $algo"
    
    if [ "$fail_hash" = "true" ]; then
        desc="$desc --fail-hash"
        flags="$flags --fail-hash"
    fi
    if [ "$fail_verify" = "true" ]; then
        desc="$desc --fail-verify"
        flags="$flags --fail-verify"
    fi
    if [ "$fail_quote" = "true" ]; then
        desc="$desc --fail-quote"
        flags="$flags --fail-quote"
    fi
    
    echo "=== Running $desc $SWTPM ==="
    
    for i in $(seq 1 $runs); do
        echo "Run $i/$runs - $desc $SWTPM"
        rm -f pipeline.log
        python3 infer_secure.py $flags $SWTPM $COLLECT_POWER
        if [ $i -lt $runs ]; then
            echo "Sleeping for 60 seconds..."
            sleep 60
        fi
    done
    
    echo "Sleeping for 60 seconds..."
    sleep 60
    echo
    cleanup_quotes
}

# Run all permutations for RSA algorithm
echo "=== Setting up RSA model ==="
echo "Removing existing tss_model_sec directory..."
rm -rf ~/tss_model_sec
echo "Redeploying model with RSA signature..."
pushd . > /dev/null
cd ../orchestrator
python3 main.py "$MODEL_PATH" rsa
popd > /dev/null
echo "Model ready. Sleeping for cleaner performance metrics..."
sleep 10

# RSA permutations: only test each failure mode individually (workflow stops on first failure)
# 1. Happy path   2. fail_quote   3. fail_verify   4. fail_hash
run_permutation "rsa" "false" "false" "false" $NUM_RUNS
run_permutation "rsa" "false" "false" "true"  $NUM_RUNS
run_permutation "rsa" "false" "true"  "false" $NUM_RUNS
run_permutation "rsa" "true"  "false" "false" $NUM_RUNS

# Run all permutations for ECC algorithm
echo "=== Setting up ECC model ==="
echo "Removing existing tss_model_sec directory..."
rm -rf ~/tss_model_sec
echo "Redeploying model with ECC signature..."
pushd . > /dev/null
cd ../orchestrator
python3 main.py "$MODEL_PATH" ecc
popd > /dev/null
echo "Model ready. Sleeping for cleaner performance metrics..."
sleep 10

# ECC permutations: only test each failure mode individually (workflow stops on first failure)
# 1. Happy path   2. fail_quote   3. fail_verify   4. fail_hash
run_permutation "ecc" "false" "false" "false" $NUM_RUNS
run_permutation "ecc" "false" "false" "true"  $NUM_RUNS
run_permutation "ecc" "false" "true"  "false" $NUM_RUNS
run_permutation "ecc" "true"  "false" "false" $NUM_RUNS

echo
echo "All test runs completed!"
