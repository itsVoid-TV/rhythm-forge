#!/bin/bash
set -euo pipefail

rhythm_forge_source="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
plugins_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins"
plugin_id="io.github.itsvoid-tv.rhythm-forge"
target="$plugins_dir/$plugin_id"
legacy_target="$plugins_dir/local.rhythm-forge"
backup_dir="${XDG_STATE_HOME:-$HOME/.local/state}/rhythm-forge/plugin-backups"

for command_name in omarchy jq; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
done

if ! "$rhythm_forge_source/app/check-dependencies"; then
  exit 1
fi

mkdir -p "$plugins_dir"
stage="$(mktemp -d "$plugins_dir/.rhythm-forge-install.XXXXXX")"
cleanup() {
  if [[ -d "$stage" ]]; then
    find "$stage" -depth -type f -delete
    find "$stage" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT

cp -a \
  "$rhythm_forge_source/manifest.json" \
  "$rhythm_forge_source/BarWidget.qml" \
  "$rhythm_forge_source/app" \
  "$rhythm_forge_source/LICENSE" \
  "$rhythm_forge_source/README.md" \
  "$stage/"

omarchy plugin validate "$stage"

if [[ -e "$target" ]]; then
  mkdir -p "$backup_dir"
  backup="$backup_dir/$plugin_id.$(date +%Y%m%d-%H%M%S)"
  mv "$target" "$backup"
  echo "Previous installation moved to: $backup"
fi
if [[ -e "$legacy_target" ]]; then
  omarchy plugin disable local.rhythm-forge || true
  mkdir -p "$backup_dir"
  legacy_backup="$backup_dir/local.rhythm-forge.migrated.$(date +%Y%m%d-%H%M%S)"
  mv "$legacy_target" "$legacy_backup"
  echo "Legacy installation moved to: $legacy_backup"
fi
mv "$stage" "$target"
trap - EXIT

omarchy-shell shell rescanPlugins >/dev/null
omarchy plugin enable "$plugin_id" --section right
echo "Rhythm Forge installed and enabled. Click the music-note icon in the Omarchy bar."
