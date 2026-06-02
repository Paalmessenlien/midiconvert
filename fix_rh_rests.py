#!/usr/bin/env python3
"""Repair dropped eighth-rests in a compound-meter piano right hand.

Audiveris often misreads the common accompaniment texture

    upper voice:   eighth-rest  +  two beamed eighths   (the "breath then run" figure)
    lower voice:   a sustained dotted-quarter chord

by merging the two voices into one and dropping the eighth-rests. The result is a
single line like  [chord(1.5), 8th, 8th, chord(1.5)]  that OVERFLOWS the bar
(4.0 ql in a 6/8 = 3.0 bar) and has no rests.

This script rebuilds each such measure into the correct two-voice layout:
  * lower voice (stems down): the recognised dotted-quarter chords, one per beat;
  * upper voice (stems up):   for each beat, an eighth-rest followed by the eighths
    the OMR captured for that beat (beats with no captured eighths become rests).

It does NOT invent pitches: notes Audiveris never recognised stay absent (now shown
as rests with correct timing). It only touches measures that match the broken
pattern (compound meter, bar overflow, both a dotted chord and a loose eighth), so
correctly-read measures are left untouched.

Usage:
    python fix_rh_rests.py INPUT.mxl [OUTPUT.mxl]
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from music21 import chord, converter, meter, note, stream

EIGHTH = 0.5
DOTTED_QUARTER = 1.5


def _is_dotted_chordish(el) -> bool:
    return isinstance(el, (note.Note, chord.Chord)) and abs(float(el.quarterLength) - DOTTED_QUARTER) < 1e-6


def _is_eighth_note(el) -> bool:
    return isinstance(el, (note.Note, chord.Chord)) and abs(float(el.quarterLength) - EIGHTH) < 1e-6


def _compound_beat_count(ts: meter.TimeSignature | None, bar_ql: float) -> int | None:
    """Number of dotted-quarter beats if this is a compound (x/8) bar, else None."""
    if ts is not None:
        if ts.denominator == 8 and ts.numerator % 3 == 0:
            return ts.numerator // 3
        return None
    # Fall back to bar length: a 3.0/4.5/... ql bar divides into dotted quarters.
    beats = bar_ql / DOTTED_QUARTER
    return int(round(beats)) if abs(beats - round(beats)) < 1e-6 else None


def _needs_repair(measure, n_beats: int) -> bool:
    els = list(measure.notesAndRests)
    total = sum(float(e.quarterLength) for e in els)
    has_chord = any(_is_dotted_chordish(e) for e in els)
    has_eighth = any(_is_eighth_note(e) for e in els)
    return total > n_beats * DOTTED_QUARTER + 1e-6 and has_chord and has_eighth


def _rebuild_measure(measure, n_beats: int) -> None:
    els = list(measure.notesAndRests)
    chords = [e for e in els if _is_dotted_chordish(e)]
    eighths = [e for e in els if _is_eighth_note(e)]

    # Remove the merged notes/rests; keep clefs, key/time signatures, etc.
    for el in els:
        measure.remove(el, recurse=True)
    for v in list(measure.getElementsByClass(stream.Voice)):
        measure.remove(v)

    upper = stream.Voice(id="1")  # the "rest + eighths" figure
    lower = stream.Voice(id="2")  # the sustained chords

    ei = 0
    for b in range(n_beats):
        base = b * DOTTED_QUARTER

        # Lower voice: one dotted-quarter chord per beat (or a rest if none read).
        if b < len(chords):
            c = copy.deepcopy(chords[b])
            c.stemDirection = "down"
            lower.insert(base, c)
        else:
            lower.insert(base, note.Rest(quarterLength=DOTTED_QUARTER))

        # Upper voice: eighth-rest, then up to two captured eighths, else rests.
        upper.insert(base, note.Rest(quarterLength=EIGHTH))
        for slot in (1, 2):
            off = base + slot * EIGHTH
            if ei < len(eighths):
                n = copy.deepcopy(eighths[ei]); ei += 1
                n.stemDirection = "up"
                upper.insert(off, n)
            else:
                upper.insert(off, note.Rest(quarterLength=EIGHTH))

    measure.insert(0, upper)
    measure.insert(0, lower)


def repair(score) -> int:
    """Repair eligible measures in place. Returns the number of measures changed."""
    changed = 0
    for part in score.parts:
        ts = None
        for m in part.getElementsByClass(stream.Measure):
            found_ts = m.getElementsByClass(meter.TimeSignature)
            if found_ts:
                ts = found_ts[0]
            n_beats = _compound_beat_count(ts, float(m.barDuration.quarterLength))
            if n_beats is None:
                continue
            if _needs_repair(m, n_beats):
                _rebuild_measure(m, n_beats)
                changed += 1
    return changed


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1])
    if not src.exists():
        print(f"error: input not found: {src}", file=sys.stderr)
        return 1
    out = Path(argv[2]) if len(argv) > 2 else src.with_suffix(".fixed.mxl")

    score = converter.parse(str(src))
    n = repair(score)
    score.write("musicxml", fp=str(out))
    print(f"repaired {n} measure(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
