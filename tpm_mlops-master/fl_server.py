import flwr as fl
import torch
import hashlib

from flwr.common import parameters_to_ndarrays
# --------------------------
# Your TPM Quote Verification (Replace with your actual tpm_utils code)
# --------------------------
def verify_tpm_quote(client_id: int, tpm_quote: str, model_parameters: list) -> bool:
    """
    Verify that the TPM quote matches the model parameters
    REPLACE THIS WITH YOUR ACTUAL tpm_utils/ MODULE CODE
    """
    # Recompute the model hash
    model_hash = hashlib.sha256()
    for param in model_parameters:
        model_hash.update(param.tobytes())
    expected_digest = model_hash.hexdigest()
    
    # Placeholder verification
    expected_quote = f"TPM_QUOTE_{expected_digest}"
    if tpm_quote == expected_quote:
        print(f"✅ Server: Client {client_id} TPM quote verified")
        return True
    else:
        print(f"❌ Server: Client {client_id} TPM quote INVALID! Model tampered.")
        return False

# --------------------------
# Trusted FedAvg Strategy
# --------------------------
class TrustedFedAvg(fl.server.strategy.FedAvg):
    def aggregate_fit(self, server_round, results, failures):
        # 🔒 TPM Security Step 3: Verify ALL client quotes BEFORE aggregation
        trusted_results = []
        for client_proxy, fit_res in results:
            metrics = fit_res.metrics
            
            if metrics.get("status") != "success":
                print(f"❌ Server: Rejecting client {metrics.get('client_id')} (training failed)")
                continue
            
            client_id = metrics.get("client_id")
            tpm_quote = metrics.get("tpm_quote")
            model_params = parameters_to_ndarrays(fit_res.parameters)
            
            if not verify_tpm_quote(client_id, tpm_quote, model_params):
                print(f"❌ Server: Rejecting client {client_id} (invalid TPM quote)")
                continue
            
            # Only add trusted clients to aggregation
            trusted_results.append((client_proxy, fit_res))
        
        print(f"\n🔒 Server: Aggregating {len(trusted_results)} trusted clients out of {len(results)} total")
        
        # Aggregate only trusted models
        return super().aggregate_fit(server_round, trusted_results, failures)

# --------------------------
# Start Trusted Server
# --------------------------
def main():
    def fit_config(server_round: int):
        print(f"\n=== Starting Federated Round {server_round} ===")
        return {}

    strategy = TrustedFedAvg(
        fraction_fit=1.0,
        fraction_evaluate=1.0,
        min_fit_clients=5,
        min_evaluate_clients=5,
        min_available_clients=5,
        on_fit_config_fn=fit_config,
    )

    print("🛡️ Starting TPM-Trusted Federated Learning Server")
    fl.server.start_server(
        server_address="0.0.0.0:8080",
        config=fl.server.ServerConfig(num_rounds=3),
        strategy=strategy,
    )

if __name__ == "__main__":
    main()
