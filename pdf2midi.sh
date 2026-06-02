#!/usr/bin/env bash
# pdf2midi.sh -- convert an engraved sheet-music PDF to MIDI.
#
#   PDF --[Audiveris OMR]--> MusicXML (.mxl) --[convert.py / music21]--> MIDI (.mid)
#
# Usage:
#   ./pdf2midi.sh [INPUT.pdf]
# Defaults to the "His Eye Is On The Sparrow" score if no argument is given.
#
# Artifacts land in ./out/ :  <name>.omr (Audiveris project, the correction
# surface), <name>.mxl (recognised MusicXML), <name>.mid (final MIDI).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

DEFAULT_PDF="Sister+Act+-+His+Eye+Is+On+The+Sparrow+-+TwoPart+Vocal+-+Jules+Kain+Music.pdf"
PDF="${1:-$DEFAULT_PDF}"

if [[ ! -f "$PDF" ]]; then
  echo "error: PDF not found: $PDF" >&2
  exit 1
fi

OUT="$HERE/out"
VENV_PY="$HERE/.venv/bin/python"

# Locate the Audiveris launcher across platforms. Override with: AUDIVERIS=/path ./pdf2midi.sh
find_audiveris() {
  local c
  for c in \
    "${AUDIVERIS:-}" \
    "$HERE/tools/audiveris-root/opt/audiveris/bin/Audiveris" \
    "/Applications/Audiveris.app/Contents/MacOS/Audiveris" \
    "$HOME/Applications/Audiveris.app/Contents/MacOS/Audiveris" \
    "$(command -v audiveris 2>/dev/null || true)" \
    "$(command -v Audiveris 2>/dev/null || true)"
  do
    [[ -n "$c" && -x "$c" ]] && { echo "$c"; return 0; }
  done
  echo "error: Audiveris launcher not found. Install it, or set AUDIVERIS=/path/to/launcher" >&2
  return 1
}
AUD="$(find_audiveris)"

# Audiveris bundles its own JRE; OCR language data is the only external bit.
export TESSDATA_PREFIX="$HERE/tools/tessdata"
export JAVA_TOOL_OPTIONS="-Djava.awt.headless=true"

mkdir -p "$OUT"

echo ">> OMR (Audiveris): $PDF"
"$AUD" -batch -transcribe -export -output "$OUT" "$PDF"

# Audiveris names the .mxl after the PDF stem.
stem="$(basename "$PDF")"; stem="${stem%.*}"
MXL="$OUT/$stem.mxl"
if [[ ! -f "$MXL" ]]; then
  echo "error: expected MusicXML not produced: $MXL" >&2
  exit 2
fi

MID="$OUT/$stem.mid"
echo ">> MusicXML -> MIDI (music21)"
"$VENV_PY" "$HERE/convert.py" "$MXL" "$MID"

echo ">> done: $MID"
