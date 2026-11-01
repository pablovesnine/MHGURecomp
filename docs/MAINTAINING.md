# Maintenance

`master` is the only permanent branch. Upstream history is retained through
normal merge commits. No force-push, reset of published history or routine
manual PR approval is needed.

## Automatic upstream updates

**Synchronize upstream after read-only ARM64 validation** checks
`morerokk/MHGURecomp:master` every six hours, after master pushes, and
can also be started manually from Actions.

1. Prepare a normal merge using the fork policy.
2. Validate the exact candidate with public ARM64 tests.
3. Advance `master` only if validation passed and its expected base has
   not changed.
4. Publish the same tested tools image to GHCR.
5. Remove only the incorporated temporary branch tip.

The internal `bot/upstream-sync` branch exists only while an update is
being tested or needs intervention. It is not a second product branch.
Human edits on that branch are never overwritten.

`tools/fork-policy.json` protects the fork's README, automation and build
rules and keeps retired paths deleted. Shared runtime, recompiler and
dependency changes merge normally. The policy comes from trusted master,
not from the candidate. Actions reports which upstream changes the policy
excluded. Preserving a fork-owned build file can omit an upstream build
adjustment; inspect these summaries when diagnosing incompatibilities.

An unexpected shared-code conflict stops integration and updates one issue.
Repeated unchanged blockers do not trigger new builds or duplicate issues.
Resolve files individually; do not use a blanket merge strategy.
The issue is closed after its blocking upstream revision is incorporated.
Test failures remain failures, not successful updates. Select
`retry_validation` on a manual run to retry an unchanged blocker.

## CI and images

Public CI checks scripts, Python regressions, compiler probes, the ARM64
runtime, settings/panel navigation, fault handling and ELF imports.
It never receives a dump or exercises the game or GPU.

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

Release builds use the highest numeric upstream tag incorporated into HEAD.
`bash tools/upstream-version.sh` reports that version, using the fixed upstream
remote and a separate ref namespace, not local or fork tags. Verification needs
network access and full Git history; missing, moved or unverifiable tags stop
the build. An explicit `--version` must equal the resolved upstream version.
Between releases the number stays unchanged; metadata records the exact SHA,
tools image and program hashes. Verify checksums only after a successful build;
old archives with the same version may still exist after a failed attempt.

`.linux-release/`, logs and `dist/` are local outputs, not tracked sources.
Never attach dumps, generated sources or private build folders to Issues.
Maintainer release uploads are manual; automation creates no fork tags or
GitHub Releases. CI publishes only the tools image.
The fork's license does not authorize redistribution of game-derived code.
Licenses and required third-party sources must remain intact.
