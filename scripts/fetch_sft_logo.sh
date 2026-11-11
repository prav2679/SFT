#!/usr/bin/env bash
# Download the SFT logo from the official website (identified 2 Nov 2026 as the header image
# https://susanfuturetechnologies.com/wp-content/uploads/2024/03/3.png). Confirm with SFT that this is
# the current official asset; replace with an SVG/transparent PNG from SFT if provided.
set -euo pipefail
ROOT="$(dirname "$0")/.."
URL="https://susanfuturetechnologies.com/wp-content/uploads/2024/03/3.png"
for d in "$ROOT/frontend/public/assets/branding" "$ROOT/frontend/dist/assets/branding"; do
  mkdir -p "$d"; curl -fsSL "$URL" -o "$d/sft-logo.png" && echo "Saved $d/sft-logo.png"
done
