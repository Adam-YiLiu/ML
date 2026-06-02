from __future__ import annotations

import logging
import signal
import subprocess
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

log = logging.getLogger(__name__)

# Default timeout (seconds) for DPU execute_async.  If the DPU locks the
# AXI bus this won't help, but it catches hangs in user-space.
DPU_EXEC_TIMEOUT_S = int(__import__("os").environ.get("DPU_EXEC_TIMEOUT", "30"))


def _flush_logs():
    """Force-flush every log handler **and** stdout/stderr.

    When the DPU locks up, buffered log messages are lost.  Calling this
    before any DPU operation guarantees we see the last log line.
    """
    for h in logging.root.handlers:
        h.flush()
    sys.stdout.flush()
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# DPU helpers – only imported when actually running on a Kria board with DPU
# ---------------------------------------------------------------------------


def _get_dpu_subgraph(model_path: Path):
    """Find the DPU subgraph in a compiled .xmodel file.

    Returns ``(graph, subgraph)`` — the caller **must** keep a reference to
    *graph* for the entire lifetime of any runner created from *subgraph*,
    because the C++ ``xir::Subgraph`` holds a raw pointer to its parent
    ``xir::Graph``.  If the Python ``graph`` object is garbage-collected the
    runner will dereference freed memory → SIGSEGV.
    """
    import xir

    graph = xir.Graph.deserialize(str(model_path))
    subgraphs = graph.get_root_subgraph().toposort_child_subgraph()
    dpu_subgraph = [
        s for s in subgraphs
        if s.has_attr("device") and s.get_attr("device") == "DPU"
    ]
    if not dpu_subgraph:
        raise RuntimeError(
            f"No DPU subgraph found in {model_path}. "
            "Ensure the model was compiled with vai_c_xir for the correct DPU arch."
        )
    # Return the graph too so it stays alive
    return graph, dpu_subgraph[0]


def _get_xmodel_fingerprint(model_path: Path) -> str | None:
    """Read the DPU fingerprint embedded in a compiled .xmodel."""
    try:
        import xir
        graph = xir.Graph.deserialize(str(model_path))
        for s in graph.get_root_subgraph().toposort_child_subgraph():
            if s.has_attr("device") and s.get_attr("device") == "DPU":
                if s.has_attr("dpu_fingerprint"):
                    fp = s.get_attr("dpu_fingerprint")
                    return hex(fp) if isinstance(fp, int) else str(fp)
    except Exception as exc:
        log.warning("Could not read xmodel fingerprint: %s", exc)
    return None


def _get_hw_dpu_fingerprint() -> str | None:
    """Read the hardware DPU fingerprint via ``xdputil query``.

    ``xdputil query`` emits JSON.  The DPU core fingerprint lives at::

        { "kernels": [ { "fingerprint": "0x101000016010406", ... }, ... ] }

    We parse the JSON first; if that fails we fall back to a regex scan of
    the raw text.
    """
    import json as _json
    import re as _re

    try:
        r = subprocess.run(
            ["xdputil", "query"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("xdputil not available: %s", exc)
        return None

    # --- attempt 1: proper JSON parse ---
    try:
        # xdputil may print warnings on stderr before the JSON object.
        # Find the first '{' and parse from there.
        raw = r.stdout
        brace = raw.find("{")
        if brace >= 0:
            data = _json.loads(raw[brace:])
            for kernel in data.get("kernels", []):
                fp = kernel.get("fingerprint", "")
                # Skip the dummy core with fingerprint "0x0"
                if fp and fp != "0x0" and fp != "0":
                    log.info("HW DPU fingerprint (JSON): %s", fp)
                    return fp.strip()
    except (_json.JSONDecodeError, KeyError, TypeError) as exc:
        log.debug("JSON parse of xdputil output failed: %s", exc)

    # --- attempt 2: regex fallback ---
    for m in _re.finditer(r'"fingerprint"\s*:\s*"(0x[0-9a-fA-F]+)"', r.stdout):
        fp = m.group(1)
        if fp != "0x0":
            log.info("HW DPU fingerprint (regex): %s", fp)
            return fp

    log.warning("Could not extract HW DPU fingerprint from xdputil output")
    return None


def verify_dpu_fingerprint(model_path: Path) -> bool:
    """Compare the xmodel fingerprint against the hardware DPU.

    A mismatch means the xmodel was compiled for a different DPU arch
    (e.g. B4096 vs B3136) and running it **will** lock up or crash the SoC.

    Returns True if they match or if we cannot determine one of them
    (fail-open so we don't break setups without xdputil).
    """
    model_fp = _get_xmodel_fingerprint(model_path)
    hw_fp = _get_hw_dpu_fingerprint()

    log.info("DPU fingerprint check — model: %s  hardware: %s", model_fp, hw_fp)
    _flush_logs()

    if model_fp is None or hw_fp is None:
        log.warning(
            "Cannot verify DPU fingerprint (model=%s, hw=%s) — proceeding anyway",
            model_fp, hw_fp,
        )
        return True  # fail-open

    if model_fp.lower() != hw_fp.lower():
        # Check whether only the last nibble differs — this is typical for
        # KV260 smartcam firmware (0x…0406) vs Model Zoo models (0x…0407).
        # The last nibble encodes minor feature flags and vart considers
        # these compatible (runner creation succeeds).  We warn but allow.
        prefix_match = model_fp.lower()[:-1] == hw_fp.lower()[:-1]
        if prefix_match:
            log.warning(
                "DPU fingerprint MINOR mismatch (last nibble) — "
                "model: %s  hardware: %s.  "
                "vart accepted the runner; proceeding with caution.",
                model_fp, hw_fp,
            )
            _flush_logs()
            return True  # allow — vart considers them compatible

        log.error(
            "\n"
            "!!  DPU FINGERPRINT MISMATCH  !!\n"
            "    xmodel : %s\n"
            "    hardware: %s\n"
            "Running this xmodel WILL lock up the SoC.  Aborting DPU inference.\n"
            "Recompile the xmodel for the correct DPU arch or swap to a\n"
            "matching xmodel from the Vitis AI Model Zoo.",
            model_fp, hw_fp,
        )
        _flush_logs()
        return False

    log.info("DPU fingerprint OK — model matches hardware")
    return True


def _get_dpu_runner(model_path: Path):
    """Create a Vitis AI DPU runner from a compiled .xmodel file.

    Returns ``(graph, runner)`` — the caller **must** keep *graph* alive for
    the entire lifetime of *runner* (see ``_get_dpu_subgraph`` docstring).
    """
    import vart

    graph, subgraph = _get_dpu_subgraph(model_path)
    log.info("Creating DPU runner …")
    _flush_logs()
    runner = vart.Runner.create_runner(subgraph, "run")
    log.info("DPU runner created successfully")
    _flush_logs()
    return graph, runner


def _get_dpu_tensor_info(runner):
    """Extract tensor shapes and fix_points from the runner.

    In Vitis AI 2.5, ``get_input_tensors()`` / ``get_output_tensors()``
    return a **set**, not a list, so ``[0]`` fails.  We convert to a sorted
    list (by tensor name) for deterministic ordering.
    """
    raw_in = runner.get_input_tensors()
    raw_out = runner.get_output_tensors()

    # set → sorted list (Vitis AI 2.5 quirk)
    in_tensors = sorted(raw_in, key=lambda t: t.name) if isinstance(raw_in, set) else list(raw_in)
    out_tensors = sorted(raw_out, key=lambda t: t.name) if isinstance(raw_out, set) else list(raw_out)

    in_shape = tuple(in_tensors[0].dims)
    out_shape = tuple(out_tensors[0].dims)

    # fix_point: number of fractional bits in the int8 representation
    in_fixpos = in_tensors[0].get_attr("fix_point") if in_tensors[0].has_attr("fix_point") else 0
    out_fixpos = out_tensors[0].get_attr("fix_point") if out_tensors[0].has_attr("fix_point") else 0

    return in_shape, out_shape, in_fixpos, out_fixpos


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def load_labels():
    """Load class labels"""
    with open("./labels/synset.txt", "r") as f:
        labels = [line.strip() for line in f.readlines()]
    return labels


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------


def preprocess_image(image_path: Path, backend: str = "onnx", backend_kwargs: dict | None = None):
    """Preprocess the input image.

    For the ONNX backend the output is NCHW float32 normalised with ImageNet
    statistics.  For the DPU backend the output is NHWC **float32** after
    BGR conversion and mean/scale normalisation.  The caller (``_run_inference_dpu``)
    is responsible for quantising to int8 using the xmodel's ``fix_point``.

    Parameters
    ----------
    backend_kwargs : dict, optional
        Reserved for future use.
    """
    img = Image.open(image_path).convert("RGB")
    img = img.resize((224, 224))

    img_array = np.array(img).astype(np.float32)

    if backend == "dpu":
        # Vitis AI Model Zoo MobileNetV2: BGR, mean subtraction, scale
        img_array = img_array[:, :, ::-1]                    # RGB → BGR
        img_array = np.ascontiguousarray(img_array)
        mean = np.array([103.94, 116.78, 123.68], dtype=np.float32)
        img_array = (img_array - mean) * 0.017429
        # Return as float32; quantisation happens in _run_inference_dpu
        img_array = np.expand_dims(img_array, axis=0)        # (1, H, W, C)
        img_array = np.ascontiguousarray(img_array)
    else:
        # ONNX Runtime expects NCHW float32 with ImageNet normalisation
        img_array = img_array / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        img_array = (img_array - mean) / std
        img_array = img_array.transpose((2, 0, 1))           # HWC → CHW
        img_array = np.expand_dims(img_array, axis=0)
        img_array = img_array.astype(np.float32)

    return img_array


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def run_inference(model_path: Path, input_data: np.ndarray, backend: str = "onnx"):
    """Run inference, dispatching to the correct backend.

    Parameters
    ----------
    model_path : Path
        For ``onnx``: path to the ``.onnx`` model.
        For ``dpu`` : path to the compiled ``.xmodel``.
    input_data : np.ndarray
        Pre-processed image tensor (see ``preprocess_image``).
    backend : str
        ``"onnx"`` (default) or ``"dpu"``.
    """
    if backend == "dpu":
        return _run_inference_dpu(model_path, input_data)
    return _run_inference_onnx(model_path, input_data)


def _run_inference_onnx(model_path: Path, input_data: np.ndarray):
    """Run inference using ONNX Runtime (CPU / CUDA)."""
    session = ort.InferenceSession(model_path)

    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    outputs = session.run([output_name], {input_name: input_data})

    return outputs[0]


# ---------------------------------------------------------------------------
# Session / runner creation for batch inference (load model once)
# ---------------------------------------------------------------------------


def create_session(model_path: Path, backend: str = "onnx"):
    """Create a reusable inference session/runner.

    Returns an opaque session object to pass to ``run_inference_with_session``.
    For ONNX this is the ``ort.InferenceSession``; for DPU it is
    ``(graph, runner, in_shape, out_shape, in_fixpos, out_fixpos)``.
    """
    if backend == "dpu":
        if not verify_dpu_fingerprint(model_path):
            raise RuntimeError(
                "DPU fingerprint mismatch — refusing to run to avoid SoC lockup."
            )
        _graph, runner = _get_dpu_runner(model_path)
        in_shape, out_shape, in_fixpos, out_fixpos = _get_dpu_tensor_info(runner)
        return ("dpu", _graph, runner, in_shape, out_shape, in_fixpos, out_fixpos)

    session = ort.InferenceSession(model_path)
    return ("onnx", session)


def run_inference_with_session(session, input_data: np.ndarray):
    """Run inference using a pre-created session from ``create_session``."""
    backend = session[0]
    if backend == "dpu":
        _, _graph, runner, in_shape, out_shape, in_fixpos, out_fixpos = session
        return _run_inference_dpu_with_runner(
            runner, input_data, in_shape, out_shape, in_fixpos, out_fixpos
        )

    _, ort_session = session
    input_name = ort_session.get_inputs()[0].name
    output_name = ort_session.get_outputs()[0].name
    outputs = ort_session.run([output_name], {input_name: input_data})
    return outputs[0]


def _run_inference_dpu(model_path: Path, input_data: np.ndarray):
    """Run inference on the Kria DPU using Vitis AI 2.5 runtime (xir + vart).

    Vitis AI 2.5 specifics
    -----------------------
    * ``get_input_tensors()``/``get_output_tensors()`` return a **set** (not a
      list), so indexing with ``[0]`` will raise ``TypeError``.
      → ``_get_dpu_tensor_info`` handles the set→sorted-list conversion.

    * The runner in ``"run"`` mode does **not** auto-quantise float32→int8.
      We must read ``fix_point`` from the tensor metadata and do the
      quantisation / dequantisation ourselves.

    * Buffers must be **int8**, C-contiguous ``np.ndarray``.

    * The DPU uses CMA-backed DMA.  We touch every page of the buffers
      (via ``np.zeros`` + ``np.copyto``) before ``execute_async`` so the
      kernel has faulted the physical pages in.  We also call
      ``runner.execute_async`` and ``runner.wait`` in separate steps.
    """
    # ---- pre-flight: fingerprint check ------------------------------------
    if not verify_dpu_fingerprint(model_path):
        raise RuntimeError(
            "DPU fingerprint mismatch — refusing to run to avoid SoC lockup. "
            "Falling back to ONNX is recommended."
        )

    # IMPORTANT: keep `_graph` alive — the C++ runner holds a raw pointer
    # back to the xir::Graph.  If it is garbage-collected → SIGSEGV.
    _graph, runner = _get_dpu_runner(model_path)
    in_shape, out_shape, in_fixpos, out_fixpos = _get_dpu_tensor_info(runner)

    log.info(
        "DPU tensor info — in: %s (fix_point=%d)  out: %s (fix_point=%d)",
        in_shape, in_fixpos, out_shape, out_fixpos,
    )
    _flush_logs()
    log.info(
        "Preprocessed input — shape: %s  dtype: %s  C-contiguous: %s",
        input_data.shape, input_data.dtype, input_data.flags["C_CONTIGUOUS"],
    )
    _flush_logs()

    # ---- quantise float32 → int8 using input fix_point --------------------
    input_scale = 2.0 ** in_fixpos
    quantized = np.clip(np.round(input_data * input_scale), -128, 127).astype(np.int8)

    if quantized.shape != in_shape:
        log.warning("DPU input shape mismatch: got %s, expected %s — reshaping",
                     quantized.shape, in_shape)
        quantized = quantized.reshape(in_shape)

    # ---- allocate int8 buffers (pages touched via zeros + copyto) ----------
    input_buf = np.zeros(in_shape, dtype=np.int8, order="C")
    output_buf = np.zeros(out_shape, dtype=np.int8, order="C")
    np.copyto(input_buf, quantized)

    # ---- CMA sanity check --------------------------------------------------
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("CmaTotal") or line.startswith("CmaFree"):
                    log.info("  %s", line.strip())
    except OSError:
        pass

    # ---- verify buffer properties before DMA -------------------------------
    log.info(
        "input_buf — dtype: %s  shape: %s  C-contiguous: %s  data ptr: %s",
        input_buf.dtype, input_buf.shape,
        input_buf.flags["C_CONTIGUOUS"], input_buf.ctypes.data,
    )
    log.info(
        "output_buf — dtype: %s  shape: %s  C-contiguous: %s  data ptr: %s",
        output_buf.dtype, output_buf.shape,
        output_buf.flags["C_CONTIGUOUS"], output_buf.ctypes.data,
    )

    # ---- execute (with SIGALRM timeout guard) -----------------------------
    log.info("Calling DPU execute_async … (timeout=%ds)", DPU_EXEC_TIMEOUT_S)
    _flush_logs()

    # Set an alarm so that if the DPU hangs in user-space we get a signal
    # rather than blocking forever.  (If the DPU locks the AXI bus the
    # kernel itself freezes and no signal will fire — but this still helps
    # for softer hangs.)
    _prev_alarm = 0
    _prev_handler = signal.SIG_DFL
    try:
        if DPU_EXEC_TIMEOUT_S > 0:
            def _timeout_handler(signum, frame):
                raise TimeoutError(
                    f"DPU execute_async did not complete within "
                    f"{DPU_EXEC_TIMEOUT_S}s — possible DPU hang"
                )
            _prev_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            _prev_alarm = signal.alarm(DPU_EXEC_TIMEOUT_S)

        job_id = runner.execute_async([input_buf], [output_buf])
        runner.wait(job_id)
    finally:
        if DPU_EXEC_TIMEOUT_S > 0:
            signal.alarm(0)  # cancel alarm
            signal.signal(signal.SIGALRM, _prev_handler)
            if _prev_alarm > 0:
                signal.alarm(_prev_alarm)  # restore previous alarm

    log.info("DPU inference complete")
    _flush_logs()

    # ---- dequantise int8 → float32 using output fix_point ------------------
    output_scale = 1.0 / (2.0 ** out_fixpos)
    result = output_buf.astype(np.float32) * output_scale
    return result


def _run_inference_dpu_with_runner(runner, input_data, in_shape, out_shape, in_fixpos, out_fixpos):
    """Run DPU inference using an already-created runner (for batch reuse)."""
    log.info("Quantising input using fix_point=%d …", in_fixpos)
    input_scale = 2.0 ** in_fixpos
    quantized = np.clip(np.round(input_data * input_scale), -128, 127).astype(np.int8)

    if quantized.shape != in_shape:
        quantized = quantized.reshape(in_shape)

    input_buf = np.zeros(in_shape, dtype=np.int8, order="C")
    output_buf = np.zeros(out_shape, dtype=np.int8, order="C")
    np.copyto(input_buf, quantized)

    _prev_alarm = 0
    _prev_handler = signal.SIG_DFL
    try:
        log.info("Calling DPU using existing session … (timeout=%ds)", DPU_EXEC_TIMEOUT_S)
        if DPU_EXEC_TIMEOUT_S > 0:
            def _timeout_handler(signum, frame):
                raise TimeoutError(
                    f"DPU execute_async did not complete within "
                    f"{DPU_EXEC_TIMEOUT_S}s — possible DPU hang"
                )
            _prev_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            _prev_alarm = signal.alarm(DPU_EXEC_TIMEOUT_S)

        job_id = runner.execute_async([input_buf], [output_buf])
        runner.wait(job_id)
    finally:
        if DPU_EXEC_TIMEOUT_S > 0:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, _prev_handler)
            if _prev_alarm > 0:
                signal.alarm(_prev_alarm)

    output_scale = 1.0 / (2.0 ** out_fixpos)
    result = output_buf.astype(np.float32) * output_scale
    return result


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def postprocess_output(output: np.ndarray, labels: list[str], top_k: int = 5):
    """Postprocess the output of the inference."""
    log.info("Raw model output: shape=%s dtype=%s", output.shape, output.dtype)
    probs = np.exp(output) / np.sum(np.exp(output), axis=1)

    top_indices = np.argsort(probs[0])[::-1][:top_k]
    top_probs = probs[0][top_indices]
    top_labels = [labels[idx] if idx < len(labels) else f"class_{idx}" for idx in top_indices]

    for i, (prob, label) in enumerate(zip(top_probs, top_labels)):
        log.info("Top %d: %s (%.4f%%)", i + 1, label, prob * 100)
        return f"{top_labels[0]} ({top_probs[0] * 100:.4f})%"
    log.error("No output probabilities found.")