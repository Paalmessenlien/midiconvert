#!/usr/bin/env python3
"""Convert an Audiveris MusicXML export (.mxl/.xml/.musicxml) into a MIDI file.

Pipeline position:  PDF --[Audiveris]--> MusicXML --[THIS SCRIPT, music21]--> MIDI

The MusicXML produced by Audiveris is the "correction surface": if the OMR
misreads a dense chord, fix the .mxl and re-run this script -- conversion is cheap.

Usage:
    python convert.py INPUT.mxl [OUTPUT.mid] [options]

Options:
    --voice-program N   GM program (0-127) for the sung Voice part   (default 53, "Voice Oohs")
    --piano-program N   GM program (0-127) for the Piano part(s)     (default 0,  "Acoustic Grand")
    --no-tempo-fix      Disable the compound-meter tempo correction (see below)
    --eighth-bpm N      Force the eighth-note tempo to N (overrides what's in the score)
    --repair-rh         Repair dropped eighth-rests in the compound-meter piano right
                        hand (see fix_rh_rests.py)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from music21 import converter, tempo, meter, instrument, note

import fix_rh_rests


# This score is "His Eye Is On The Sparrow": 6/8, dotted-quarter feel, eighth = 105.
# If Audiveris fails to recover the tempo/meter from the engraving we inject these
# so the MIDI plays back at the intended speed instead of music21's 120 bpm default.
FALLBACK_TEMPO_EIGHTH_BPM = 105
FALLBACK_TIME_SIGNATURE = "6/8"


def ensure_tempo_and_meter(score, fallback_eighth_bpm: float) -> None:
    """Guarantee the score carries a tempo and time signature.

    Audiveris usually recovers '6/8' and the '= 105' marking, but OMR can drop
    them. We only add fallbacks when they're genuinely missing, so a correctly
    recognised score is never overridden.
    """
    if not score.recurse().getElementsByClass(meter.TimeSignature):
        score.parts[0].insert(0, meter.TimeSignature(FALLBACK_TIME_SIGNATURE))

    if not score.recurse().getElementsByClass(tempo.MetronomeMark):
        # referent = eighth note, because the marking is ♪ = 105 (not quarter = 105).
        mark = tempo.MetronomeMark(
            number=fallback_eighth_bpm,
            referent=note.Note(type="eighth"),
        )
        score.parts[0].insert(0, mark)


def correct_compound_tempo(score) -> None:
    """Fix Audiveris' compound-meter tempo misread.

    In a compound meter (x/8), tempo is marked against the eighth note: "♪ = 105".
    Audiveris frequently OCRs the eighth-note beat unit as a *quarter* note, so it
    exports `quarter = 105`, which plays the piece at DOUBLE the intended speed.

    Heuristic: if the meter denominator is 8 (compound feel) and a metronome mark
    is referenced to a quarter note, reinterpret the printed number as eighth = N
    (i.e. halve the quarter-BPM). This leaves correctly-read marks untouched.

    NOTE: this is opt-out (--no-tempo-fix) because a score genuinely marked
    "quarter = N" in a /8 meter would be wrongly halved.
    """
    ts_list = score.recurse().getElementsByClass(meter.TimeSignature)
    if not ts_list or ts_list[0].denominator != 8:
        return

    for mm in score.recurse().getElementsByClass(tempo.MetronomeMark):
        # referent.quarterLength == 1.0 means the mark is "quarter = N".
        if mm.referent is not None and mm.referent.quarterLength == 1.0 and mm.number:
            printed = mm.number
            mm.referent = note.Note(type="eighth").duration
            mm.number = printed  # now interpreted as eighth = printed
            print(
                f"  corrected compound-meter tempo: quarter={printed} "
                f"-> eighth={printed} (quarterBPM {printed} -> {mm.getQuarterBPM():.1f})"
            )


def force_eighth_tempo(score, eighth_bpm: float) -> None:
    """Replace every metronome mark with an explicit eighth = N marking."""
    for mm in list(score.recurse().getElementsByClass(tempo.MetronomeMark)):
        mm.activeSite.remove(mm)
    score.parts[0].insert(
        0, tempo.MetronomeMark(number=eighth_bpm, referent=note.Note(type="eighth"))
    )
    print(f"  forced tempo: eighth = {eighth_bpm} (quarterBPM {eighth_bpm / 2:.1f})")


def assign_instruments(score, voice_program: int, piano_program: int) -> None:
    """Give each part a distinct General-MIDI voice so the tracks are separable.

    Audiveris emits this score as two parts -- the sung "Voice" line and the
    "Piano" grand staff. We match by part name: anything that looks vocal gets
    the melody patch, everything else gets the piano patch.

    The patch numbers are GM program numbers (0-127), exposed as CLI flags so you
    can, e.g., put the melody on a pad/strings patch to make it stand out against
    the busy piano, without touching this code.
    """
    for part in score.parts:
        name = (part.partName or "").lower()
        program = voice_program if ("voice" in name or "vocal" in name) else piano_program
        # Drop any instrument Audiveris/music21 already attached, else its
        # program_change lingers and fights ours in the exported MIDI.
        for old in list(part.recurse().getElementsByClass(instrument.Instrument)):
            old.activeSite.remove(old)
        part.insert(0, instrument.instrumentFromMidiProgram(program))


def convert(
    input_path: Path,
    output_path: Path,
    *,
    voice_program: int = 53,
    piano_program: int = 0,
    tempo_fix: bool = True,
    eighth_bpm: float | None = None,
    repair_rh: bool = False,
) -> Path:
    score = converter.parse(str(input_path))

    if repair_rh:
        n = fix_rh_rests.repair(score)
        print(f"  repaired {n} right-hand measure(s) (eighth-rests)")

    ensure_tempo_and_meter(score, FALLBACK_TEMPO_EIGHTH_BPM)

    if eighth_bpm is not None:
        force_eighth_tempo(score, eighth_bpm)
    elif tempo_fix:
        correct_compound_tempo(score)

    assign_instruments(score, voice_program, piano_program)
    score.write("midi", fp=str(output_path))
    return output_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MusicXML -> MIDI converter (music21).")
    p.add_argument("input", type=Path, help="input .mxl/.xml/.musicxml")
    p.add_argument("output", type=Path, nargs="?", help="output .mid (default: input with .mid)")
    p.add_argument("--voice-program", type=int, default=53, metavar="N",
                   help="GM program for the Voice part (default 53)")
    p.add_argument("--piano-program", type=int, default=0, metavar="N",
                   help="GM program for the Piano part(s) (default 0)")
    p.add_argument("--no-tempo-fix", dest="tempo_fix", action="store_false",
                   help="disable the compound-meter eighth/quarter tempo correction")
    p.add_argument("--eighth-bpm", type=float, default=None, metavar="N",
                   help="force eighth-note tempo to N (overrides the score's tempo)")
    p.add_argument("--repair-rh", dest="repair_rh", action="store_true",
                   help="repair dropped eighth-rests in the compound-meter piano right hand")
    return p.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 1
    output_path = args.output or args.input.with_suffix(".mid")
    convert(
        args.input,
        output_path,
        voice_program=args.voice_program,
        piano_program=args.piano_program,
        tempo_fix=args.tempo_fix,
        eighth_bpm=args.eighth_bpm,
        repair_rh=args.repair_rh,
    )
    print(f"wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
