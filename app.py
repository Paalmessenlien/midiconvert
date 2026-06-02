#!/usr/bin/env python3
"""Flask web UI for the midiconvert PDF -> MIDI pipeline.

Local single-user tool. Upload a sheet-music PDF, watch OMR progress, then play
the resulting MIDI in-browser and download the .mid / .mxl.

Run:
    .venv/bin/python app.py
    # open http://127.0.0.1:5000
"""
from __future__ import annotations

import threading
import traceback
import uuid
from pathlib import Path

from flask import (
    Flask, abort, jsonify, render_template, request, send_file,
)

import pipeline

HERE = Path(__file__).resolve().parent
JOBS_DIR = HERE / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB upload cap

# In-memory job registry. Lost on restart; on-disk artifacts in jobs/<id>/ persist.
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _set(job_id: str, **fields) -> None:
    with _LOCK:
        JOBS.setdefault(job_id, {}).update(fields)


def _worker(job_id: str, pdf_path: Path, outdir: Path, opts: dict) -> None:
    def on_step(label: str, percent: float) -> None:
        _set(job_id, state="running", step=label, percent=round(percent, 1))

    try:
        result = pipeline.run_pipeline(pdf_path, outdir, on_step=on_step, **opts)
        _set(job_id, state="done", step="Done", percent=100.0,
             stem=result["stem"])
    except pipeline.PipelineError as e:
        _set(job_id, state="error", error=str(e))
    except Exception:  # pragma: no cover - surface unexpected failures cleanly
        _set(job_id, state="error", error=traceback.format_exc())


def _int_arg(name: str, default: int) -> int:
    try:
        return int(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/convert", methods=["POST"])
def convert_endpoint():
    file = request.files.get("pdf")
    if file is None or not file.filename:
        return jsonify(error="No file uploaded."), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify(error="Please upload a .pdf file."), 400

    # Parse conversion options (mirror convert.py CLI flags).
    opts: dict = {
        "voice_program": _int_arg("voice_program", 53),
        "piano_program": _int_arg("piano_program", 0),
        "tempo_fix": request.form.get("tempo_fix", "true") != "false",
        "repair_rh": request.form.get("repair_rh", "false") == "true",
    }
    eighth = request.form.get("eighth_bpm", "").strip()
    if eighth:
        try:
            opts["eighth_bpm"] = float(eighth)
        except ValueError:
            return jsonify(error="eighth_bpm must be a number."), 400

    job_id = uuid.uuid4().hex
    outdir = JOBS_DIR / job_id
    outdir.mkdir(parents=True, exist_ok=True)
    pdf_path = outdir / "input.pdf"
    file.save(pdf_path)

    # Remember the original name for nicer downloads.
    display = Path(file.filename).stem
    _set(job_id, state="queued", step="Queued", percent=0.0, display=display)

    threading.Thread(
        target=_worker, args=(job_id, pdf_path, outdir, opts), daemon=True
    ).start()
    return jsonify(job_id=job_id)


@app.route("/api/jobs/<job_id>")
def job_status(job_id: str):
    with _LOCK:
        job = JOBS.get(job_id)
    if job is None:
        abort(404)
    return jsonify(job_id=job_id, **job)


def _artifact(job_id: str, suffix: str):
    with _LOCK:
        job = JOBS.get(job_id)
    if job is None or job.get("state") != "done":
        abort(404)
    path = JOBS_DIR / job_id / f"{job['stem']}{suffix}"
    if not path.is_file():
        abort(404)
    download_name = f"{job.get('display', job['stem'])}{suffix}"
    return send_file(path, as_attachment=(suffix != ".mid"),
                     download_name=download_name)


@app.route("/api/jobs/<job_id>/midi")
def job_midi(job_id: str):
    return _artifact(job_id, ".mid")


@app.route("/api/jobs/<job_id>/musicxml")
def job_musicxml(job_id: str):
    return _artifact(job_id, ".mxl")


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="File too large (max 25 MB)."), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
