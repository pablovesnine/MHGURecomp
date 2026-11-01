#!/usr/bin/env bash
# Only upstream's currently advertised numeric tags can name an integrated release.
set -euo pipefail
umask 077
export LC_ALL=C GIT_NO_REPLACE_OBJECTS=1 GIT_TERMINAL_PROMPT=0

die() { echo "upstream-version: $*" >&2; exit 1; }
(($# == 0)) || die "expected no arguments; run from the repository"
upstream=https://github.com/morerokk/MHGURecomp.git
namespace=refs/upstream-version/observed
root=$(git rev-parse --show-toplevel) || die "run from the repository"
cd "$root"
full_history() {
  [[ $(git rev-parse --is-shallow-repository) == false ]] \
    || die "shallow history is unsafe; run: git fetch --unshallow origin"
}
full_history
common=$(git rev-parse --path-format=absolute --git-common-dir)
# A common-dir lock also covers linked worktrees. Never steal an active lock.
lock="$common/upstream-version.lock"
mkdir "$lock" 2>/dev/null || die "another upstream version lookup is active (lock: $lock)"
work=''
cleanup() {
  [[ -z $work ]] || rm -rf -- "$work"
  rmdir -- "$lock"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
work=$(mktemp -d "$common/upstream-version.XXXXXX")

# Do not prompt for, or ask credential helpers to disclose, authentication secrets.
remote_git() { GIT_ASKPASS=/bin/false git -c credential.helper= -c core.askPass= "$@"; }
advertised() {
  local oid ref
  remote_git ls-remote --tags "$upstream" > "$work/raw" \
    || die "cannot query upstream tags"
  while read -r oid ref; do
    # Annotated tags are fetched by their tag-object OID, then peeled locally.
    # Ignore ^{} advertisements and every nonnumeric/nonrelease tag name.
    if [[ $ref =~ ^refs/tags/([0-9]+(\.[0-9]+)*)$ ]]; then
      printf '%s\t%s\n' "${BASH_REMATCH[1]}" "$oid"
    fi
  done < "$work/raw" | sort -V
}
advertised > "$work/advertised"
[[ -s $work/advertised ]] || die "no numeric upstream tags are advertised"

refspecs=()
while read -r version oid; do
  previous=$(git rev-parse --verify "$namespace/$version" 2>/dev/null) || previous=''
  [[ -z $previous || $previous == "$oid" ]] \
    || die "upstream tag $version changed destination; refusing moved tag"
  # Permanent, non-tag refs are both the cache and the first-observation ledger.
  # No forced updates; the common-dir lock serializes observation snapshots.
  refspecs+=("$oid:$namespace/$version")
done < "$work/advertised"
remote_git fetch --atomic --quiet --no-tags --no-write-fetch-head \
  --no-recurse-submodules "$upstream" "${refspecs[@]}" >&2 \
  || die "cannot fetch upstream tags"

# Fetch the exact advertised objects, not a branch or remote executable. Refuse
# changes during the lookup instead of choosing from inconsistent snapshots.
advertised > "$work/confirmed"
cmp -s "$work/advertised" "$work/confirmed" \
  || die "upstream tags changed during lookup; retry"
full_history
selected=''
while read -r version oid; do
  commit=$(git rev-parse --verify "$namespace/$version^{commit}" 2>/dev/null) || continue
  if git merge-base --is-ancestor "$commit" HEAD; then
    selected=$version
  else
    status=$?
    ((status == 1)) || die "cannot check upstream tag ancestry"
  fi
done < "$work/advertised"
[[ -n $selected ]] || die "no numeric upstream tag is an ancestor of HEAD"
printf '%s\n' "$selected"
