import random
import numpy as np
import torch
from torchvision import datasets, transforms
from torchvision.io import read_image
from typing import List, Dict, Tuple
import os
import hashlib
from pathlib import Path
import json

# Fix random seed
def set_seed(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

# --------------------------
# Custom Dataset: Safe image loading (skip unsupported files)
# --------------------------
class UnorganizedImageDataset(torch.utils.data.Dataset):
    def __init__(self, folder_path, transform=None):
        self.folder_path = Path(folder_path)
        self.transform = transform
        # Load ONLY supported image files
        self.image_paths = []
        supported_ext = ['*.jpg', '*.png', '*.jpeg', '*.bmp']
        for ext in supported_ext:
            self.image_paths.extend(list(self.folder_path.rglob(ext)))
        self.image_paths = sorted(self.image_paths)
        print(f"✅ Found {len(self.image_paths)} valid images in {folder_path}")

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        try:
            image = read_image(str(img_path)).float() / 255.0
            # Force all images to 3 channels
            if image.shape[0] == 1:
                image = image.repeat(3, 1, 1)
            elif image.shape[0] == 4:
                image = image[:3, :, :]
            if self.transform:
                image = self.transform(image)
            label = 0
            return image, label
        except Exception as e:
            print(f"⚠️ Skipping corrupted/unsupported image: {img_path}")
            # Return a dummy tensor to avoid crashing
            return torch.zeros((3, 64, 64)), 0

# =====================
# Load Dataset
# =====================
def load_dataset_from_existing_dir():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    train_root = os.path.join(current_dir, "original_images")
    test_root = os.path.join(current_dir, "images")

    transform = transforms.Compose([
        transforms.Resize((64, 64), antialias=True),
        transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
    ])

    train_set = UnorganizedImageDataset(train_root, transform)
    test_set = UnorganizedImageDataset(test_root, transform)
    return train_set, test_set, current_dir

# =====================
# Exclusive Partition (run once, save to file)
# =====================
def exclusive_non_iid_partition(
    dataset: torch.utils.data.Dataset,
    fixed_counts: List[int] = [50, 17, 92, 20, 80],
    seed: int = 42
) -> Dict[int, List[int]]:
    set_seed(seed)
    num_clients = len(fixed_counts)
    total_samples = len(dataset)
    assert sum(fixed_counts) <= total_samples, f"❌ Total samples exceed dataset size {total_samples}"

    all_indices = list(range(total_samples))
    random.shuffle(all_indices)

    client_data_indices = {}
    current_idx = 0
    for client_id in range(num_clients):
        count = fixed_counts[client_id]
        client_data_indices[client_id] = all_indices[current_idx:current_idx + count]
        current_idx += count

    # Verify no duplicates
    all_assigned = [idx for indices in client_data_indices.values() for idx in indices]
    assert len(all_assigned) == len(set(all_assigned)), "❌ Duplicate images found!"
    print("✅ Partition done: NO duplicate images")
    return client_data_indices

# =====================
# Save/Load Partition Results (Critical for Unique Client Data)
# =====================
def save_partition_indices(client_indices: Dict[int, List[int]], save_path: str):
    with open(save_path, "w") as f:
        json.dump(client_indices, f)
    print(f"✅ Partition indices saved to {save_path}")

def load_partition_indices(load_path: str) -> Dict[int, List[int]]:
    with open(load_path, "r") as f:
        return json.load(f)

# =====================
# Generate Hash Files
# =====================
def generate_client_hashes(
    dataset: UnorganizedImageDataset,
    client_data_indices: Dict[int, List[int]],
    output_dir: str
):
    hash_dir = os.path.join(output_dir, "image_hashes")
    os.makedirs(hash_dir, exist_ok=True)
    for client_id, indices in client_data_indices.items():
        hash_file = os.path.join(hash_dir, f"client_{client_id}_hashes.txt")
        with open(hash_file, "w") as f:
            for idx in indices:
                img_path = dataset.image_paths[idx]
                with open(img_path, "rb") as img_file:
                    img_hash = hashlib.sha256(img_file.read()).hexdigest()
                f.write(f"{os.path.basename(img_path)}: {img_hash}\n")
        print(f"✅ Client {client_id} hash saved")

# =====================
# Create DataLoaders
# =====================
def create_client_dataloaders(
    dataset: torch.utils.data.Dataset,
    client_data_indices: Dict[int, List[int]],
    batch_size: int = 8
) -> Dict[int, torch.utils.data.DataLoader]:
    client_loaders = {}
    for client_id, indices in client_data_indices.items():
        subset = torch.utils.data.Subset(dataset, indices)
        client_loaders[client_id] = torch.utils.data.DataLoader(subset, batch_size=batch_size, shuffle=True)
    return client_loaders

# ------------------------------
# Run Once (Generate Partition + Save Indices)
# ------------------------------
if __name__ == "__main__":
    train_set, test_set, data_hashing_dir = load_dataset_from_existing_dir()
    fixed_counts = [50, 17, 92, 20, 80]
    client_indices = exclusive_non_iid_partition(train_set, fixed_counts)
    
    # Save partition to file (clients will load this instead of re-partitioning)
    partition_file = os.path.join(data_hashing_dir, "client_partitions.json")
    save_partition_indices(client_indices, partition_file)

    print("\n📊 Client Results:")
    for i in range(5):
        print(f"Client {i}: {len(client_indices[i])} images")

    generate_client_hashes(train_set, client_indices, data_hashing_dir)
    print("\n✅ Partition saved! Now use this for Flower clients.")
