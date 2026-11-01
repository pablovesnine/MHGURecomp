#!/usr/bin/env bash
set -euo pipefail
umask 077

die() { echo "linux-release: $*" >&2; exit 1; }
usage() {
  cat <<'HELP'
Usage: bash tools/build-linux-release.sh --game DIR --version VERSION [--jobs N]
       bash tools/build-linux-release.sh --check --version 0 [--jobs N]

Build Linux ARM64 only, on a Linux x86_64 host with local Docker.
--check validates the public ARM64 runtime without game files.
By default use ghcr.io/pablovesnine/mhgurecomp-builder:<full HEAD>, or build
the tools locally from that exact tracked commit if the image is unavailable.
--image NAME overrides the image name; --skip-image-build requires it to exist.
--rebuild-image forces a local tools build (incompatible with --skip-image-build).
Tracked changes must be committed first. Untracked files are never exported.
HELP
}

game=''
version=''
jobs=2
mode=release
image=''
skip_build=false
rebuild=false
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --check) mode=check; shift ;;
    --skip-image-build) skip_build=true; shift ;;
    --rebuild-image) rebuild=true; shift ;;
    --game|--version|--jobs|--image)
      (($# >= 2)) || die "missing value for $1"
      [[ $2 != --* && -n $2 ]] || die "missing value for $1"
      case "$1" in
        --game) game=$2 ;;
        --version) version=$2 ;;
        --jobs) jobs=$2 ;;
        --image) image=$2 ;;
      esac
      shift 2 ;;
    *) die "unknown option: $1" ;;
  esac
done
[[ $version =~ ^[0-9]+(\.[0-9]+)*$ ]] || die "use a numeric release version"
[[ $jobs =~ ^[1-9][0-9]*$ ]] || die "jobs must be a positive integer"
[[ $skip_build != true || $rebuild != true ]] \
  || die "--skip-image-build and --rebuild-image are incompatible"
[[ -z $image || $image != -* ]] || die "invalid image name"
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] \
  || die "this builder requires an x86-64 Linux host"
[[ ${CONTAINER_ENGINE:-docker} == docker ]] || die "only Docker is supported"
if [[ $mode == check ]]; then
  [[ -z $game ]] || die "do not supply game files in check mode"
else
  [[ -n $game ]] || die "supply your dump with --game"
  game=$(realpath -e -- "$game") || die "dump folder does not exist"
  [[ -r $game/exefs/main && -r $game/exefs/sdk && -d $game/romfs ]] \
    || die "dump must contain exefs/main, exefs/sdk and romfs"
  [[ $game != *:* && $game != *$'\n'* ]] || die "dump path contains unsupported characters"
fi
root=$(git rev-parse --show-toplevel) || die "run from the repository"
cd "$root"
git diff --quiet HEAD -- || die "commit or restore tracked changes first"
[[ -z $(git ls-files -u) ]] || die "resolve the merge first"
git cat-file -e HEAD:tools/build-linux-release.sh \
  || die "commit the build tools before using this command"
[[ $root != *:* && $root != *$'\n'* ]] || die "checkout path contains unsupported characters"
revision=$(git rev-parse HEAD)
[[ $revision =~ ^[0-9a-f]{40}$ ]] || die "expected a full SHA-1 source revision"
default_image=false
if [[ -z $image ]]; then
  image="ghcr.io/pablovesnine/mhgurecomp-builder:$revision"
  default_image=true
fi

command -v docker >/dev/null || die "install Docker"
endpoint=
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
[[ $endpoint == unix://* ]] || die "select a local Docker socket"
unset DOCKER_HOST DOCKER_CONTEXT
engine_cmd=(docker --host "$endpoint")
security=$("${engine_cmd[@]}" info --format '{{json .SecurityOptions}}') \
  || die "cannot connect to Docker"
if [[ $security == *rootless* ]]; then
  user_args=()
else
  user_args=(--user "$(id -u):$(id -g)")
  for group in $(id -G); do
    [[ $group == "$(id -g)" ]] || user_args+=(--group-add "$group")
  done
fi

work="$root/.linux-release"
mkdir -p "$work"
exec 9>"$work/lock"
flock -n 9 || die "another Linux build is active"
context=''
cleanup() { [[ -z $context ]] || rm -rf -- "$context"; }
trap cleanup EXIT

inspect_image() {
  "${engine_cmd[@]}" image inspect --format \
    '{{.Id}} {{.Os}} {{.Architecture}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "$image"
}
description=''
if [[ $rebuild == false ]]; then
  if ! description=$(inspect_image 2>/dev/null); then
    [[ $skip_build == false ]] || die "builder image is missing; build or pull it first"
    if "${engine_cmd[@]}" pull --platform linux/amd64 "$image"; then
      description=$(inspect_image) || die "cannot inspect pulled image"
    else
      echo "linux-release: image unavailable; building tools from tracked HEAD"
    fi
  fi
fi
if [[ -z $description ]]; then
  # Never send a user's working tree (or dump) to the Docker daemon.
  context=$(mktemp -d "$work/image-context.XXXXXX")
  git archive "$revision" tools | tar -x -C "$context"
  if [[ $default_image == true ]]; then image="mhgurecomp-builder:$revision"; fi
  "${engine_cmd[@]}" build --platform linux/amd64 \
    --build-arg "SOURCE_REVISION=$revision" \
    --file "$context/tools/docker/Dockerfile" --tag "$image" "$context/tools"
  description=$(inspect_image) || die "cannot inspect locally built image"
fi
read -r image_id image_os image_arch image_revision extra <<< "$description"
[[ $image_id =~ ^sha256:[0-9a-f]{64}$ && -z $extra ]] || die "invalid builder image metadata"
[[ $image_os == linux && $image_arch == amd64 ]] || die "builder image must be linux/amd64"
[[ $image_revision == "$revision" ]] || die "builder image revision must match HEAD ($revision)"

cache="$work/$revision-${image_id#sha256:}-aarch64-$mode-$version-j$jobs"
mkdir -p "$cache"
# Keep downloads outside the fresh source export. No stale or private sources.
rm -rf "$cache/src"
mkdir -p "$cache/src/third_party"
git archive "$revision" | tar -x -C "$cache/src"
for library in ffmpeg sdl3 shaderc; do
  mkdir -p "$cache/downloads/$library"
  ln -s "/work/downloads/$library" "$cache/src/third_party/$library"
done
mounts=(-v "$cache:/work:Z")
if [[ $mode == release ]]; then
  mkdir -p "$root/dist"
  mounts+=(-v "$game:/game:ro,z" -v "$root/dist:/out:Z")
fi
echo "linux-release: sources $revision"
echo "linux-release: builder $image_id"
# Use the validated immutable ID, not a tag that another process could retarget.
"${engine_cmd[@]}" run --rm --platform linux/amd64 \
  "${user_args[@]}" "${mounts[@]}" "$image_id" "$mode" "$version" "$jobs" "$revision" "$image_id"
if [[ $mode == release ]]; then
  echo "linux-release: LinuxARM64-MHGURecomp.$version.tar.gz and SHA256SUMS are in dist/"
fi
