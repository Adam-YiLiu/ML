from pathlib import Path
import re
import hashlib
import shutil
import sys
import argparse

# -----------------------------
# 1️⃣ Create baseline hashes
# -----------------------------
def create_baseline(image_dir: Path, output_file: Path):
    """Generate SHA-256 hashes for all JPG images in a folder."""
    output_file.parent.mkdir(exist_ok=True)

    def extract_number(p):
        match = re.search(r'\d+', p.stem)
        return int(match.group()) if match else 0

    image_paths = sorted(image_dir.glob("*.jpg"), key=extract_number)

    with open(output_file, "w") as f:
        for img_path in image_paths:
            with open(img_path, "rb") as img_file:
                digest = hashlib.sha256(img_file.read()).hexdigest()
            f.write(f"{img_path}\t{digest}\n")
            print(f"Hashed: {img_path.name}")

    print(f"\nAll baseline hashes saved to {output_file}")

# -----------------------------
# 2️⃣ Verify test images
# -----------------------------
def verify_images(baseline_file: Path, test_dir: Path, output_file: Path):
    """Verify test images against a baseline hash file (simplified output)."""
    baseline = {}
    with open(baseline_file, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            filename = Path(parts[0]).name.lower()
            baseline[filename] = parts[1].lower()

    results = []
    for img in sorted(test_dir.glob("*.jpg")):
        if not img.is_file():
            continue
        with open(img, "rb") as img_file:
            new_hash = hashlib.sha256(img_file.read()).hexdigest().lower()
        results.append((img.name, new_hash))

    with open(output_file, "w") as f:
        for filename, new_hash in sorted(results, key=lambda x: x[0].lower()):
            f.write(f"{filename} {new_hash}\n")

    print("\nVerification Results:")
    for filename, new_hash in sorted(results, key=lambda x: x[0].lower()):
        key = filename.lower()
        if key in baseline:
            if new_hash == baseline[key]:
                print(f"{filename}: Verified")
            else:
                print(f"{filename}: Hash mismatch!")
        else:
            print(f"{filename}: Not found in baseline")

    print(f"\nAll new hashes saved in {output_file}")
    return results

# -----------------------------
# 3️⃣ Detect tampered images/hashes
# -----------------------------
def detect_tampering(original_file: Path, tampered_file: Path, test_dir: Path):
    """Detect modified images and tampered hash records."""
    def load_hashes(file_path: Path):
        hashes = {}
        if not file_path.exists():
            return hashes
        with open(file_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    filename = Path(parts[0]).name.lower()
                    hashes[filename] = parts[1].lower()
        return hashes

    def generate_hashes(directory: Path):
        hashes = {}
        for img in sorted(directory.glob("*")):
            if not img.is_file():
                continue
            with open(img, "rb") as img_file:
                new_hash = hashlib.sha256(img_file.read()).hexdigest().lower()
            hashes[img.name.lower()] = new_hash
        return hashes

    original_hashes = load_hashes(original_file)
    tampered_hashes = load_hashes(tampered_file)
    test_hashes = generate_hashes(test_dir)

    modified_images = [name for name, h in test_hashes.items() if name in original_hashes and h != original_hashes[name]]
    tampered_records = [name for name, h in tampered_hashes.items() if name in test_hashes and h != test_hashes[name]]

    print("\nTampering Verification Results:")
    if modified_images:
        print("\nModified Images Detected:")
        for img in modified_images:
            print(f"  - {img}")
    if tampered_records:
        print("\nTampered Hash Records Detected:")
        for img in tampered_records:
            print(f"  - {img}")
    if not modified_images and not tampered_records:
        print("All images and hashes are verified and untampered.")

# -----------------------------
# 4️⃣ Setup environment
# -----------------------------
def setup_environment(fail: bool = False):
    """Setup the test environment by copying appropriate files."""
    test_dir = Path.cwd() / "images"
    baseline_file = Path.cwd() / "original_hashes.txt"
    tampered_file = Path.cwd() / "tampered_hashes.txt"

    if fail:
        print("Setting up tampered environment for testing.")
        shutil.copy(test_dir / "50.tampered.bak", test_dir / "50.jpg")
        shutil.copy(Path.cwd() / "tampered_hashes.txt.bak", tampered_file)
    else:
        print("Setting up clean environment.")
        shutil.copy(test_dir / "50.bak", test_dir / "50.jpg")
        shutil.copy(baseline_file, tampered_file)

# -----------------------------
# 5️⃣ Verify single image
# -----------------------------
def verify_single_image(image_name: str) -> bool:
    """Verify a single image against baseline and tampered hash files.

    Returns True if the image passes all checks, False otherwise.
    """
    results = verify_images_batch([image_name])
    return results.get(image_name, False)


def verify_images_batch(image_names, base_dir=None):
    """Verify multiple images against baseline and tampered hash files.

    Loads baseline and tampered hashes once for all images.
    *base_dir* defaults to ``Path.cwd()`` (the data_hashing directory).

    Returns a dict mapping each image name to True (verified) or False.
    """
    base_dir = Path(base_dir) if base_dir else Path.cwd()
    baseline_file = base_dir / "original_hashes.txt"
    test_dir = base_dir / "images"
    tampered_file = base_dir / "tampered_hashes.txt"

    # Load baseline hashes once
    baseline = {}
    with open(baseline_file, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                filename = Path(parts[0]).name.lower()
                baseline[filename] = parts[1].lower()

    # Load tampered hashes once
    tampered = {}
    if tampered_file.exists():
        with open(tampered_file, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    filename = Path(parts[0]).name.lower()
                    tampered[filename] = parts[1].lower()

    results = {}
    for image_name in image_names:
        image_path = test_dir / image_name

        if not image_path.exists():
            print(f"{image_name}: ERROR - Image not found in {test_dir}")
            results[image_name] = False
            continue

        with open(image_path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest().lower()

        key = image_name.lower()
        verified = True

        if key not in baseline:
            print(f"{image_name}: NOT FOUND in baseline")
            verified = False
        elif actual_hash != baseline[key]:
            print(f"{image_name}: MODIFIED - Hash mismatch with baseline")
            print(f"  Expected: {baseline[key]}")
            print(f"  Actual:   {actual_hash}")
            verified = False

        if key in tampered and tampered[key] != actual_hash:
            print(f"{image_name}: TAMPERED hash record detected")
            print(f"  Record hash: {tampered[key]}")
            print(f"  Actual hash: {actual_hash}")
            verified = False

        if verified:
            print(f"{image_name}: Verified")
        results[image_name] = verified

    return results

# -----------------------------
# Main function
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="Image Hash Integrity Check")
    parser.add_argument("--fail", action="store_true", help="Intentionally fail the hash integrity check (for testing)")
    parser.add_argument("--setup-only", action="store_true", help="Only setup the test environment (copy files)")
    parser.add_argument("--create-baseline", action="store_true", help="Only create baseline hashes")
    parser.add_argument("--verify-image", type=str, metavar="FILENAME", help="Verify a single image against baseline")
    args = parser.parse_args()

    image_dir = Path.cwd() / "original_images"
    baseline_file = Path.cwd() / "original_hashes.txt"
    test_dir = Path.cwd() / "images"
    test_hash_file = Path.cwd() / "image_hashes.txt"
    tampered_file = Path.cwd() / "tampered_hashes.txt"

    if args.setup_only:
        setup_environment(args.fail)
        return

    if args.create_baseline:
        create_baseline(image_dir, baseline_file)
        return

    if args.verify_image:
        if not baseline_file.exists():
            print(f"Error: Baseline file not found at {baseline_file}")
            print("Run with --create-baseline first.")
            sys.exit(1)
        result = verify_single_image(args.verify_image)
        sys.exit(0 if result else 1)

    # Full pipeline (original behavior)
    setup_environment(args.fail)
    create_baseline(image_dir, baseline_file)
    verify_images(baseline_file, test_dir, test_hash_file)
    detect_tampering(baseline_file, tampered_file, test_dir)

if __name__ == "__main__":
    main()

def verify_client_data_integrity(client_id: int, image_paths: list) -> bool:
    """
    Verify that the client's dataset matches the trusted baseline hash file
    Returns True if data is intact, False if tampered
    """
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    hash_file = os.path.join(current_dir, "image_hashes", f"client_{client_id}_hashes.txt")
    
    if not os.path.exists(hash_file):
        print(f"❌ Client {client_id}: Trusted hash file not found!")
        return False
    
    # Load trusted hashes
    trusted_hashes = {}
    with open(hash_file, "r") as f:
        for line in f:
            filename, file_hash = line.strip().split(": ")
            trusted_hashes[filename] = file_hash
    
    # Verify each image
    import hashlib
    for img_path in image_paths:
        filename = os.path.basename(img_path)
        if filename not in trusted_hashes:
            print(f"❌ Client {client_id}: Unknown file {filename} detected!")
            return False
        
        with open(img_path, "rb") as f:
            current_hash = hashlib.sha256(f.read()).hexdigest()
        
        if current_hash != trusted_hashes[filename]:
            print(f"❌ Client {client_id}: File {filename} has been TAMPERED!")
            return False
    
    print(f"✅ Client {client_id}: Data integrity verified (TPM baseline)")
    return True
