#!/bin/bash
set -euo pipefail

plugins_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins"
backup_dir="${XDG_STATE_HOME:-$HOME/.local/state}/rhythm-forge/plugin-backups"

found=false
for plugin_id in io.github.itsvoid-tv.rhythm-forge local.rhythm-forge; do
  target="$plugins_dir/$plugin_id"
  if [[ ! -e "$target" ]]; then
    continue
  fi
  found=true
  omarchy plugin disable "$plugin_id" || true
  mkdir -p "$backup_dir"
  archive="$backup_dir/$plugin_id.removed.$(date +%Y%m%d-%H%M%S)"
  mv "$target" "$archive"
  echo "Rhythm Forge was disabled and moved to: $archive"
done

if [[ "$found" == false ]]; then
  echo "Rhythm Forge is not installed."
  exit 0
fi

omarchy-shell shell rescanPlugins >/dev/null
echo "Downloaded videos remain in your XDG cache directory."
