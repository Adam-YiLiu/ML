import flwr as fl
import torch
import torch.nn as nn
import hashlib
from data_partitioning import (
    load_dataset_from_existing_dir,
    load_partition_indices,
    create_client_dataloaders
)
from hash_integrity import verify_client_data_integrity
import os
import sys

# --------------------------
# Your TPM Quote Integration (Replace with your actual quote_generation code)
# --------------------------
def generate_tpm_quote_for_model(model_parameters: list) -> str:
    """
    Generate a TPM quote for the model parameters
    REPLACE THIS WITH YOUR ACTUAL quote_generation/ MODULE CODE
    """
    # Hash the model parameters first
    model_hash = hashlib.sha256()
    for param in model_parameters:
        model_hash.update(param.tobytes())
    model_digest = model_hash.hexdigest()
    
    # 👇 Replace this with your actual TPM quote generation code
    # from quote_generation import create_tpm_quote
    # tpm_quote = create_tpm_quote(model_digest)
    tpm_quote = f"TPM_QUOTE_{model_digest}"  # Placeholder
    
    return tpm_quote

# --------------------------
# Model Definition
# --------------------------
class SimpleModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Conv2d(3, 16, 3)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Linear(16, 1)

    def forward(self, x):
        x = self.pool(torch.relu(self.conv(x)))
        x = x.view(x.size(0), -1)
        return self.fc(x)

# --------------------------
# Trusted Flower Client
# --------------------------
class TrustedFLClient(fl.client.NumPyClient):
    def __init__(self, client_id, train_loader, test_loader, client_image_paths):
        self.model = SimpleModel()
        self.client_id = client_id
        self.train_loader = train_loader
        self.test_loader = test_loader
        self.client_image_paths = client_image_paths
        self.criterion = nn.MSELoss()
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)

    def get_parameters(self, config):
        return [val.cpu().numpy() for val in self.model.state_dict().values()]

    def set_parameters(self, parameters):
        params_dict = zip(self.model.state_dict().keys(), parameters)
        state_dict = {k: torch.tensor(v) for k, v in params_dict}
        self.model.load_state_dict(state_dict, strict=True)

    def fit(self, parameters, config):
        # 🔒 TPM Security Step 1: Verify data integrity BEFORE training
        if not verify_client_data_integrity(self.client_id, self.client_image_paths):
            print(f"❌ Client {self.client_id}: Data tampered! Refusing to train.")
            # Return empty result (server will reject this client)
            return [], 0, {"status": "failed", "reason": "data_tampered"}

        self.set_parameters(parameters)
        self.model.train()
        total_loss = 0.0
        
        for batch_idx, batch in enumerate(self.train_loader):
            x, y = batch
            y_hat = self.model(x)
            loss = self.criterion(y_hat, y.float().view(-1,1))
            total_loss += loss.item()
            loss.backward()
            self.optimizer.step()
            self.optimizer.zero_grad()
        
        avg_loss = total_loss / len(self.train_loader)
        print(f"✅ Client {self.client_id} trained, avg loss: {avg_loss:.4f}")

        # 🔒 TPM Security Step 2: Sign model parameters BEFORE uploading
        model_params = self.get_parameters({})
        tpm_quote = generate_tpm_quote_for_model(model_params)

        # Return model + TPM quote
        return model_params, len(self.train_loader.dataset), {
            "status": "success",
            "client_id": self.client_id,
            "tpm_quote": tpm_quote,
            "loss": avg_loss
        }

    def evaluate(self, parameters, config):
        self.set_parameters(parameters)
        self.model.eval()
        loss = 0.0
        with torch.no_grad():
            for batch in self.test_loader:
                x, y = batch
                y_hat = self.model(x)
                loss += self.criterion(y_hat, y.float().view(-1,1)).item()
        avg_loss = loss / len(self.test_loader)
        print(f"✅ Client {self.client_id} evaluated, avg loss: {avg_loss:.4f}")
        return avg_loss, len(self.test_loader.dataset), {}

# --------------------------
# Start Trusted Client
# --------------------------
def start_trusted_fl_client(client_id):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    partition_file = os.path.join(current_dir, "client_partitions.json")
    client_indices = load_partition_indices(partition_file)
    client_indices = {int(k): v for k, v in client_indices.items()}

    train_set, test_set, _ = load_dataset_from_existing_dir()
    
    # Get this client's image paths for integrity check
    client_image_paths = [train_set.image_paths[idx] for idx in client_indices[client_id]]
    
    client_train_loader = create_client_dataloaders(train_set, client_indices)[client_id]
    test_loader = torch.utils.data.DataLoader(test_set, batch_size=8)

    client = TrustedFLClient(client_id, client_train_loader, test_loader, client_image_paths)
    fl.client.start_client(server_address="127.0.0.1:8080", client=client.to_client())

if __name__ == "__main__":
    client_id = int(sys.argv[1])
    start_trusted_fl_client(client_id)
