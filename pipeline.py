#!/usr/bin/env python3
"""Reusable PDF -> MIDI pipeline shared by the CLI and the web UI.

Mirrors pdf2midi.sh: locate the Audiveris launcher, run OMR in batch mode, then
hand the recognised MusicXML to convert.convert(). The only addition over the
shell script is progress reporting: Audiveris' ordered step log is parsed so a
caller (e.g. the web UI) can show a real progress bar.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections import deque
from pathlib import Path
from typing import Callable, Optional

import convert

HERE = Path(__file__).resolve().parent

# Audiveris transcribes each sheet through these steps, in order. We use the
# index of the reported step to estimate overall progress.
AUDIVERIS_STEPS = [
    "LOAD", "BINARY", "SCALE", "GRID", "HEADERS", "STEM_SEEDS", "BEAMS",
    "LEDGERS", "HEADS", "STEMS", "REDUCTION", "CUE_BEAMS", "TEXTS", "MEASURES",
    "CHORDS", "CURVES", "SYMBOLS", "RHYTHMS", "PAGE",
]
_STEP_INDEX = {name: i for i, name in enumerate(AUDIVERIS_STEPS)}

# OMR gets 0-90% of the bar; the music21 MIDI step takes the rest.
_OMR_SHARE = 90.0

_SHEETS_RE = re.compile(r"(\d+)\s+sheets?\s+in")
_CONTEXT_SHEET_RE = re.compile(r"#(\d+)[\]\s]")
_STEP_RE = re.compile(r"StepMonitoring.*\|\s*([A-Z_]+)\s*$")


class PipelineError(RuntimeError):
    """Raised when OMR fails or produces no MusicXML; carries the log tail."""


def find_audiveris() -> str:
    """Locate the Audiveris launcher across platforms (mirrors pdf2midi.sh)."""
    candidates = [
        os.environ.get("AUDIVERIS"),
        str(HERE / "tools/audiveris-root/opt/audiveris/bin/Audiveris"),
        "/Applications/Audiveris.app/Contents/MacOS/Audiveris",
        str(Path.home() / "Applications/Audiveris.app/Contents/MacOS/Audiveris"),
        shutil.which("audiveris"),
        shutil.which("Audiveris"),
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise PipelineError(
        "Audiveris launcher not found. Install it, or set the AUDIVERIS "
        "environment variable to the launcher path."
    )


class _ProgressTracker:
    """Turns Audiveris log lines into (label, percent) updates."""

    def __init__(self) -> None:
        self.sheets = 1
        self.furthest = -1  # furthest (sheet*steps + step) seen so far

    def update(self, line: str) -> Optional[tuple[str, float]]:
        m = _SHEETS_RE.search(line)
        if m:
            self.sheets = max(1, int(m.group(1)))
            return ("Loading score", 2.0)

        if "exported to" in line and ".mxl" in line:
            return ("Exporting MusicXML", _OMR_SHARE)

        sm = _STEP_RE.search(line)
        if not sm:
            return None
        step = sm.group(1)
        if step not in _STEP_INDEX:
            return None

        sheet = 1
        cm = _CONTEXT_SHEET_RE.search(line)
        if cm:
            sheet = int(cm.group(1))

        n_steps = len(AUDIVERIS_STEPS)
        position = (sheet - 1) * n_steps + _STEP_INDEX[step]
        if position <= self.furthest:
            return None
        self.furthest = position

        total = self.sheets * n_steps
        pct = min(_OMR_SHARE, (position + 1) / total * _OMR_SHARE)
        label = f"OMR: {step.replace('_', ' ').title()} (sheet {sheet}/{self.sheets})"
        return (label, pct)


def run_pipeline(
    pdf: Path,
    outdir: Path,
    *,
    on_step: Optional[Callable[[str, float], None]] = None,
    **convert_opts,
) -> dict:
    """Run OMR + MIDI conversion. Returns {'stem','mxl','mid'} or raises PipelineError.

    `on_step(label, percent)` is called as progress is made (percent 0-100).
    `convert_opts` are forwarded to convert.convert (voice_program, piano_program,
    tempo_fix, eighth_bpm).
    """
    pdf = Path(pdf)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    def emit(label: str, pct: float) -> None:
        if on_step:
            on_step(label, pct)

    aud = find_audiveris()
    env = dict(os.environ)
    tessdata = HERE / "tools/tessdata"
    if tessdata.is_dir():
        env["TESSDATA_PREFIX"] = str(tessdata)
    env["JAVA_TOOL_OPTIONS"] = "-Djava.awt.headless=true"

    emit("Starting OMR engine", 1.0)
    cmd = [aud, "-batch", "-transcribe", "-export", "-output", str(outdir), str(pdf)]
    proc = subprocess.Popen(
        cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    tracker = _ProgressTracker()
    tail: deque[str] = deque(maxlen=40)
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        tail.append(line)
        update = tracker.update(line)
        if update:
            emit(*update)
    code = proc.wait()

    stem = pdf.stem
    mxl = outdir / f"{stem}.mxl"
    if not mxl.is_file():
        raise PipelineError(
            f"Audiveris produced no MusicXML (exit {code}).\n\n"
            + "\n".join(tail)
        )

    emit("Converting to MIDI", 93.0)
    mid = outdir / f"{stem}.mid"
    convert.convert(mxl, mid, **convert_opts)

    emit("Done", 100.0)
    return {"stem": stem, "mxl": str(mxl), "mid": str(mid)}
