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

# Allow importing hash_integrity from the data_hashing directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "data_hashing"))
from hash_integrity import verify_images_batch

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
quote_generation_dir = repo_root / "quote_generation"
images_dir = data_hashing_dir / "images"

# Model path is discovered dynamically from the edge package.
# The orchestrator places the signed model (onnx or xmodel) there.
backend = determine_inference_backend()
model_path = discover_model(backend)
if model_path is None:
    # Fallback to the legacy hardcoded path so existing setups still work
    model_path = Path.home() / "tss_model_sec/orchestrator_output/edge_package/mobilenetv2-7.onnx"


def get_log_path(algo, fail_hash=False, fail_verify=False, fail_quote=False):
    os.makedirs(current_dir / "logs", exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    flags = []
    if fail_hash:
        flags.append("failhash")
    if fail_verify:
        flags.append("failverify")
    if fail_quote:
        flags.append("failquote")
    flags_str = "_".join(flags) if flags else "nofail"
    log_filename = f"infer_secure_{algo}_{flags_str}_{timestamp_str}.log"
    return current_dir / "logs" / log_filename, timestamp_str, flags_str


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
    cpu_query = '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5s])) * 100)'
    mem_used_query = 'node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes'
    mem_percent_query = '100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))'

    cpu_data = query_prometheus(cpu_query, start_timestamp, end_timestamp, log_path=log_path)
    mem_used_data = query_prometheus(mem_used_query, start_timestamp, end_timestamp, log_path=log_path)
    mem_percent_data = query_prometheus(mem_percent_query, start_timestamp, end_timestamp, log_path=log_path)

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

    metrics = []
    for i, ts in enumerate(timestamps):
        metrics.append({
            "timestamp": datetime.fromtimestamp(ts).isoformat(),
            "cpu_percent": cpu_values[i] if i < len(cpu_values) else None,
            "memory_bytes": mem_used_values[i] if i < len(mem_used_values) else None,
            "memory_percent": mem_percent_values[i] if i < len(mem_percent_values) else None
        })

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


def run_command(command, cwd, description, log_path, log_output=False):
    """Run a subprocess command, logging output and timing.

    Returns (success, start_time, end_time, duration_ms).
    success is True if the command exited with 0, False otherwise.
    start_time/end_time are from time.time() for display.
    duration_ms uses time.time_ns() for higher precision.
    """
    log(f"Starting {description}...", log_path)
    start_time = time.time()
    start_ns = time.time_ns()
    log(f"{description} Start: {datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_path)

    success = True
    try:
        if log_output:
            process = subprocess.Popen(
                command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1
            )
            for line in process.stdout:
                log(f"  {line.rstrip()}", log_path)
            process.wait(timeout=120)
            stderr_output = process.stderr.read()
            if stderr_output:
                log(f"  Stderr: {stderr_output.rstrip()}", log_path)
            if process.returncode != 0:
                success = False
        else:
            subprocess.run(command, cwd=cwd, check=True, timeout=120)
    except subprocess.TimeoutExpired:
        log(f"{description} TIMED OUT after 120s — possible DPU hang", log_path)
        success = False
    except subprocess.CalledProcessError:
        success = False

    end_time = time.time()
    duration_ms = (time.time_ns() - start_ns) / 1_000_000

    if success:
        log(f"{description} End: {datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", log_path)
        log(f"{description} Duration: {duration_ms:.4f}ms", log_path)
    else:
        log(f"{description} FAILED after {duration_ms:.4f}ms", log_path)

    return success, start_time, end_time, duration_ms


def fmt_ts(ts):
    """Format a Unix timestamp as a human-readable string."""
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def compile_summary_csv(csv_path, task_records, log_path):
    """Write task records to a summary CSV."""
    if not task_records:
        log("No task records to save.", log_path)
        return

    fieldnames = ["task", "start", "end", "duration", "algorithm", "use_swtpm", "result", "image"]
    csv_path.parent.mkdir(exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(task_records)

    log(f"Summary CSV saved to {csv_path}", log_path)


def save_results(overall_start_time, task_records, algo, flags_str, timestamp_str, log_path,
                 power_monitor=None):
    """Collect Prometheus metrics and write summary CSV."""
    overall_end_time = time.time()
    log("\nCollecting metrics from Prometheus...", log_path)
    metrics = collect_metrics(overall_start_time, overall_end_time, log_path)

    include_power = power_monitor is not None
    if include_power:
        merge_power_into_metrics(metrics, power_monitor)

    csv_filename = f"infer_secure_{algo}_{flags_str}_{timestamp_str}.csv"
    csv_path = current_dir / "logs" / csv_filename
    save_metrics_to_csv(metrics, csv_path, log_path, include_power=include_power)

    summary_csv_filename = f"infer_secure_summary_{algo}_{flags_str}_{timestamp_str}.csv"
    summary_csv_path = current_dir / "logs" / summary_csv_filename
    compile_summary_csv(summary_csv_path, task_records, log_path)


def run_inference(algo="ecc", use_swtpm=False, fail_quote=False, fail_hash=False, fail_verify=False,
                  collect_power=False):
    log_path, timestamp_str, flags_str = get_log_path(algo, fail_hash, fail_verify, fail_quote)

    if not images_dir.exists():
        log(f"Error: Images directory not found at {images_dir}", log_path)
        return

    power_monitor = None
    if collect_power:
        power_monitor = PowerMonitor(host=POWER_MONITOR_IP)
        power_monitor.start()
        log(f"Power monitoring started - {POWER_MONITOR_IP}", log_path)

    overall_start_time = time.time()
    task_records = []
    workflow_failed = False

    # ================================================================
    # Step 0: Setup hash environment and create baseline (once)
    # ================================================================
    setup_cmd = [sys.executable, "hash_integrity.py", "--setup-only"]
    if fail_hash:
        setup_cmd.append("--fail")
    run_command(setup_cmd, data_hashing_dir, "Hash Environment Setup", log_path, log_output=True)

    run_command(
        [sys.executable, "hash_integrity.py", "--create-baseline"],
        data_hashing_dir, "Baseline Creation", log_path, log_output=True
    )

    # ================================================================
    # Step 1: Quote Generation (oneshot — failure stops workflow)
    # ================================================================
    quote_cmd = [sys.executable, "generatequote.py", "--algo", algo]
    if fail_quote:
        quote_cmd.append("--fail")
    q_ok, q_start, q_end, q_dur = run_command(
        quote_cmd, quote_generation_dir, "Quote Generation", log_path, log_output=True
    )
    task_records.append({
        "task": "quote_generation", "start": fmt_ts(q_start), "end": fmt_ts(q_end),
        "duration": f"{q_dur:.4f}", "algorithm": algo, "use_swtpm": "",
        "result": "OK" if q_ok else "FAILED", "image": ""
    })
    if not q_ok:
        log("\nWorkflow STOPPED: Quote generation failed", log_path)
        save_results(overall_start_time, task_records, algo, flags_str, timestamp_str, log_path,
                     power_monitor=power_monitor)
        if power_monitor:
            power_monitor.stop()
        return

    # ================================================================
    # Step 2: Model Signature Verification (oneshot — failure stops workflow)
    # ================================================================
    verify_cmd = [sys.executable, "main.py", str(model_path), "--verify-only", "--algo", algo]
    if not use_swtpm:
        verify_cmd.append("--no-swtpm")
    if fail_verify:
        verify_cmd.append("--fail")
    v_ok, v_start, v_end, v_dur = run_command(
        verify_cmd, current_dir, "Model Verification", log_path, log_output=True
    )
    task_records.append({
        "task": "model_validation", "start": fmt_ts(v_start), "end": fmt_ts(v_end),
        "duration": f"{v_dur:.4f}", "algorithm": algo, "use_swtpm": str(use_swtpm),
        "result": "VALID" if v_ok else "INVALID", "image": ""
    })
    if not v_ok:
        log("\nWorkflow STOPPED: Model verification failed", log_path)
        save_results(overall_start_time, task_records, algo, flags_str, timestamp_str, log_path,
                     power_monitor=power_monitor)
        if power_monitor:
            power_monitor.stop()
        return

    # ================================================================
    # Step 3: Per-image hash integrity check, then batch inference
    # ================================================================
    images = sorted([f.name for f in images_dir.iterdir() if f.is_file() and f.suffix == ".jpg"])
    if not images:
        log("No images found.", log_path)
        return

    log(f"\nStarting per-image processing on {len(images)} images using {algo} algorithm.", log_path)
    inference_loop_start = time.time()
    log(f"Per-image loop Start: {fmt_ts(inference_loop_start)}", log_path)

    image_durations = []
    hash_durations = {}         # image name -> hash duration ms
    verified_images = []        # images that passed hash check

    # 3a. Batch hash integrity check (single in-process call)
    log(f"\nRunning hash integrity check on {len(images)} images...", log_path)
    h_start_time = time.time()
    h_start_ns = time.time_ns()
    hash_results = verify_images_batch(images, base_dir=data_hashing_dir)
    h_end_time = time.time()
    h_dur_ms = (time.time_ns() - h_start_ns) / 1_000_000
    h_dur_per_image = h_dur_ms / len(images) if images else 0

    for i, image in enumerate(images, 1):
        h_ok = hash_results.get(image, False)
        task_records.append({
            "task": "hash_integrity", "start": fmt_ts(h_start_time), "end": fmt_ts(h_end_time),
            "duration": f"{h_dur_per_image:.4f}", "algorithm": "", "use_swtpm": "",
            "result": "Verified" if h_ok else "FAILED", "image": image
        })
        if not h_ok:
            image_durations.append(h_dur_per_image)
            log(f"Image {i}/{len(images)}: {image} SKIPPED — hash integrity failed", log_path)
        else:
            hash_durations[image] = h_dur_per_image
            verified_images.append(image)

    log(f"Hash integrity check completed in {h_dur_ms:.4f}ms "
        f"({len(verified_images)}/{len(images)} verified)", log_path)

    # 3b. Batch inference for all verified images (model loaded once)
    if verified_images:
        log(f"\nRunning batch inference on {len(verified_images)} verified images...", log_path)
        batch_cmd = [
            sys.executable, "main.py",
            str(model_path),
            "--batch-dir", str(images_dir),
            "--batch-images", *verified_images,
            "--no-integrity-check", "--algo", algo
        ]
        if not use_swtpm:
            batch_cmd.append("--no-swtpm")

        batch_start = time.time()
        batch_start_ns = time.time_ns()
        batch_result = None
        try:
            result = subprocess.run(batch_cmd, cwd=current_dir, check=True, timeout=600,
                                    capture_output=True, text=True)
            if result.stderr:
                log(result.stderr, log_path)
            batch_result = json.loads(result.stdout.strip())
        except subprocess.TimeoutExpired:
            log("TIMEOUT: batch inference timed out after 600s", log_path)
        except subprocess.CalledProcessError as e:
            log(f"Error running batch inference: {e}", log_path)
            if e.stderr:
                log(f"Stderr: {e.stderr}", log_path)
        except (json.JSONDecodeError, KeyError) as e:
            log(f"Error parsing batch inference output: {e}", log_path)

        # Map inference durations back to per-image records
        inf_by_image = {}
        if batch_result:
            for inf in batch_result.get("inferences", []):
                inf_by_image[inf["image"]] = inf

        for image in verified_images:
            inf = inf_by_image.get(image)
            if inf:
                i_dur = inf["duration"]
                h_dur = hash_durations[image]
                img_total_ms = h_dur + i_dur
                image_durations.append(img_total_ms)

                task_records.append({
                    "task": "inference", "start": inf["start"], "end": inf["end"],
                    "duration": f"{i_dur:.4f}", "algorithm": "", "use_swtpm": "",
                    "result": "", "image": image
                })

                log(f"Image: {image} total {img_total_ms:.4f}ms "
                    f"(hash {h_dur:.4f}ms + inference {i_dur:.4f}ms)", log_path)
            else:
                image_durations.append(hash_durations[image])
                log(f"Image: {image} — no inference result returned", log_path)

    inference_loop_end = time.time()
    total_time_ms = sum(image_durations)
    avg_time_ms = total_time_ms / len(images) if images else 0
    std_dev_ms = statistics.stdev(image_durations) if len(image_durations) >= 2 else 0.0

    log(f"\nPer-image loop End: {fmt_ts(inference_loop_end)}", log_path)
    log(f"Total Time: {total_time_ms:.4f}ms", log_path)
    log(f"Average Time per Image: {avg_time_ms:.4f}ms", log_path)
    log(f"Standard Deviation: {std_dev_ms:.4f}ms", log_path)

    save_results(overall_start_time, task_records, algo, flags_str, timestamp_str, log_path,
                 power_monitor=power_monitor)
    if power_monitor:
        power_monitor.stop()
        log("Power monitoring stopped", log_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Secure Inference Script")
    parser.add_argument("--fail-hash", action="store_true", default=False,
                        help="Intentionally fail the hash integrity check (for testing)")
    parser.add_argument("--fail-verify", action="store_true", default=False,
                        help="Intentionally fail the model signature verification (for testing)")
    parser.add_argument("--fail-quote", action="store_true", default=False,
                        help="Intentionally fail the quote verification (for testing)")
    parser.add_argument("--algo", choices=["rsa", "ecc"], default="ecc",
                        help="Algorithm to use (rsa or ecc)")
    parser.add_argument("--use-swtpm", action="store_true",
                        help="Use swtpm for TPM operations (default false)")
    parser.add_argument("--collect-power", action="store_true", default=False,
                        help="Collect power metrics via MQTT from Tasmota smart plug")
    args = parser.parse_args()
    print("Running inference with algorithm:", args.algo, "Use swtpm:", args.use_swtpm)
    run_inference(
        args.algo,
        use_swtpm=args.use_swtpm,
        fail_quote=args.fail_quote,
        fail_hash=args.fail_hash,
        fail_verify=args.fail_verify,
        collect_power=args.collect_power
    )
