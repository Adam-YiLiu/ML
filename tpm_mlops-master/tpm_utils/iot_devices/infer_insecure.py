import os
import sys
import subprocess
import time
import argparse
import csv
import json
import statistics
import requests
from datetime import datetime
from pathlib import Path

from power_monitor import PowerMonitor, merge_power_into_metrics, POWER_COLUMNS

# Prometheus configuration
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

# Power monitor (Tasmota smart plug) IP
POWER_MONITOR_IP = os.environ.get("POWER_MONITOR_IP", "192.168.3.29")

from device_detection import determine_inference_backend
from constants import discover_model

# Paths
current_dir = Path(__file__).parent.resolve()
repo_root = current_dir.parent.parent
data_hashing_dir = repo_root / "data_hashing"
images_dir = data_hashing_dir / "images"

# Model path is discovered dynamically from the edge package.
backend = determine_inference_backend()
model_path = discover_model(backend)
if model_path is None:
    model_path = Path.home() / "tss_model_sec/orchestrator_output/edge_package/mobilenetv2-7.onnx"

def get_log_path(algo):
    os.makedirs(current_dir / "logs", exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"infer_insecure_{timestamp_str}.log"
    return current_dir / "logs" / log_filename, timestamp_str

def log(message, log_path):
    print(message)
    log_path.parent.mkdir(exist_ok=True)
    with open(log_path, "a") as f:
        f.write(message + "\n")

def query_prometheus(query, start_time, end_time, step="1s", log_path=None):
    """Query Prometheus for metrics over a time range."""
    try:
        url = f"{PROMETHEUS_URL}/api/v1/query_range"
        params = {
            "query": query,
            "start": start_time,
            "end": end_time,
            "step": step
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        if log_path:
            log(f"Error querying Prometheus: {e}", log_path)
        return None

def collect_metrics(start_timestamp, end_timestamp, log_path):
    """Collect CPU and memory metrics from Prometheus."""
    metrics = []
    
    # CPU usage percentage (using node_exporter metric)
    # 100 - (average idle CPU percentage)
    cpu_query = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5s])) * 100)'
    
    # Memory usage in bytes
    mem_used_query = 'node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes'
    
    # Memory usage percentage
    mem_percent_query = '100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))'
    
    cpu_data = query_prometheus(cpu_query, start_timestamp, end_timestamp, log_path=log_path)
    mem_used_data = query_prometheus(mem_used_query, start_timestamp, end_timestamp, log_path=log_path)
    mem_percent_data = query_prometheus(mem_percent_query, start_timestamp, end_timestamp, log_path=log_path)
    
    # Extract values and combine
    cpu_values = []
    mem_used_values = []
    mem_percent_values = []
    timestamps = []
    
    if cpu_data and cpu_data.get("status") == "success":
        results = cpu_data.get("data", {}).get("result", [])
        if results:
            for ts, val in results[0].get("values", []):
                timestamps.append(ts)
                cpu_values.append(float(val))
    
    if mem_used_data and mem_used_data.get("status") == "success":
        results = mem_used_data.get("data", {}).get("result", [])
        if results:
            for ts, val in results[0].get("values", []):
                mem_used_values.append(float(val))
    
    if mem_percent_data and mem_percent_data.get("status") == "success":
        results = mem_percent_data.get("data", {}).get("result", [])
        if results:
            for ts, val in results[0].get("values", []):
                mem_percent_values.append(float(val))
    
    # Combine into metrics list
    for i, ts in enumerate(timestamps):
        metric = {
            "timestamp": datetime.fromtimestamp(ts).isoformat(),
            "cpu_percent": cpu_values[i] if i < len(cpu_values) else None,
            "memory_bytes": mem_used_values[i] if i < len(mem_used_values) else None,
            "memory_percent": mem_percent_values[i] if i < len(mem_percent_values) else None
        }
        metrics.append(metric)
    
    return metrics

def save_metrics_to_csv(metrics, csv_path, log_path, include_power=False):
    """Save collected metrics to a CSV file."""
    if not metrics:
        log("No metrics to save.", log_path)
        return
    
    fieldnames = ["timestamp", "cpu_percent", "memory_bytes", "memory_percent"]
    if include_power:
        fieldnames += POWER_COLUMNS
    csv_path.parent.mkdir(exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(metrics)
    
    log(f"Metrics saved to {csv_path}", log_path)
    
def compile_inference_result(csv_path, batch_result=None):
    """Compile inference results into a summary CSV."""
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["task", "start", "end", "duration", "image"])
        if batch_result:
            for inf in batch_result.get("inferences", []):
                writer.writerow(["inference", inf["start"], inf["end"],
                                 inf["duration"], inf.get("image", "")])

def run_inference(algo="ecc", collect_power=False):
    log_path, timestamp_str = get_log_path(algo)
    
    if not images_dir.exists():
        log(f"Error: Images directory not found at {images_dir}", log_path)
        return

    power_monitor = None
    if collect_power:
        power_monitor = PowerMonitor(host=POWER_MONITOR_IP)
        power_monitor.start()
        log(f"Power monitoring started - {POWER_MONITOR_IP}", log_path)

    # Count images for logging
    images = sorted([f.name for f in images_dir.iterdir() if f.is_file() and f.suffix == ".jpg"])
    if not images:
        log("No images found.", log_path)
        return

    log(f"Starting batch inference on {len(images)} images using {algo} algorithm.", log_path)
    start_time = time.time()
    start_ns = time.time_ns()
    log(f"Start Timestamp: {datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_path)

    # Single subprocess call with --batch-dir to load the model once
    cmd = [
        sys.executable,
        "main.py",
        str(model_path),
        "--batch-dir", str(images_dir),
        "--no-integrity-check",
        "--algo", algo
    ]

    image_durations = []
    batch_result = None
    try:
        result = subprocess.run(cmd, cwd=current_dir, check=True, timeout=600,
                                capture_output=True, text=True)
        if result.stderr:
            log(result.stderr, log_path)
        # Parse the JSON output (printed to stdout by main_batch)
        batch_result = json.loads(result.stdout.strip())
        for inf in batch_result.get("inferences", []):
            dur = inf["duration"]
            image_durations.append(dur)
            log(f"Image: {inf['image']} - Duration: {dur:.4f}ms - Result: {inf['result']}", log_path)
    except subprocess.TimeoutExpired:
        log(f"TIMEOUT: batch inference timed out after 600s", log_path)
    except subprocess.CalledProcessError as e:
        log(f"Error running batch inference: {e}", log_path)
        if e.stderr:
            log(f"Stderr: {e.stderr}", log_path)
    except (json.JSONDecodeError, KeyError) as e:
        log(f"Error parsing batch inference output: {e}", log_path)

    end_time = time.time()
    total_time_ms = (time.time_ns() - start_ns) / 1_000_000
    log(f"End Timestamp: {datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_path)
    
    avg_time_ms = total_time_ms / len(images) if images else 0
    std_dev_ms = statistics.stdev(image_durations) if len(image_durations) >= 2 else 0.0
    
    log(f"Total Time Taken: {total_time_ms:.4f}ms", log_path)
    log(f"Average Time per Image: {avg_time_ms:.4f}ms", log_path)
    log(f"Standard Deviation: {std_dev_ms:.4f}ms", log_path)
    
    # Collect and save Prometheus metrics
    log("Collecting metrics from Prometheus...", log_path)
    metrics = collect_metrics(start_time, end_time, log_path)

    include_power = power_monitor is not None
    if include_power:
        merge_power_into_metrics(metrics, power_monitor)

    csv_filename = f"infer_insecure_{timestamp_str}.csv"
    csv_path = current_dir / "logs" / csv_filename
    save_metrics_to_csv(metrics, csv_path, log_path, include_power=include_power)

    if power_monitor:
        power_monitor.stop()
        log("Power monitoring stopped", log_path)
    
    log("Compile inference results and metrics into summary CSV", log_path)
    csv_filename = f"infer_insecure_summary_{timestamp_str}.csv"
    summary_csv_path = current_dir / "logs" / csv_filename
    compile_inference_result(summary_csv_path, batch_result)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insecure Inference Script")
    parser.add_argument("--algo", choices=["rsa", "ecc"], default="ecc", help="Algorithm to use (rsa or ecc)")
    parser.add_argument("--collect-power", action="store_true", default=False,
                        help="Collect power metrics via MQTT from Tasmota smart plug")
    args = parser.parse_args()
    run_inference(args.algo, collect_power=args.collect_power)