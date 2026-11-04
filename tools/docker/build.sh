#!/usr/bin/env bash
set -euo pipefail

die() { echo "build: $*" >&2; exit 2; }
(($# == 5)) || die "expected MODE VERSION JOBS SOURCE_REVISION IMAGE_ID (ARM64 only)"
mode=$1
version=$2
jobs=$3
revision=$4
image_id=$5
[[ $mode == check || $mode == release ]] || die "expected release or check"
[[ $version =~ ^[0-9]+(\.[0-9]+)*$ ]] || die "invalid version"
[[ $jobs =~ ^[1-9][0-9]*$ ]] || die "invalid job count"
[[ $revision =~ ^[0-9a-f]{40}$ && $image_id =~ ^sha256:[0-9a-f]{64}$ ]] \
  || die "expected immutable source revision and image ID"
[[ $(cat /opt/mhgu/source-revision) == "$revision" ]] \
  || die "image tools and source revision do not match"
sysroot=/opt/mhgu/sysroot
cd /work/src
mkdir -p third_party/vk_mem_alloc
ln -sfn /opt/mhgu/include/vk_mem_alloc.h third_party/vk_mem_alloc/vk_mem_alloc.h
build=/work/build-aarch64
mkdir -p "$build"
# Failed/retried makes must never leave a usable old attestation.
rm -f "$build/build-metadata.json"

pilot() {
  local flags=(--target=aarch64-linux-gnu "--sysroot=$sysroot"
    "--gcc-toolchain=$sysroot/usr")
  local runner=(qemu-aarch64 -L "$sysroot")
  mkdir -p /work/pilot-aarch64
  printf '#include <stdio.h>\nint main(void){puts("ARM64 C pilot: OK");}\n' \
    > /work/pilot-aarch64/test.c
  printf '#include <vector>\nint main(){return std::vector<int>{0}.at(0);}\n' \
    > /work/pilot-aarch64/test.cpp
  clang "${flags[@]}" -fuse-ld=lld /work/pilot-aarch64/test.c -o /work/pilot-aarch64/c
  clang++ "${flags[@]}" -fuse-ld=lld /work/pilot-aarch64/test.cpp -o /work/pilot-aarch64/cxx
  python3 /opt/mhgu/docker/check-elf.py aarch64 /work/pilot-aarch64/c /work/pilot-aarch64/cxx
  "${runner[@]}" /work/pilot-aarch64/c
  "${runner[@]}" /work/pilot-aarch64/cxx
}

args=("TARGET_ARCH=aarch64" "B=$build" "O=/work/obj-aarch64"
  "GEN=/work/generated" "GAME=/game" "VERSION=$version" "JOBS=$jobs"
  "SYSROOT=$sysroot" "TEST_RUNNER=qemu-aarch64 -L $sysroot")
if [[ $mode == release ]]; then
  [[ -r /game/exefs/main && -r /game/exefs/sdk && -d /game/romfs ]] \
    || die "dump is unreadable in Docker; check ownership, ACLs and SELinux"
  rm -rf /work/generated.new
  make gen GAME=/game GEN=/work/generated.new
  rm -rf /work/generated
  mv /work/generated.new /work/generated
else
  test ! -d /work/generated
fi

pilot
# Build dependencies serially before Make's outer parallelism.
make -j1 "${args[@]}" licenses pipelist
programs=("$build/mhgurecomp")
if [[ $mode == release ]]; then programs+=("$build/mhgugame.so"); fi
make -j"$jobs" "${args[@]}" "${programs[@]}"
python3 /opt/mhgu/docker/check-elf.py aarch64 "${programs[@]}"
if [[ $mode == check ]]; then
  # All public checks are required, including actual menu navigation.
  make -j"$jobs" "${args[@]}" test-settings test-settings-locale \
    test-linux-fault test-settings-panel test-arm64-abi test-arcmerge
  python3 tests/test_build_arch.py
  python3 tests/test_linux_release.py
  exit 0
fi

compiler=$(clang --version)
compiler=${compiler%%$'\n'*}
python3 tools/dist.py record "$build" --version "$version" \
  --revision "$revision" --image "$image_id" --compiler "$compiler" \
  --host-packages /opt/mhgu/host-packages.tsv \
  --target-packages /opt/mhgu/arm64-packages.tsv
python3 tools/dist.py "$build" /work/packages linux "$version" \
  --revision "$revision" --image "$image_id"

mkdir -p /out
staging=$(mktemp -d /out/.arm64-release.XXXXXX)
trap 'rm -rf -- "$staging"' EXIT
name="LinuxARM64-MHGURecomp.$version.tar.gz"
cp "/work/packages/$name" "$staging/$name"
(
  cd "$staging"
  sha256sum "$name" > SHA256SUMS
  sha256sum -c SHA256SUMS
  chmod 644 "$name" SHA256SUMS
)
# Publish complete files only, with the checksum manifest last as commit marker.
mv -f "$staging/$name" "/out/$name"
mv -f "$staging/SHA256SUMS" /out/SHA256SUMS
