# Data Hashing & Integrity Verification

This directory contains scripts and data for verifying the integrity of image datasets using SHA-256 hashing. It simulates a scenario where image data and hash records might be distributed and need to be audited for tampering.

## Overview

The `hash_integrity.py` script performs three main functions:

1.  **Baseline Creation**: Establishes a "Ground Truth" by hashing a trusted set of images.
2.  **Verification**: Checks a second set of images (e.g., transferred or downloaded files) against the trusted baseline to ensure they haven't been modified.
3.  **Tampering Detection**: Analyzes a specific hash record file (simulating a potentially untrusted or "tampered" log) to see if it accurately reflects the files on disk.

## Directory Structure

*   `hash_integrity.py`: The main Python script.
*   `original_images/`: Directory containing the **trusted source images**.
*   `images/`: Directory containing the **test images** to be verified (e.g., images retrieved from a device).
*   `original_hashes.txt`: The **Baseline Hash File**. Generated from `original_images/`.
*   `image_hashes.txt`: The **Test Hash File**. Generated from `images/` during execution.
*   `tampered_hashes.txt`: A hash file that simulates a record that may have been altered. The script checks this file against the actual content of `original_images/`.

## Usage

Run the script from this directory:

```bash
python3 hash_integrity.py
```

## Process Details

### 1. Create Baseline
The script scans `original_images/*.jpg`, calculates SHA-256 hashes, and saves them to `original_hashes.txt`. This file serves as the source of truth.

### 2. Verify Test Images
The script scans `images/`, calculates their hashes, and compares them against `original_hashes.txt`.
- **Match**: The image is verified.
- **Mismatch**: The image has been modified.
- **Not Found**: The image is not in the baseline.

### 3. Detect Tampering
The script compares the actual state of `images/` against two records:
1.  **Against Baseline (`original_hashes.txt`)**: Identifies if the image files themselves have been modified.
2.  **Against Tampered Record (`tampered_hashes.txt`)**: Identifies if the *record* of hashes has been tampered with (i.e., if the hash in the text file doesn't match the actual file's hash).
