#!/usr/bin/env bash
# Update the authorized ARM64 checkout and run its existing release wrapper.
set -euo pipefail
umask 077

die() { printf 'update-build-arm64: %s\n' "$*" >&2; exit 1; }
usage() {
  printf '%s\n' \
    'Usage: bash update-build-arm64.sh [--repo-dir DIR] [--game DIR]' \
    '                                    [--jobs N] [--version VERSION]' \
    '' \
    'Update https://github.com/pablovesnine/MHGURecomp.git, branch master only.' \
    "Default checkout: \$HOME/MHGURecomp-arm64-test" \
    'Default dump: /home/vesnine/Descargas/MHGU dump/' \
    'Default jobs: 2; default build label: UTC YYYYMMDD.HHMMSS.' \
    'VERSION must be numeric, with optional dot-separated numeric components.' \
    'Requires the wrapper-supported x86-64 Linux host and accessible local Docker.' \
    'No packages are installed; private caches, logs and prior outputs are kept.' \
    'The dump stays local. No game data or built package is uploaded.' \
    '--help, -h  Show this help.'
}

origin='https://github.com/pablovesnine/MHGURecomp.git'
repo="${HOME:?HOME must be set}/MHGURecomp-arm64-test"
game='/home/vesnine/Descargas/MHGU dump/'
jobs=2
version=''
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --repo-dir|--game|--jobs|--version)
      (($# >= 2)) || die "missing value for $1"
      [[ -n $2 && $2 != --* ]] || die "missing value for $1"
      case "$1" in
        --repo-dir) repo=$2 ;;
        --game) game=$2 ;;
        --jobs) jobs=$2 ;;
        --version) version=$2 ;;
      esac
      shift 2 ;;
    *) die "unknown option: $1 (use --help)" ;;
  esac
done
[[ $jobs =~ ^[1-9][0-9]*$ ]] || die "jobs must be a positive integer"
[[ -z $version || $version =~ ^[0-9]+(\.[0-9]+)*$ ]] \
  || die "use a numeric build version"
for requirement in git bash docker flock tar realpath sha256sum date tee uname mkdir mktemp; do
  command -v "$requirement" >/dev/null \
    || die "missing required command: $requirement (nothing was installed)"
done
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] \
  || die "the release wrapper requires an x86-64 Linux host"
[[ ${CONTAINER_ENGINE:-docker} == docker ]] || die "only Docker is supported"
[[ -n $version ]] || version=$(date -u +%Y%m%d.%H%M%S)
game=$(realpath -e -- "$game") || die "dump folder does not exist"
[[ -d $game && -r $game/exefs/main && -r $game/exefs/sdk && -d $game/romfs ]] \
  || die "dump must contain readable exefs/main, exefs/sdk and a romfs directory"
[[ $game != *:* && $game != *$'\n'* ]] \
  || die "dump path contains unsupported characters"
repo=$(realpath -m -- "$repo") || die "cannot resolve checkout path"
[[ $repo != / && $repo != *:* && $repo != *$'\n'* ]] \
  || die "checkout path contains unsupported characters"
script_file=$(realpath -e -- "${BASH_SOURCE[0]}") || die "cannot locate this script"
starting_digest=$(sha256sum < "$script_file")
starting_digest=${starting_digest%% *}

# Mirror the wrapper's endpoint policy. Never switch contexts, elevate, or try
# a TCP daemon; a successful info request checks this user's actual access.
endpoint=''
if [[ -n ${DOCKER_CONTEXT:-} ]]; then
  endpoint=$(docker context inspect "$DOCKER_CONTEXT" \
    --format '{{.Endpoints.docker.Host}}') || die "cannot inspect Docker context"
elif [[ -n ${DOCKER_HOST:-} ]]; then
  endpoint=$DOCKER_HOST
fi
if [[ -z $endpoint ]]; then
  endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}') \
    || die "cannot inspect Docker context"
fi
[[ $endpoint == unix://* ]] || die "select a local Docker Unix socket"
docker --host "$endpoint" info --format '{{json .SecurityOptions}}' >/dev/null \
  || die "cannot connect to Docker as the current user; check the local socket"

# A persistent sibling lock also covers the first clone. Never delete this
# file: unlinking locks allows two processes to lock different inodes.
mkdir -p -- "${repo%/*}" || die "cannot create checkout parent"
lock_file="$repo.update-build-arm64.lock"
reentry=${MHGU_UPDATE_REEXEC_SHA:-}
if [[ -n $reentry ]]; then
  [[ $reentry =~ ^[0-9a-f]{40}$ &&
     ${MHGU_UPDATE_LOCK_FILE:-} == "$lock_file" &&
     -e /proc/$$/fd/8 && /proc/$$/fd/8 -ef "$lock_file" ]] \
    || die "invalid self-update re-entry; run the command again normally"
else
  exec 8>>"$lock_file" || die "cannot open update/build lock"
fi
# FD 8 survives exec; the wrapper uses FD 9 for its separate build lock.
flock -n 8 || die "another update/build is active for $repo"

if [[ ! -e $repo && ! -L $repo ]]; then
  [[ -z $reentry ]] || die "checkout disappeared during self-update"
  git clone --branch master --single-branch --origin origin "$origin" "$repo" \
    || die "clone failed; any partial checkout was left untouched"
else
  [[ -d $repo ]] || die "checkout path is occupied by a non-directory"
  [[ -e $repo/.git ]] || die "checkout path is occupied, not a repository root"
fi
root=$(git -C "$repo" rev-parse --show-toplevel) || die "not a Git checkout"
[[ $root == "$repo" ]] || die "checkout path must be the repository root"
cd "$repo"
# Read the stored URL, not `remote get-url`: that command expands insteadOf.
# Only Git's explicit per-user configuration may rewrite the fixed URL (the
# offline tests use this); this script never adds or changes a remote.
stored_origin=$(git config --get-all remote.origin.url) || die "origin is missing"
[[ $stored_origin == "$origin" || $stored_origin == "${origin%.git}" ]] \
  || die "origin must be exactly $origin"
branch=$(git symbolic-ref --quiet --short HEAD) || die "detached HEAD; select master"
[[ $branch == master ]] || die "checkout must be on branch master"
[[ -z $(git ls-files -u) ]] || die "resolve the unmerged files first"
git diff --quiet --ignore-submodules=none HEAD -- \
  || die "tracked changes or staged changes exist; commit or restore them first"

if [[ -z $reentry ]]; then
  git fetch --no-tags origin refs/heads/master:refs/remotes/origin/master \
    || die "cannot fetch origin/master; checkout was not reset"
  git merge-base --is-ancestor HEAD refs/remotes/origin/master \
    || die "unpublished local commits or divergent history; refusing to update"
  git merge --ff-only --no-edit refs/remotes/origin/master \
    || die "fast-forward failed; private files were not cleaned"
else
  [[ $(git rev-parse HEAD) == "$reentry" ]] \
    || die "checkout revision changed during self-update"
  [[ $(git rev-parse refs/remotes/origin/master) == "$reentry" ]] \
    || die "origin/master changed during self-update"
  # This exact fetched SHA has already passed the ancestry check. Do not fetch
  # again on re-entry: that would permit an unbounded sequence of self-updates.
fi
revision=$(git rev-parse HEAD)
updated_script="$repo/update-build-arm64.sh"
git cat-file -e HEAD:update-build-arm64.sh \
  || die "updated checkout does not contain the tracked update script"
updated_digest=$(sha256sum < "$updated_script")
updated_digest=${updated_digest%% *}
if [[ $starting_digest != "$updated_digest" ]]; then
  [[ -z $reentry ]] || die "self-update changed again; refusing a re-entry loop"
  printf 'update-build-arm64: Re-executing updated script at %s\n' "$revision"
  export MHGU_UPDATE_REEXEC_SHA=$revision MHGU_UPDATE_LOCK_FILE=$lock_file
  exec bash "$updated_script" --repo-dir "$repo" --game "$game" \
    --version "$version" --jobs "$jobs"
fi
git cat-file -e HEAD:tools/build-linux-release.sh \
  || die "the tracked release wrapper is missing"
log_dir="$repo/.linux-release/update-logs"
mkdir -p -- "$log_dir"
log_file=$(mktemp "$log_dir/$version.XXXXXX.log") || die "cannot create build log"
printf 'update-build-arm64: sources %s\nupdate-build-arm64: log %s\n' \
  "$revision" "$log_file"
if bash tools/build-linux-release.sh --game "$game" --version "$version" \
    --jobs "$jobs" 2>&1 | tee "$log_file"; then
  :
else
  status=$?
  printf 'update-build-arm64: build failed; see %s\n' "$log_file" >&2
  exit "$status"
fi

# Never bless a previous build after a failed wrapper invocation. Validate both
# the manifest and this invocation's expected archive, not an unrelated file.
archive_name="LinuxARM64-MHGURecomp.$version.tar.gz"
archive="$repo/dist/$archive_name"
[[ -f $repo/dist/SHA256SUMS && -f $archive ]] \
  || die "successful build did not produce the expected archive and SHA256SUMS"
(cd "$repo/dist" && sha256sum --check --strict SHA256SUMS) \
  || die "output checksum verification failed"
expected_sum=$(cd "$repo/dist" && sha256sum -- "$archive_name")
manifest_has_archive=false
while IFS= read -r line || [[ -n $line ]]; do
  if [[ $line == "$expected_sum" || $line == "${expected_sum:0:64} *$archive_name" ]]; then
    manifest_has_archive=true
  fi
done < "$repo/dist/SHA256SUMS"
[[ $manifest_has_archive == true ]] || die "SHA256SUMS does not cover $archive_name"
printf 'update-build-arm64: Archive: %s\nupdate-build-arm64: Build log: %s\n' \
  "$archive" "$log_file"
