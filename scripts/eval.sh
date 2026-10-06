#!/usr/bin/env bash
# Run presidio-agent on a folder of PDFs in three sets, each in its own output folder:
#   real     the PDFs whose pages are scans
#   sim      the digital PDFs turned into scan-like images (scripts/simulate_scan.py)
#   digital  the digital PDFs as they are (text layer positions)
#
#   scripts/eval.sh FIXTURE_DIR [OUT_DIR] [PRIVATE_DIR]      N=copies per document (default 1)
#
# Each set gets OUT_DIR/SET/index.html. Analysis and mappings go to PRIVATE_DIR/SET
# (default: OUT_DIR.private, beside OUT_DIR so serving OUT_DIR never serves them).
# The summary of every run is appended to OUT_DIR/summary.txt.
set -u
fixtures=${1:?usage: scripts/eval.sh FIXTURE_DIR [OUT_DIR]}
out=${2:-/dev/shm/presidio-agent/eval}
private=${3:-$out.private}
n=${N:-1}
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$out/sim-input"

run() {  # SET PDF
  echo "== $1 $(basename "$2")" | tee -a "$out/summary.txt"
  presidio-agent copy "$2" --n "$n" --out "$out/$1" --private "$private/$1" 2>&1 \
    | grep --line-buffered -E "^page|^copy|Error" | tee -a "$out/summary.txt"
  python -m presidio_agent.page "$out/$1" > /dev/null
}

mapfile -t pdfs < <(find "$fixtures" -name '*.pdf' | sort)
for pdf in "${pdfs[@]}"; do
  if [ "$(pdftotext "$pdf" - 2>/dev/null | wc -w)" -eq 0 ]; then
    run real "$pdf"
  fi
done
for pdf in "${pdfs[@]}"; do
  words=$(pdftotext "$pdf" - 2>/dev/null | wc -w)
  pages=$(pdfinfo "$pdf" | awk '/^Pages/ {print $2}')
  if [ "$words" -gt 0 ] && [ "$pages" -le 3 ]; then  # skip compilations of other files
    python "$here/simulate_scan.py" "$pdf" "$out/sim-input" > /dev/null
    run sim "$out/sim-input/$(basename "$pdf")"
    run digital "$pdf"
  fi
done
echo "== done" | tee -a "$out/summary.txt"
