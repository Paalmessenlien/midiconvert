#!/usr/bin/env bash
# setup.sh -- install the midiconvert toolchain locally (no sudo, no system changes).
#
# Linux (x86_64): fully automated -- downloads & extracts Audiveris, OCR data,
#                 and creates the Python venv.
# macOS:          installs the Python venv + OCR data, then prints the manual
#                 Audiveris .dmg step (see README "Install on macOS").
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

AUDIVERIS_VERSION="5.10.2"
TESSDATA_URL="https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata"

mkdir -p tools/tessdata

# 1. Python virtual environment -------------------------------------------------
if [[ ! -x .venv/bin/python ]]; then
  echo ">> creating Python venv + installing music21, mido"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

# 2. OCR language data (Tesseract eng) ------------------------------------------
if [[ ! -f tools/tessdata/eng.traineddata ]]; then
  echo ">> downloading Tesseract eng.traineddata"
  curl -fL -o tools/tessdata/eng.traineddata "$TESSDATA_URL"
fi

# 3. Audiveris OMR engine -------------------------------------------------------
AUD="tools/audiveris-root/opt/audiveris/bin/Audiveris"
if [[ -x "$AUD" ]]; then
  echo ">> Audiveris already present"
elif [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]]; then
  DEB_URL="https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu24.04-x86_64.deb"
  echo ">> downloading Audiveris ${AUDIVERIS_VERSION} (.deb) and extracting locally (no sudo)"
  curl -fL -o /tmp/audiveris.deb "$DEB_URL"
  dpkg-deb -x /tmp/audiveris.deb tools/audiveris-root
else
  cat <<'EOF'
>> Audiveris not auto-installed on this platform.
   macOS: download the .dmg from
     https://github.com/Audiveris/audiveris/releases
   (arm64 for Apple Silicon, x86_64 for Intel), drag Audiveris to /Applications,
   then run:  xattr -dr com.apple.quarantine /Applications/Audiveris.app
   pdf2midi.sh will find it at /Applications/Audiveris.app/Contents/MacOS/Audiveris.
EOF
fi

echo ">> setup complete. Try:  ./pdf2midi.sh your-score.pdf"
