#!/usr/bin/env python3
"""Transcribe an audio file (MP3/WAV/…) into MIDI + a notes list.

This is the *reverse* of the PDF pipeline: instead of reading engraved notes, it
runs Automatic Music Transcription on a recording. It uses Spotify's `basic-pitch`
(polyphonic) via its ONNX backend, then derives two outputs from a single pass:

    <stem>.full.mid     every note basic-pitch detects (dense on a full mix)
    <stem>.melody.mid   a cleaned, strictly monophonic "lead line"
    <stem>.notes.csv    the melody as start,end,dur,midi,note_name
    <stem>.notes.txt    the same, human-readable

AMT is approximate, especially on a full band mix -- treat the melody line as a
best-effort transcription, not ground truth.

Usage:
    python audio2midi.py INPUT.mp3 [OUTDIR] [options]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Flat spelling to match the rest of the project (static/app.js PITCH_NAMES).
PITCH_NAMES = ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B"]


def note_name(midi: int) -> str:
    return PITCH_NAMES[midi % 12] + str(midi // 12 - 1)


def extract_melody(note_events, *, lo: int, hi: int, min_ms: float):
    """Reduce polyphonic note events to one monophonic 'lead' line.

    note_events: list of (start_s, end_s, pitch_midi, amplitude, pitch_bends).
    Strategy: keep only notes in [lo, hi]; sort by onset; walk left to right and
    keep the most salient note (highest amplitude, tie-break higher pitch),
    trimming the previous kept note so it never overlaps the next onset. Finally
    drop notes shorter than min_ms.
    """
    min_s = min_ms / 1000.0
    cands = sorted(
        ((s, e, p, a) for (s, e, p, a, *_) in note_events if lo <= p <= hi),
        key=lambda n: (n[0], -n[3], -n[2]),
    )

    melody: list[list[float]] = []  # [start, end, pitch]
    for s, e, p, a in cands:
        if melody and s < melody[-1][1]:
            # Overlaps the current note: keep whichever is more salient.
            # `cands` is onset-sorted; the in-progress note was chosen as most
            # salient at its onset, so we let it ring and trim it to this onset
            # only if this new note actually starts a distinct, later event.
            if s <= melody[-1][0]:
                continue  # same onset cluster -> already took the salient one
            melody[-1][1] = min(melody[-1][1], s)  # trim previous to this onset
        melody.append([s, e, p])

    return [(s, e, int(p)) for s, e, p in melody if (e - s) >= min_s]


def write_melody_midi(melody, path: Path, *, program: int = 0) -> None:
    import pretty_midi

    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=program, name="Melody")
    for s, e, p in melody:
        inst.notes.append(pretty_midi.Note(velocity=96, pitch=p, start=s, end=e))
    pm.instruments.append(inst)
    pm.write(str(path))


def write_notes_list(melody, csv_path: Path, txt_path: Path) -> None:
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "start_s", "end_s", "dur_s", "midi", "note"])
        for i, (s, e, p) in enumerate(melody, 1):
            w.writerow([i, f"{s:.3f}", f"{e:.3f}", f"{e - s:.3f}", p, note_name(p)])
    with txt_path.open("w") as f:
        f.write("  #   start    dur    note\n")
        for i, (s, e, p) in enumerate(melody, 1):
            f.write(f"{i:4d}  {s:6.2f}s {e - s:5.2f}s  {note_name(p)}\n")


def transcribe(
    input_path: Path,
    outdir: Path,
    *,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    min_note_ms: float = 127.70,
    min_freq: float | None = None,
    max_freq: float | None = None,
    melody_min: int = 55,
    melody_max: int = 84,
    melody_min_ms: float = 120.0,
    on_step=None,
) -> dict:
    """Transcribe `input_path` to a full + melody MIDI and a notes list.

    `on_step(label, percent)` is called for progress (the predict() call is a
    single blocking step, so progress is coarse). Returns a dict with note counts,
    pitch range, and a `files` map of logical name -> Path.
    """
    def emit(label, pct):
        if on_step:
            on_step(label, pct)

    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    outdir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem

    emit("Loading transcription model", 5.0)
    _, midi_data, note_events = predict(
        str(input_path),
        ICASSP_2022_MODEL_PATH,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=min_note_ms,
        minimum_frequency=min_freq,
        maximum_frequency=max_freq,
        melodia_trick=True,
    )

    emit("Writing full transcription", 82.0)
    full_path = outdir / f"{stem}.full.mid"
    midi_data.write(str(full_path))

    emit("Extracting melody line", 90.0)
    melody = extract_melody(note_events, lo=melody_min, hi=melody_max, min_ms=melody_min_ms)
    melody_path = outdir / f"{stem}.melody.mid"
    csv_path = outdir / f"{stem}.notes.csv"
    txt_path = outdir / f"{stem}.notes.txt"
    write_melody_midi(melody, melody_path)
    write_notes_list(melody, csv_path, txt_path)

    emit("Done", 100.0)
    pitches = [p for *_, p in melody]
    return {
        "stem": stem,
        "full_notes": len(note_events),
        "melody_notes": len(melody),
        "range": (note_name(min(pitches)), note_name(max(pitches))) if pitches else None,
        "files": {
            "full": full_path,
            "melody": melody_path,
            "notes_csv": csv_path,
            "notes_txt": txt_path,
        },
    }


def parse_args(argv):
    p = argparse.ArgumentParser(description="Audio -> MIDI + notes (basic-pitch).")
    p.add_argument("input", type=Path, help="input audio file (mp3/wav/flac/…)")
    p.add_argument("outdir", type=Path, nargs="?", default=Path("out"),
                   help="output directory (default: out/)")
    # basic-pitch knobs
    p.add_argument("--onset-threshold", type=float, default=0.5,
                   help="note-onset sensitivity 0-1 (higher = fewer notes)")
    p.add_argument("--frame-threshold", type=float, default=0.3,
                   help="note-activation sensitivity 0-1 (higher = fewer notes)")
    p.add_argument("--min-note-ms", type=float, default=127.70,
                   help="minimum note length in ms for the full transcription")
    p.add_argument("--min-freq", type=float, default=None, help="ignore content below N Hz")
    p.add_argument("--max-freq", type=float, default=None, help="ignore content above N Hz")
    # melody-extraction knobs
    p.add_argument("--melody-min", type=int, default=55, metavar="MIDI",
                   help="lowest MIDI pitch kept in the melody line (default 55 = G3)")
    p.add_argument("--melody-max", type=int, default=84, metavar="MIDI",
                   help="highest MIDI pitch kept in the melody line (default 84 = C6)")
    p.add_argument("--melody-min-ms", type=float, default=120.0,
                   help="drop melody notes shorter than this (ms)")
    return p.parse_args(argv[1:])


def main(argv) -> int:
    args = parse_args(argv)
    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 1
    print(f">> transcribing {args.input.name} (basic-pitch / ONNX) …")
    info = transcribe(
        args.input, args.outdir,
        onset_threshold=args.onset_threshold,
        frame_threshold=args.frame_threshold,
        min_note_ms=args.min_note_ms,
        min_freq=args.min_freq,
        max_freq=args.max_freq,
        melody_min=args.melody_min,
        melody_max=args.melody_max,
        melody_min_ms=args.melody_min_ms,
    )
    print(f"   full transcription : {info['full_notes']} notes")
    print(f"   melody line        : {info['melody_notes']} notes"
          + (f"  range {info['range'][0]}–{info['range'][1]}" if info["range"] else ""))
    for path in info["files"].values():
        print(f"   wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
