#!/bin/bash
set -euo pipefail

rhythm_forge_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
dist_dir="$rhythm_forge_root/dist"
version="$(jq -r .version "$rhythm_forge_root/manifest.json")"
archive="$dist_dir/rhythm-forge-$version.tar.gz"

mkdir -p "$dist_dir"
python3 -m unittest discover -s "$rhythm_forge_root/tests" -v
omarchy plugin validate "$rhythm_forge_root"
python3 -m py_compile "$rhythm_forge_root/app/engine.py" "$rhythm_forge_root/app/progression.py" "$rhythm_forge_root/app/rhythm_forge.py"

tar \
  --exclude='./.git' \
  --exclude='./dist' \
  --exclude='./tests' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  -czf "$archive" \
  -C "$rhythm_forge_root" .
sha256sum "$archive" > "$archive.sha256"
echo "$archive"
