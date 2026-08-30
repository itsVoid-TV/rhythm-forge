#!/bin/bash
set -euo pipefail

rhythm_forge_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$rhythm_forge_root/app/rhythm-forge" "$@"
