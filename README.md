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

### macOS (Apple Silicon or Intel) — step by step

On macOS `setup.sh` sets up the Python venv and OCR data automatically; Audiveris
is installed once from its official `.dmg`. Full walkthrough:

**1. Prerequisites** — you need `git`, `python3`, and `curl`. The quickest way to
get `git`/`python3` is the Xcode Command Line Tools (or Homebrew):

```bash
xcode-select --install          # provides git + python3 (or: brew install git python)
python3 --version               # confirm Python 3.9+
```

**2. Get the project and run setup:**

```bash
git clone https://github.com/Paalmessenlien/midiconvert.git
cd midiconvert
./setup.sh                       # creates .venv/, installs deps, downloads OCR data
```

**3. Install Audiveris** (the OMR engine — it bundles its own Java, so you don't
install Java separately):

1. Check your chip: `uname -m` → `arm64` (Apple Silicon, M-series) or `x86_64` (Intel).
2. Download the matching `.dmg` from the
   [Audiveris releases](https://github.com/Audiveris/audiveris/releases)
   (`…macosx-arm64.dmg` for Apple Silicon, `…macosx-x86_64.dmg` for Intel), open it,
   and drag **Audiveris** into `/Applications`.
3. Clear the Gatekeeper quarantine flag once (the build isn't notarized):
   ```bash
   xattr -dr com.apple.quarantine /Applications/Audiveris.app
   ```

`pdf2midi.sh` and the web UI auto-detect the launcher at
`/Applications/Audiveris.app/Contents/MacOS/Audiveris` (no extra config). If you
put it elsewhere, point at it with `AUDIVERIS=/path/to/Audiveris`.

**4. Run it** — exactly the same commands as Linux:

```bash
# A) one-shot CLI: PDF -> MIDI (writes to out/)
./pdf2midi.sh "path/to/your-score.pdf"

# B) web UI: open http://127.0.0.1:5000 in your browser
.venv/bin/python app.py
```

**5. Play the result on macOS:**
- Easiest: double-click `out/<name>.mid` (opens in **GarageBand**), or open it in
  **MuseScore**.
- In the web UI it plays in-page (piano-roll + live note read-out); the first play
  downloads a soundfont, so it needs internet that once.
- Or with fluidsynth + CoreAudio:
  ```bash
  brew install fluid-synth
  fluidsynth -a coreaudio /path/to/FluidR3_GM.sf2 out/<name>.mid
  ```

> Tip: if you also have MuseScore installed, you already have a soundfont at
> `MuseScore_General.sf3` inside its app bundle that fluidsynth can use.

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
| `--repair-rh` | off | Repair dropped eighth-rests in the compound-meter piano right hand (see [`fix_rh_rests.py`](fix_rh_rests.py)). |

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

## Web UI

A small Flask app gives you a browser interface for **both directions**: drop a
**sheet-music PDF** *or* an **audio file** (MP3/WAV/FLAC/…), watch progress, then
play the result in-page (scrolling piano-roll + live note read-out) and download
the artifacts.

```bash
./setup.sh                            # installs flask (in requirements.txt)
.venv/bin/pip install --no-deps basic-pitch        # for audio input (optional)
.venv/bin/pip install -r requirements-audio.txt    #   "
.venv/bin/python app.py               # serves on http://127.0.0.1:5000
```

Open <http://127.0.0.1:5000> and drop a file:
- **PDF** → Audiveris OMR → MIDI. "Advanced options" exposes the `convert.py` knobs
  (voice/piano GM program, tempo-fix, **Repair right-hand eighth-rests**, forced
  eighth-note BPM). Downloads: MIDI + MusicXML.
- **Audio** → basic-pitch transcription. "Advanced options" exposes onset/frame
  sensitivity and the melody pitch range. The result has a **Melody / Full** toggle
  on the player; downloads: melody MIDI, full MIDI, and the notes CSV.

The app auto-detects the file type and routes accordingly (`pipeline.run_pipeline`
for PDF, `audio2midi.transcribe` for audio).

Notes:
- **Audio input is optional** — if `basic-pitch` isn't installed the PDF path still
  works; audio uploads just error until you install the audio extras.
- **Local single-user tool** — no auth or upload hardening. It binds to
  `127.0.0.1` by default; only change the host in `app.py` deliberately.
- In-browser playback uses the [`html-midi-player`](https://github.com/cifkao/html-midi-player)
  web component, which loads a soundfont from a CDN — the **first play needs
  internet**. (That CDN `<script>` is a jsdelivr `combine` bundle, which is why it
  carries no Subresource-Integrity hash; fine for a local tool, but pin/host it
  yourself if you deploy this.)
- OMR is the slow part (~1–2 min); audio transcription takes ~30 s. The page polls a
  job-status endpoint and shows a progress bar (Audiveris recognition steps for PDF,
  coarse stages for audio).

The web app is a thin layer over the same engines: `pipeline.py`/`convert.py` for
PDF and `audio2midi.py` for audio, so the CLI and UI behave identically.

---

## Audio → MIDI (experimental, the reverse direction)

`audio2midi.py` goes the *other* way — it transcribes a recording (MP3/WAV/FLAC…)
into MIDI + a notes list, using Spotify's [`basic-pitch`](https://github.com/spotify/basic-pitch)
(polyphonic) via its **ONNX** backend.

```bash
# install the audio extras into the same venv (basic-pitch needs --no-deps,
# see the file header for why)
.venv/bin/pip install --no-deps basic-pitch
.venv/bin/pip install -r requirements-audio.txt

.venv/bin/python audio2midi.py "song.mp3" out
```

It writes, from a single transcription pass:

| File | What it is |
|------|------------|
| `out/<name>.full.mid` | every note basic-pitch detects (dense on a full mix) |
| `out/<name>.melody.mid` | a cleaned, strictly **monophonic** lead line |
| `out/<name>.notes.csv` / `.txt` | the melody as `start,end,dur,midi,note` |

Useful flags: `--onset-threshold` / `--frame-threshold` (sensitivity), `--min-note-ms`,
`--min-freq`/`--max-freq`, and melody options `--melody-min`/`--melody-max` (pitch
range, MIDI numbers) and `--melody-min-ms`.

> **Accuracy caveat.** This is Automatic Music Transcription — ML pitch/onset
> estimation, not the deterministic note-reading of the PDF path. On a **full band
> mix** it over-detects (the example, a 4-min promo, yields ~2400 raw notes), and the
> melody line is a *best-effort* heuristic (most-salient note over time) — a real
> vocal melody isn't always the loudest/highest pitch. For faithful results, feed it
> cleaner/solo material, or separate stems first. The engraved-PDF path remains the
> high-fidelity route.

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
├── pdf2midi.sh        # PDF -> MIDI orchestrator, CLI (Audiveris + convert.py)
├── convert.py         # MusicXML -> MIDI (music21), with the OMR clean-ups
├── fix_rh_rests.py    # repair dropped eighth-rests in the piano right hand
├── pipeline.py        # shared engine: Audiveris invocation + convert, with progress
├── app.py             # Flask web UI server
├── templates/         # index.html (the web page)
├── static/            # app.js, style.css
├── audio2midi.py      # reverse direction: audio -> MIDI + notes (basic-pitch)
├── setup.sh           # local, no-sudo toolchain installer
├── requirements.txt   # music21, mido, flask
├── requirements-audio.txt  # basic-pitch / onnxruntime / librosa (audio2midi.py)
├── tools/             # (created by setup.sh) Audiveris + OCR data — git-ignored
├── .venv/             # (created by setup.sh) Python env — git-ignored
├── out/               # (CLI) .omr / .mxl / .mid — git-ignored
└── jobs/              # (web UI) per-upload working dirs — git-ignored
```

---

## Limitations

- OMR is not perfect — expect occasional wrong notes/durations on dense or
  low-quality scores; the `.mxl` is there to fix them.
- The automated `setup.sh` install path is **Linux x86_64**; other platforms need
  the Audiveris step done manually (see Install).
- `convert.py`'s tempo heuristic is tuned for compound (`x/8`) meters; for other
  meters it leaves the recognised tempo untouched.
