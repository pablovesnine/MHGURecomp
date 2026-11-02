#!/usr/bin/env bash
# The reviewed state file, never the greatest ancestor tag, pins the release.
set -euo pipefail
umask 077
export LC_ALL=C GIT_NO_REPLACE_OBJECTS=1 GIT_TERMINAL_PROMPT=0

die() { echo "upstream-version: $*" >&2; exit 1; }
(($# == 0)) || die "expected no arguments; run from the repository"
upstream=https://github.com/morerokk/MHGURecomp.git
root=$(git rev-parse --show-toplevel) || die "run from the repository"
cd "$root"
full_history() {
  [[ $(git rev-parse --is-shallow-repository) == false ]] \
    || die "shallow history is unsafe; run: git fetch --unshallow origin"
  local grafts
  grafts=$(git rev-parse --git-path info/grafts)
  [[ ! -s $grafts ]] || die "grafted history is unsafe; remove info/grafts"
}
full_history
common=$(git rev-parse --path-format=absolute --git-common-dir)
# Serialize all linked worktrees; never remove somebody else's active lock.
lock="$common/upstream-version.lock"
mkdir "$lock" 2>/dev/null || die "another upstream version lookup is active (lock: $lock)"
work=''
isolated_ref=''
cleanup() {
  if [[ -n $isolated_ref ]]; then
    git update-ref -d "$isolated_ref" >/dev/null 2>&1 || :
  fi
  [[ -z $work ]] || rm -rf -- "$work"
  rmdir -- "$lock" 2>/dev/null || :
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
work=$(mktemp -d "$common/upstream-version.XXXXXX")

# Read data, not shell. -d '' detects NUL rather than silently discarding it,
# and preserves the final LF, unlike command substitution.
state_file=.github/maintenance/upstream-release.tsv
[[ -f $state_file && -r $state_file ]] || die "missing or unreadable state file"
state=''
if IFS= read -r -d '' state < "$state_file"; then
  die "invalid state: NUL byte"
fi
[[ $state == *$'\n' && $state != *$'\r'* ]] || die "invalid state: expected canonical LF"
keys=(schema algorithm repository release_id version tag tag_oid commit
      published_at fork_base migration_merge migration_source)
# Explicit initialization also lets static analyzers follow printf -v below.
schema='' algorithm='' repository='' release_id='' version='' tag=''
tag_oid='' commit='' published_at='' fork_base='' migration_merge='' migration_source=''
for key in "${keys[@]}"; do
  [[ $state == *$'\n'* ]] || die "invalid state: missing $key"
  line=${state%%$'\n'*}
  state=${state#*$'\n'}
  [[ $line == "$key"$'\t'* ]] || die "invalid state: expected key $key"
  value=${line#*$'\t'}
  [[ -n $value && $value != *$'\t'* ]] || die "invalid state: malformed $key"
  printf -v "$key" '%s' "$value"
done
[[ -z $state ]] || die "invalid state: extra or duplicate keys"
[[ $schema == 1 && $algorithm == release-base-v1 &&
   $repository == morerokk/MHGURecomp ]] || die "invalid state: unsupported schema, algorithm or repository"
[[ $release_id =~ ^[1-9][0-9]*$ ]] || die "invalid state: release_id must be positive"
[[ $version =~ ^[0-9]+(\.[0-9]+)*$ && $tag == "$version" ]] \
  || die "invalid state: version and tag must be identical numeric versions"
for oid in "$tag_oid" "$commit" "$fork_base" "$migration_merge" "$migration_source"; do
  [[ $oid =~ ^[0-9a-f]{40}$ ]] || die "invalid state: expected lowercase 40-character OID"
done
utc_pattern='^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z$'
[[ $published_at =~ $utc_pattern ]] || die "invalid state: published_at must be exact UTC"
year=$((10#${BASH_REMATCH[1]}))
month=$((10#${BASH_REMATCH[2]}))
day=$((10#${BASH_REMATCH[3]}))
hour=$((10#${BASH_REMATCH[4]}))
minute=$((10#${BASH_REMATCH[5]}))
second=$((10#${BASH_REMATCH[6]}))
((year > 0 && month >= 1 && month <= 12 && day >= 1 &&
  hour <= 23 && minute <= 59 && second <= 59)) || die "invalid state: published_at date or time"
days=(0 31 28 31 30 31 30 31 31 30 31 30 31)
if ((year % 4 == 0 && (year % 100 != 0 || year % 400 == 0))); then
  days[2]=29
fi
((day <= days[month])) || die "invalid state: published_at date"

# No prompts, credentials, local tags, fallback cache or remote executable.
remote_git() { GIT_ASKPASS=/bin/false git -c credential.helper= -c core.askPass= "$@"; }
upstream_ref="refs/tags/$tag"
advertised() {
  local line oid ref advertised_oid='' peeled=''
  remote_git ls-remote --tags "$upstream" "$upstream_ref" "$upstream_ref^{}" > "$work/raw" \
    || die "cannot query upstream tag"
  while IFS= read -r line || [[ -n $line ]]; do
    [[ $line == *$'\t'* ]] || die "invalid upstream tag advertisement"
    oid=${line%%$'\t'*}
    ref=${line#*$'\t'}
    [[ $oid =~ ^[0-9a-f]{40}$ ]] || die "invalid upstream tag OID"
    case $ref in
      "$upstream_ref")
        [[ -z $advertised_oid ]] || die "duplicate upstream tag advertisement"
        advertised_oid=$oid ;;
      "$upstream_ref^{}")
        [[ -z $peeled ]] || die "duplicate upstream peeled advertisement"
        peeled=$oid ;;
      *) die "unexpected upstream tag advertisement" ;;
    esac
  done < "$work/raw"
  [[ -n $advertised_oid ]] || die "pinned upstream tag $tag is not advertised"
  [[ $advertised_oid == "$tag_oid" ]] || die "upstream tag $tag does not match pinned tag OID"
  [[ ${peeled:-$advertised_oid} == "$commit" ]] \
    || die "upstream tag $tag does not match pinned commit"
  printf '%s\t%s\n' "$advertised_oid" "${peeled:--}"
}
advertised > "$work/advertised"
# A unique non-tag ref keeps local fork tags and all existing refs untouched.
isolated_ref="refs/upstream-version/${work##*/}/pinned"
remote_git fetch --atomic --quiet --no-tags --no-write-fetch-head \
  --no-recurse-submodules "$upstream" "$tag_oid:$isolated_ref" >&2 \
  || die "cannot fetch upstream pinned tag"
advertised > "$work/confirmed"
cmp -s "$work/advertised" "$work/confirmed" \
  || die "upstream tag changed during lookup; retry"
full_history
fetched_oid=$(git rev-parse --verify "$isolated_ref") || die "cannot verify fetched tag"
[[ $fetched_oid == "$tag_oid" ]] || die "fetched tag does not match pinned tag OID"
fetched_commit=$(git rev-parse --verify "$isolated_ref^{commit}" 2>/dev/null) \
  || die "pinned upstream tag is not a commit"
[[ $fetched_commit == "$commit" ]] || die "fetched tag does not match pinned commit"
if git merge-base --is-ancestor "$commit" HEAD; then
  :
else
  status=$?
  ((status == 1)) || die "cannot check pinned upstream commit ancestry"
  die "pinned upstream commit is not an ancestor of HEAD"
fi
# Remove the fetched ref before emitting the sole successful stdout line.
git update-ref -d "$isolated_ref" "$tag_oid" || die "cannot clean isolated upstream ref"
isolated_ref=''
printf '%s\n' "$version"
