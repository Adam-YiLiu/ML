"""
HTTP-polling power monitoring module.

Polls a Tasmota smart-plug via its HTTP command API (STATUS 8) every second
in a background thread, collecting voltage / current / power readings.
On Kria boards, also polls ``sudo xmutil xlnx_platformstats -p`` for SOM
power / current / voltage.

Provides helpers for merging those readings into Prometheus-style metrics.

Usage:
    from power_monitor import PowerMonitor

    pm = PowerMonitor(host=os.environ.get("POWER_MONITOR_IP", "192.168.3.29"))
    pm.start()
    # ... do work ...
    pm.stop()
    readings = pm.get_readings()          # all collected samples
    merge_power_into_metrics(metrics, pm)  # add columns in-place
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from datetime import datetime

import requests

# ----------------------------------------------------------- Kria detection
_XMUTIL = shutil.which("xmutil")


def is_kria() -> bool:
    """Return True if running on a Kria board (xmutil available)."""
    return _XMUTIL is not None


def _read_som_stats() -> dict | None:
    """Run ``xmutil xlnx_platformstats -p`` and parse SOM totals.

    Returns dict with som_power_mw, som_current_ma, som_voltage_mv or None.
    """
    try:
        result = subprocess.run(
            ["/usr/bin/python3", "/usr/bin/xmutil", "xlnx_platformstats", "-p"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            print(f"[PowerMonitor] xmutil error: {result.stderr.strip()}")
            return None

        output = result.stdout
        power = current = voltage = None
        for line in output.splitlines():
            if "SOM total power" in line:
                m = re.search(r":\s*([\d.]+)", line)
                if m:
                    power = float(m.group(1))
            elif "SOM total current" in line:
                m = re.search(r":\s*([\d.]+)", line)
                if m:
                    current = float(m.group(1))
            elif "SOM total voltage" in line:
                m = re.search(r":\s*([\d.]+)", line)
                if m:
                    voltage = float(m.group(1))

        if power is not None and current is not None and voltage is not None:
            return {
                "som_power_mw": power,
                "som_current_ma": current,
                "som_voltage_mv": voltage,
            }
    except Exception as exc:
        print(f"[PowerMonitor] xmutil error: {exc}")
    return None


class PowerMonitor:
    """Collect power telemetry from a Tasmota device over HTTP.

    On Kria boards, also collects SOM power stats via xmutil.
    """

    def __init__(self, host: str, poll_interval: float = 1.0):
        self.url = f"http://{host}/cm?cmnd=STATUS+8"
        self.poll_interval = poll_interval
        self.is_kria = is_kria()

        self._lock = threading.Lock()
        self._readings: list[dict] = []
        self._thread: threading.Thread | None = None
        self._running = False

    # --------------------------------------------------------------- polling
    def _poll_loop(self):
        """Background loop: poll Tasmota (and optionally xmutil) every interval."""
        while self._running:
            reading: dict = {"timestamp": time.time()}

            # Tasmota smart plug ----------------------------------------
            try:
                resp = requests.get(self.url, timeout=5)
                resp.raise_for_status()
                payload = resp.json()
                energy = payload.get("StatusSNS", {}).get("ENERGY", {})
                voltage = energy.get("Voltage")
                current = energy.get("Current")
                if voltage is not None and current is not None:
                    voltage = float(voltage)
                    current = float(current)
                    reading["voltage"] = voltage
                    reading["current"] = current
                    reading["power_watts"] = round(voltage * current, 4)
            except Exception as exc:
                print(f"[PowerMonitor] HTTP poll error: {exc}")

            # Kria SOM stats --------------------------------------------
            if self.is_kria:
                som = _read_som_stats()
                if som:
                    reading.update(som)

            # Only store if we got at least some data
            if len(reading) > 1:  # more than just timestamp
                with self._lock:
                    self._readings.append(reading)

            time.sleep(self.poll_interval)

    # --------------------------------------------------------------- control
    def start(self):
        """Start the background HTTP polling thread."""
        if self._running:
            return
        self._running = True
        if self.is_kria:
            print("[PowerMonitor] Kria board detected — collecting SOM stats")
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Signal the polling thread to stop."""
        self._running = False

    def get_readings(self) -> list[dict]:
        """Return a *copy* of all collected readings."""
        with self._lock:
            return list(self._readings)


# -------------------------------------------------------------- merge helper
# All possible power columns (Tasmota + Kria SOM)
POWER_COLUMNS = ["voltage", "current", "power_watts",
                 "som_power_mw", "som_current_ma", "som_voltage_mv"]


def merge_power_into_metrics(metrics: list[dict], monitor: PowerMonitor) -> None:
    """Add power columns to *metrics* in-place.

    Uses forward-fill: for each Prometheus timestamp the most recent reading
    whose timestamp <= the metric timestamp is used.  Missing fields are None.
    """
    readings = monitor.get_readings()
    if not readings:
        for m in metrics:
            for col in POWER_COLUMNS:
                m[col] = None
        return

    readings.sort(key=lambda r: r["timestamp"])

    for m in metrics:
        try:
            metric_ts = datetime.fromisoformat(m["timestamp"]).timestamp()
        except (ValueError, TypeError):
            for col in POWER_COLUMNS:
                m[col] = None
            continue

        # Forward-fill: last reading with ts <= metric_ts
        best = None
        for r in readings:
            if r["timestamp"] <= metric_ts + 0.5:
                best = r
            else:
                break

        for col in POWER_COLUMNS:
            m[col] = best.get(col) if best else None
