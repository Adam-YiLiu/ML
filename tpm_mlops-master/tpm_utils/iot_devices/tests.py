import csv
import random
import time
from datetime import datetime, timezone
from os import listdir, makedirs, path
from pathlib import Path

from main import main_wrapper as run_pipeline

base_dir = Path(path.expanduser("~"))
results_path = base_dir / "evaluation"
model_path = base_dir / "ml_models" / "mobilenetv2-7.onnx"
tampered_model_path = base_dir / "ml_models" / "mobilenetv2-7_tampered.onnx"
images_path = base_dir / "images"

makedirs(results_path, exist_ok=True)

csv_headers = [
    "image_name",
    "integrity_start",
    "integrity_end",
    "integrity_duration_ms",
    "integrity_result",
    "integrity_check_enabled",
    "inference_start",
    "inference_end",
    "inference_duration_ms",
    "inference_result",
]

time.sleep(10)

random_images = set()
for _ in range(3):
    random_n = random.randint(1, 42)
    while random_n in random_images:
        random_n = random.randint(1, 42)

    random_images.add(random.randint(1, 42))

print(f"[INFO] Images chosen for tamper test: {random_images}")

print("[INFO] Starting tests")

USE_SWTPM = True
for i in range(1, 6):
    print(f"[INFO] Iteration {i}")

    csv_file = results_path / f"inference_results_{i}.csv"

    results = []

    # inference WITH integrity check
    start = datetime.now(timezone.utc)
    for image in listdir(images_path):
        if "jpg" not in image:
            continue
        if any(n == int(image.split(".")[0]) for n in random_images):
            int_summary, inf_summary = run_pipeline(tampered_model_path, images_path / image, True, use_swtpm=USE_SWTPM)
        else:
            int_summary, inf_summary = run_pipeline(model_path, images_path / image, True, use_swtpm=USE_SWTPM)

        results.append({"image_name": image, "int_summary": int_summary, "inf_summary": inf_summary})

    end = datetime.now(timezone.utc)

    inference_summary = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration": (end - start).total_seconds() * 1000,
    }
    print("--- WITH integrity check", inference_summary)

    time.sleep(60)

    # inference WITHOUT integrity check
    start = datetime.now(timezone.utc)
    for image in listdir(images_path):
        if "jpg" not in image:
            continue
        int_summary, inf_summary = run_pipeline(model_path, images_path / image, False, use_swtpm=USE_SWTPM)

        results.append({"image_name": image, "int_summary": int_summary, "inf_summary": inf_summary})

    end = datetime.now(timezone.utc)

    inference_summary = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration": (end - start).total_seconds() * 1000,
    }
    print("--- WITHOUT integrity check", inference_summary)

    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()

        for result in results:
            row_data = {
                "image_name": result["image_name"],
                "integrity_start": result["int_summary"]["start"].isoformat(),
                "integrity_end": result["int_summary"]["end"].isoformat(),
                "integrity_duration_ms": result["int_summary"]["duration"],
                "integrity_result": result["int_summary"]["result"],
                "integrity_check_enabled": result["int_summary"]["check_integrity"],
                "inference_start": result["inf_summary"]["start"].isoformat(),
                "inference_end": result["inf_summary"]["end"].isoformat(),
                "inference_duration_ms": result["inf_summary"]["duration"],
                "inference_result": result["inf_summary"]["result"],
            }
            writer.writerow(row_data)

    if i < 5:
        time.sleep(60)

print("[INFO] Finished tests")
