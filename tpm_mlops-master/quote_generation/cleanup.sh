#!/bin/bash

# Cleanup script to remove generated TPM artifacts
# This is useful when moving to a new machine or resetting the TPM state.

echo "Cleaning up TPM context, keys, and quote files..."

# Flush TPM transient objects to free up slots
# This prevents "out of memory for object contexts" errors
if [ -e /dev/tpmrm0 ] || [ -e /dev/tpm0 ]; then
    echo "Hardware TPM detected, flushing transient objects..."
    tpm2_flushcontext --transient-object 2>/dev/null || true
elif [ -n "$TPM2TOOLS_TCTI" ]; then
    echo "Software TPM (swtpm) detected via TPM2TOOLS_TCTI, flushing transient objects..."
    tpm2_flushcontext --transient-object 2>/dev/null || true
else
    echo "Warning: No hardware TPM or TPM2TOOLS_TCTI found, skipping TPM flush."
fi

# Remove Contexts and Keys
rm -f ek.ctx ak.ctx ak.pub

# Remove Nonce
rm -f nonce.dat

# Remove Quote and Signature outputs
rm -f quote.out sig.out quote2.out sig2.out

echo "Cleanup complete."
