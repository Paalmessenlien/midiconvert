# midiconvert

Convert engraved **sheet-music PDFs into MIDI files**.

It runs the PDF through an Optical Music Recognition (OMR) engine to recover the
notes, rhythm, key and tempo, then turns the recognised score into a multi-track
General-MIDI file you can play or import into any DAW / notation editor.

```
PDF ──[Audiveris OMR]──▶ MusicXML (.mxl) ──[convert.py / music21]──▶ MIDI (.mid)
```

- **Audiveris** does the hard part: reading staves, noteheads, beams, accidentals.
- **`convert.py`** (music21) turns the recognised MusicXML into MIDI, fixing a
  couple of common OMR quirks (tempo, instruments) along the way.
- The intermediate **`.mxl` is the correction surface** — if a dense chord is
  misread, fix it once in MuseScore and re-run the conversion; no need to re-OMR.

> Works best on **digitally engraved** scores (Sibelius/Finale/MuseScore PDFs).
> Scanned/photographed scores also work but produce more recognition errors.

---

## Requirements

- **Python 3.9+**
- **[Audiveris](https://github.com/Audiveris/audiveris) 5.10.x** — bundles its own
  Java runtime, so you do **not** need to install Java separately.
- Python packages: `music21`, `mido` (see `requirements.txt`).
- For playback only: a soundfont + a synth such as `fluidsynth`, or any DAW
  (MuseScore, GarageBand, …).

No `sudo` is required: `setup.sh` extracts Audiveris into a local `tools/` folder.

---

## Install

### Linux (x86_64) — automated

```bash
git clone https://github.com/Paalmessenlien/midiconvert.git
cd midiconvert
./setup.sh
```

`setup.sh` will:
1. create a Python venv in `.venv/` and install `music21` + `mido`;
2. download the Tesseract `eng.traineddata` OCR model into `tools/tessdata/`;
3. download the Audiveris `.deb` and **extract** it (no install) into
   `tools/audiveris-root/` (its bundled JRE makes it self-contained).

### macOS

`setup.sh` handles the Python venv and OCR data; install Audiveris manually:

1. Check your chip: `uname -m` → `arm64` (Apple Silicon) or `x86_64` (Intel).
2. Download the matching `.dmg` from the
   [Audiveris releases](https://github.com/Audiveris/audiveris/releases)
   (`…macosx-arm64.dmg` / `…macosx-x86_64.dmg`) and drag **Audiveris** to
   `/Applications`.
3. Clear the Gatekeeper quarantine flag once:
   ```bash
   xattr -dr com.apple.quarantine /Applications/Audiveris.app
   ```
4. Run `./setup.sh` for the venv + OCR data.

`pdf2midi.sh` auto-detects the launcher at
`/Applications/Audiveris.app/Contents/MacOS/Audiveris`.

### Manual / other platforms

Point the pipeline at any Audiveris launcher with the `AUDIVERIS` env var:

```bash
AUDIVERIS=/path/to/Audiveris ./pdf2midi.sh score.pdf
```

---

## Usage

### One command: PDF → MIDI

```bash
./pdf2midi.sh path/to/score.pdf
```

This runs OMR then conversion and writes everything to `out/`:

| File | What it is |
|------|------------|
| `out/<name>.omr` | Audiveris project file (re-openable for editing) |
| `out/<name>.mxl` | recognised score as compressed MusicXML — **the correction surface** |
| `out/<name>.mid` | the final MIDI |
| `out/<name>-<timestamp>.log` | Audiveris run log |

Environment overrides:

- `AUDIVERIS=/path/to/launcher` — use a specific Audiveris install.

### Just the MIDI step: MusicXML → MIDI

If you already have (or have hand-corrected) a `.mxl`/`.xml`/`.musicxml`:

```bash
.venv/bin/python convert.py INPUT.mxl [OUTPUT.mid] [options]
```

| Option | Default | Purpose |
|--------|---------|---------|
| `--voice-program N` | `53` | General-MIDI program (0–127) for the sung **Voice** part. `53` ≈ "Voice Oohs". |
| `--piano-program N` | `0` | GM program for the **Piano** part(s). `0` = Acoustic Grand. |
| `--no-tempo-fix` | _(on)_ | Disable the compound-meter tempo correction (see below). |
| `--eighth-bpm N` | — | Force the eighth-note tempo to `N`, overriding the score. |

Examples:

```bash
# defaults: voice on patch 53, piano on grand, auto tempo fix
.venv/bin/python convert.py out/score.mxl out/score.mid

# put the melody on strings (48) so it cuts through a busy piano
.venv/bin/python convert.py out/score.mxl out/score.mid --voice-program 48

# trust the score's tempo exactly, no compound-meter heuristic
.venv/bin/python convert.py out/score.mxl out/score.mid --no-tempo-fix
```

---

## How `convert.py` cleans up the OMR

OMR output is usually playable but imperfect. `convert.py` applies targeted fixes:

1. **Tempo / meter fallback** — if Audiveris dropped the time signature or
   metronome mark, a sensible default is inserted (`6/8`, eighth = 105) instead
   of music21's silent 120 bpm.

2. **Compound-meter tempo correction** — in `x/8` meters, tempo is marked against
   the **eighth note** (`♪ = N`). Audiveris frequently misreads that beat unit as
   a *quarter* note and exports `quarter = N`, which plays the piece at **double
   speed**. When the meter denominator is 8 and a metronome mark is referenced to
   a quarter, the converter reinterprets it as `eighth = N` (halving the BPM).
   This is **opt-out** via `--no-tempo-fix`, because a score genuinely marked
   `quarter = N` in a `/8` meter would otherwise be wrongly halved.

3. **Instrument assignment** — each part is given a clean GM program (matching
   "voice"/"vocal" in the part name → `--voice-program`, otherwise
   `--piano-program`), and any stale instrument from the OMR is removed so it
   doesn't emit conflicting `program_change` events.

---

## Correcting recognition errors

The biggest source of error is **dense chords / many accidentals** (jazz voicings,
ledger-line notes). To fix them:

1. Open `out/<name>.mxl` in **[MuseScore](https://musescore.org)** (free).
2. Correct the wrong notes / durations and save/export the MusicXML.
3. Re-run only the cheap step:
   ```bash
   .venv/bin/python convert.py out/<name>.mxl out/<name>.mid
   ```

You can also re-open `out/<name>.omr` directly in the Audiveris GUI to re-edit at
the recognition level.

---

## Playback

**Easiest:** double-click the `.mid` (opens in GarageBand / your default player),
or open it in MuseScore.

**With fluidsynth + a soundfont:**

```bash
# Linux (a GM soundfont is often already at /usr/share/sounds/sf2/FluidR3_GM.sf2)
fluidsynth -a pulseaudio /usr/share/sounds/sf2/FluidR3_GM.sf2 out/score.mid

# macOS
brew install fluid-synth
fluidsynth -a coreaudio /path/to/FluidR3_GM.sf2 out/score.mid

# render to an audio file instead of playing live
fluidsynth -ni -F out/score.wav /path/to/FluidR3_GM.sf2 out/score.mid
```

> `fluidsynth` needs the **soundfont as its first argument** — `fluidsynth out/score.mid`
> alone fails because it has no instrument bank to synthesise with.

---

## Project layout

```
midiconvert/
├── pdf2midi.sh        # PDF -> MIDI orchestrator (Audiveris + convert.py)
├── convert.py         # MusicXML -> MIDI (music21), with the OMR clean-ups
├── setup.sh           # local, no-sudo toolchain installer
├── requirements.txt   # music21, mido
├── tools/             # (created by setup.sh) Audiveris + OCR data — git-ignored
├── .venv/             # (created by setup.sh) Python env — git-ignored
└── out/               # (created at run time) .omr / .mxl / .mid — git-ignored
```

---

## Limitations

- OMR is not perfect — expect occasional wrong notes/durations on dense or
  low-quality scores; the `.mxl` is there to fix them.
- The automated `setup.sh` install path is **Linux x86_64**; other platforms need
  the Audiveris step done manually (see Install).
- `convert.py`'s tempo heuristic is tuned for compound (`x/8`) meters; for other
  meters it leaves the recognised tempo untouched.
