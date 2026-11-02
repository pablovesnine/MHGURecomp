# Maintenance

`master` is the only permanent branch. Upstream history is retained through
normal merge commits. No force-push, reset of published history or routine
manual PR approval is needed.

## Automatic upstream updates

**Synchronize stable upstream releases after ARM64 validation** checks
published Releases from `morerokk/MHGURecomp` every six hours, after master
pushes, and manually from Actions. Drafts, prereleases, standalone tags and
development master commits do not trigger integration.

1. Select the most recently published stable release (ID breaks time ties),
   validate its numeric version and pin its exact tag object and commit.
2. Prepare a policy-aware merge using the previous recorded release as
   its explicit three-way base, not Git's historical merge base.
3. Validate the exact candidate with public ARM64 tests.
4. Advance `master` only if validation passed and its expected base has
   not changed.
5. Publish the same tested tools image to GHCR.
6. Remove only the incorporated temporary branch tip.

`tools/upstream-release.tsv` records the stable release identity. The same
release remains a no-op after fork documentation or upstream release-note
edits. A new higher release at the same commit still requires validation.
Missing/reclassified releases, moved tags, API failures, downgrades and
divergent histories stop synchronization; there is no master fallback.

The 0.13.1 migration retains historical development ancestors but removes
their runtime contribution. Future merges therefore use the recorded
release base explicitly so included changes can return without accidentally
omitting them. Two exact parents record fork/release provenance even when
one is already an ancestor. Promotion recomputes the expected tree.

The internal `bot/upstream-sync` branch exists only while an update is
being tested or needs intervention. It is not a second product branch.
Human edits on that branch are never overwritten.
Stale candidates are also preserved for intervention rather than extended
with ordinary merges or force-updated.

`tools/fork-policy.json` protects the fork's README, automation and build
rules and keeps retired paths deleted. Shared runtime, recompiler and
dependency changes merge normally. The policy comes from trusted master,
not from the candidate. Actions reports which upstream changes the policy
excluded. Preserving a fork-owned build file can omit an upstream build
adjustment; inspect these summaries when diagnosing incompatibilities.
The generated release TSV is the sole protected-path exception: its exact
expected bytes must match the trusted release record. All other protected
content and modes remain unchanged.

An unexpected shared-code conflict stops integration and updates one issue.
Repeated unchanged blockers do not trigger new builds or duplicate issues.
Resolve files individually; do not use a blanket merge strategy.
The issue is closed after its blocking upstream revision is incorporated.
Test failures remain failures, not successful updates. Select
`retry_validation` on a manual run to retry an unchanged blocker.

## CI and images

Pushes and PRs run quick checks: syntax, ShellCheck, actionlint and offline
Python regressions covering policy, release state, documentation and privacy.
They do not build Docker images or run QEMU.

Full validation runs for a new eligible stable release or a manual
**Linux fork checks and manual ARM64 validation** request. It first runs
quick checks, then compiler probes, the ARM64 runtime, settings/panel
navigation, fault handling and ELF imports using Docker/QEMU.
Neither workflow receives a dump or exercises the game or GPU.

The tools image runs on a Linux x86_64 build PC and cross-compiles for
ARM64. Keep that distinction in build internals; ARM64 is the only product.
Docker Engine with a local Unix socket is required; Fedora's installed
Moby engine is suitable. Do not replace an existing working installation.

Tools images use
`ghcr.io/pablovesnine/mhgurecomp-builder:<full-source-SHA>`.
The publisher verifies master, image identity, platform and source labels;
it does not execute candidate code. A public image needs no registry login.
If publication fails after master advanced, retry publication for the same
validated SHA rather than rolling back source history. The builder summary
provides the source SHA, image ID, artifact name and run ID for the manual
**Publish a validated master tools image** workflow. Its transport artifact
lasts one day. A manual master CI run can rebuild, validate and publish if
the artifact expired. After successful manual recovery, close issue #2;
a no-op sync deliberately keeps an unresolved publication warning open.

Read/write Git/API work, read-only candidate execution and packages
publication use separate jobs. Automation uses short-lived GITHUB_TOKEN;
never add a personal token as a permanent secret.

## GitHub settings

Keep Actions, scheduled workflows and Issues enabled. The GHCR package
must remain public and accessible to this repository's Actions.
Public-repository schedules may be disabled after prolonged inactivity;
re-enable them in Actions rather than adding artificial keepalive commits.
Dependency update PRs remain reviewable; they are not upstream sync.

## Local build and privacy

Follow the public commands in the [README](../README.md#build), using
`tools/build-linux-release.sh` and your own dump path.
Update a clean master checkout with `git pull --ff-only origin master`;
do not reset local changes or clean ignored caches to update.
Personal convenience scripts belong outside the checkout, not in Git.
The public wrapper exports tracked HEAD, not unrelated working files.
Dump mounts are read-only; SELinux labels are adjusted on the dedicated
dump/work/output directories. Never point the dump option at your home root.

Release builds use the stable version pinned in `tools/upstream-release.tsv`.
`bash tools/upstream-version.sh` verifies its exact upstream tag object and
commit in a separate ref namespace, not local/fork tags or a higher historical
ancestor tag. Verification needs network access and full Git history;
missing, moved or unverifiable tags stop the build. An explicit `--version`
must equal the pinned and verified version.
Between releases the number stays unchanged; metadata records the exact SHA,
tools image and program hashes. Verify checksums only after a successful build;
old archives with the same version may still exist after a failed attempt.

`.linux-release/`, logs and `dist/` are local outputs, not tracked sources.
Never attach dumps, generated sources or private build folders to Issues.
Maintainer release uploads are manual; automation creates no fork tags or
GitHub Releases. CI publishes only the tools image.
The fork's license does not authorize redistribution of game-derived code.
Licenses and required third-party sources must remain intact.
