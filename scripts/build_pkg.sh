#!/usr/bin/env bash
# Build downloadable mobile packages with EAS, supplying the Firebase API key
# from the root .env through EAS environment variables (never printed).
# See mobile/BUILDING.md, "Keeping the Firebase API key out of eas.json".
#
# Usage: scripts/build_pkg.sh [android|ios|all|store|ios-simulator] [--skip-key-sync]
#   android        APK for Android (default)
#   ios            Signed IPA for registered iPhones/iPads
#   all            Android and iOS preview builds
#   store          Android AAB and iOS IPA for store submission
#   ios-simulator  iOS Simulator archive
#   --skip-key-sync  Do not update the key in EAS (it is already set)
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
key_name="EXPO_PUBLIC_FIREBASE_API_KEY"
environments=(preview production)

usage() { sed -n '6,12s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"; }
die() { echo "error: $*" >&2; exit 1; }

target="android"
sync_key=true
for arg in "$@"; do
  case "$arg" in
    --skip-key-sync) sync_key=false ;;
    -h | --help) usage; exit 0 ;;
    -*) usage >&2; die "unknown option: $arg" ;;
    *) target="$arg" ;;
  esac
done
case "$target" in
  android | ios | all | store) npm_script="build:$target" ;;
  ios-simulator) npm_script="build:ios:simulator" ;;
  *) usage >&2; die "unknown target: $target" ;;
esac

# shellcheck source=frontend-env.sh
source "$root/scripts/frontend-env.sh"
eas() { npx --yes eas-cli@latest "$@"; }
cd "$root/mobile"

echo "==> Checking EAS sign-in"
if ! eas whoami >/dev/null 2>&1; then
  eas login
fi

if $sync_key; then
  # Step 1: copy the key from .env into EAS without echoing it.
  env_file="$root/.env"
  [[ -f "$env_file" ]] || die "$env_file not found"
  key="$(grep -m1 "^${key_name}=" "$env_file" | cut -d= -f2- | tr -d '\r' || true)"
  key="${key%\"}"; key="${key#\"}"; key="${key%\'}"; key="${key#\'}"
  [[ -n "$key" ]] || die "$key_name is missing or empty in $env_file"

  for environment in "${environments[@]}"; do
    echo "==> Setting $key_name in EAS environment '$environment' (sensitive)"
    eas env:set --name "$key_name" --value "$key" \
      --environment "$environment" --visibility sensitive \
      --non-interactive >/dev/null
    # Step 2: confirm it exists.
    eas env:list --environment "$environment" 2>/dev/null | grep -q "$key_name" ||
      die "$key_name not found in EAS environment '$environment' after setting it"
  done
  unset key
else
  echo "==> Skipping key sync"
fi

# Step 3 is manual: this script never edits eas.json.
if grep -q "\"$key_name\"" eas.json; then
  echo "warning: eas.json still contains $key_name. Remove that line from the" >&2
  echo "         preview profile's env block so EAS is the only source (step 3" >&2
  echo "         in mobile/BUILDING.md)." >&2
fi

# Step 4: build.
echo "==> Running npm run $npm_script"
npm run "$npm_script"
echo "==> Done. Install the build and check that sign-in works."
