#!/usr/bin/env python3
"""Flask web UI for midiconvert.

Two directions, one page:
  * a sheet-music PDF  -> MIDI   (Audiveris OMR + music21, via pipeline.py)
  * an audio file      -> MIDI   (basic-pitch transcription, via audio2midi.py)

Local single-user tool. Upload, watch progress, play the result in-page (piano-roll
+ live note read-out) and download the artifacts.

Run:
    .venv/bin/python app.py     # http://127.0.0.1:5000
"""
from __future__ import annotations

import threading
import traceback
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

import pipeline
import audio2midi

HERE = Path(__file__).resolve().parent
JOBS_DIR = HERE / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

PDF_EXTS = {".pdf"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".aif", ".aiff"}

# Per-logical download filename suffix + whether to force download (vs inline play).
ARTIFACT_SPEC = {
    "midi": (".mid", False),
    "musicxml": (".mxl", True),
    "melody": (".melody.mid", False),
    "full": (".full.mid", False),
    "notes": (".notes.csv", True),
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB (audio can be larger)

JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _set(job_id: str, **fields) -> None:
    with _LOCK:
        JOBS.setdefault(job_id, {}).update(fields)


def _num(name, default, cast):
    try:
        return cast(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


def _run_pdf(input_path, outdir, opts, on_step):
    result = pipeline.run_pipeline(input_path, outdir, on_step=on_step, **opts)
    return {
        "files": {"midi": result["mid"], "musicxml": result["mxl"]},
        "player": [{"label": "MIDI", "logical": "midi"}],
        "downloads": [
            {"label": "Download MIDI", "logical": "midi"},
            {"label": "Download MusicXML", "logical": "musicxml"},
        ],
        "info": "Recognition not perfect? The MusicXML is the correction surface — "
                "fix it in MuseScore and re-run.",
    }


def _run_audio(input_path, outdir, opts, on_step):
    info = audio2midi.transcribe(input_path, outdir, on_step=on_step, **opts)
    rng = f" ({info['range'][0]}–{info['range'][1]})" if info["range"] else ""
    return {
        "files": {
            "melody": info["files"]["melody"],
            "full": info["files"]["full"],
            "notes": info["files"]["notes_csv"],
        },
        "player": [
            {"label": "Melody", "logical": "melody"},
            {"label": "Full", "logical": "full"},
        ],
        "downloads": [
            {"label": "Melody MIDI", "logical": "melody"},
            {"label": "Full MIDI", "logical": "full"},
            {"label": "Notes (CSV)", "logical": "notes"},
        ],
        "info": f"Transcribed {info['full_notes']} notes; melody line = "
                f"{info['melody_notes']} notes{rng}. Audio transcription is "
                f"approximate — the melody is a best-effort lead line.",
    }


def _worker(job_id, input_path, outdir, kind, opts):
    def on_step(label, percent):
        _set(job_id, state="running", step=label, percent=round(percent, 1))

    try:
        runner = _run_pdf if kind == "pdf" else _run_audio
        out = runner(input_path, outdir, opts, on_step)
        _set(job_id, state="done", step="Done", percent=100.0,
             files={k: str(v) for k, v in out["files"].items()},
             player=out["player"], downloads=out["downloads"], info=out["info"])
    except pipeline.PipelineError as e:
        _set(job_id, state="error", error=str(e))
    except Exception:
        _set(job_id, state="error", error=traceback.format_exc())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/convert", methods=["POST"])
def convert_endpoint():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(error="No file uploaded."), 400
    ext = Path(file.filename).suffix.lower()
    if ext in PDF_EXTS:
        kind = "pdf"
        opts = {
            "voice_program": _num("voice_program", 53, int),
            "piano_program": _num("piano_program", 0, int),
            "tempo_fix": request.form.get("tempo_fix", "true") != "false",
            "repair_rh": request.form.get("repair_rh", "false") == "true",
        }
        eighth = request.form.get("eighth_bpm", "").strip()
        if eighth:
            try:
                opts["eighth_bpm"] = float(eighth)
            except ValueError:
                return jsonify(error="eighth_bpm must be a number."), 400
    elif ext in AUDIO_EXTS:
        kind = "audio"
        opts = {
            "onset_threshold": _num("onset_threshold", 0.5, float),
            "frame_threshold": _num("frame_threshold", 0.3, float),
            "melody_min": _num("melody_min", 55, int),
            "melody_max": _num("melody_max", 84, int),
            "melody_min_ms": _num("melody_min_ms", 120.0, float),
        }
    else:
        return jsonify(error=f"Unsupported file type '{ext}'. Upload a PDF or audio "
                             f"file ({', '.join(sorted(AUDIO_EXTS))}).") , 400

    job_id = uuid.uuid4().hex
    outdir = JOBS_DIR / job_id
    outdir.mkdir(parents=True, exist_ok=True)
    input_path = outdir / f"input{ext}"
    file.save(input_path)

    _set(job_id, state="queued", step="Queued", percent=0.0, kind=kind,
         display=Path(file.filename).stem)
    threading.Thread(target=_worker, args=(job_id, input_path, outdir, kind, opts),
                     daemon=True).start()
    return jsonify(job_id=job_id, kind=kind)


@app.route("/api/jobs/<job_id>")
def job_status(job_id):
    with _LOCK:
        job = JOBS.get(job_id)
    if job is None:
        abort(404)
    # Don't leak server-side absolute paths; expose only logical artifact names.
    public = {k: v for k, v in job.items() if k != "files"}
    return jsonify(job_id=job_id, **public)


@app.route("/api/jobs/<job_id>/f/<logical>")
def job_artifact(job_id, logical):
    with _LOCK:
        job = JOBS.get(job_id)
    if job is None or job.get("state") != "done":
        abort(404)
    files = job.get("files", {})
    if logical not in files or logical not in ARTIFACT_SPEC:
        abort(404)
    path = Path(files[logical])
    if not path.is_file():
        abort(404)
    suffix, as_attach = ARTIFACT_SPEC[logical]
    return send_file(path, as_attachment=as_attach,
                     download_name=f"{job.get('display', 'output')}{suffix}")


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="File too large (max 50 MB)."), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
