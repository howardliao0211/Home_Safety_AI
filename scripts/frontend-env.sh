#!/usr/bin/env bash
# Source this file from any directory: source scripts/frontend-env.sh
_frontend_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$_frontend_root/.tools/node-v24.22.1-linux-x64/bin/node" ]]; then
  export PATH="$_frontend_root/.tools/node-v24.22.1-linux-x64/bin:$PATH"
fi
export npm_config_cache="$_frontend_root/.tools/npm-cache"
unset _frontend_root
