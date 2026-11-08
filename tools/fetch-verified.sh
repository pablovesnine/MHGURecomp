#!/usr/bin/env bash
# Bounded source retrieval. Only transport failures may use an explicit mirror.
set -euo pipefail
die() { echo "fetch: $*" >&2; exit 1; }
(($# >= 3)) || die "expected OUTPUT SHA256 HTTPS_URL [HTTPS_MIRROR...]"
output=$1
digest=$2
shift 2
[[ $digest =~ ^[0-9a-f]{64}$ ]] || die "expected a pinned SHA-256"
for url in "$@"; do
  [[ $url == https://* ]] || die "source URLs must use HTTPS"
done
[[ ! -e $output && ! -L $output ]] || die "output already exists"
mkdir -p "$(dirname "$output")"
partial=$(mktemp "$output.part.XXXXXX")
trap 'rm -f -- "$partial"' EXIT
for url in "$@"; do
  headers=()
  asset_api='^https://api\.github\.com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/assets/[0-9]+$'
  if [[ $url =~ $asset_api ]]; then
    # The public asset API returns metadata unless binary content is requested.
    headers=(--header 'Accept: application/octet-stream')
  fi
  if curl --fail --location --silent --show-error \
      --proto '=https' --proto-redir '=https' \
      --connect-timeout 10 --max-time 120 --retry 1 --retry-all-errors \
      --retry-max-time 45 --speed-limit 1024 --speed-time 30 \
      "${headers[@]}" --output "$partial" "$url"; then
    printf '%s  %s\n' "$digest" "$partial" | sha256sum --check --status - \
      || die "source checksum mismatch, refusing all mirrors"
    mv -- "$partial" "$output"
    exit 0
  fi
  echo "fetch: source transport failed, trying the next explicit URL" >&2
done
die "all source URLs failed within the configured timeout/retry limits"
