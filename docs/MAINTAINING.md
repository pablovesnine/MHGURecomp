# Maintenance

`master` is the only permanent branch, and normal merge commits preserve upstream history. There is no need to force-push, reset published history or manually approve routine upstream updates.

## Repository structure

The public build entry points are `tools/build-linux-release.sh` and `tools/upstream-version.sh`. Release synchronization lives in `.github/maintenance/sync-upstream.py`, with trusted policy in `.github/maintenance/fork-policy.json` and pinned release state in `.github/maintenance/upstream-release.tsv`. Runtime code lives in `runtime/`, recompiler tools and build helpers in `tools/`, and regression tests in `tests/`.

The five maintained workflows each have a separate job:

- [linux-ci.yml](../.github/workflows/linux-ci.yml): push/PR quick checks and manual full validation.
- [linux-checks.yml](../.github/workflows/linux-checks.yml): reusable quick checks.
- [linux-builder.yml](../.github/workflows/linux-builder.yml): reusable ARM64 validation and tools-image artifact.
- [linux-publisher.yml](../.github/workflows/linux-publisher.yml): publish an already validated master image.
- [upstream-sync.yml](../.github/workflows/upstream-sync.yml): discover, validate and promote stable upstream releases.

The experimental Vulkan replay diagnostic (vkreplay.c) is retired. `tools/vkprobe.c` is still available as an optional diagnostic, but the build does not need it. Runtime networking still needs `updater/sha256.c` and its interface in `updater/updater.h`. Despite the directory name, these are not a binary updater. The recompiler differential tests still need `tools/test_lift.py` and `tools/test_harness.c`.

## Automatic upstream updates

**Synchronize stable upstream releases after ARM64 validation** checks published Releases from `morerokk/MHGURecomp` every hour and after pushes to master. You can also run it manually from Actions. Drafts, prereleases, standalone tags and commits on upstream's development master do not trigger integration.

1. Select the most recently published stable release (ID breaks time ties), validate its numeric version and pin its exact tag object and commit.
2. Prepare a policy-aware merge using the previous recorded release as its explicit three-way base, not Git's historical merge base.
3. Validate the exact candidate with public ARM64 tests.
4. Advance `master` only if validation passed and its expected base has not changed.
5. Publish the same tested tools image to GHCR.
6. Remove only the incorporated temporary branch tip.

`.github/maintenance/upstream-release.tsv` records the stable release identity. Editing fork documentation or upstream release notes does not cause the same release to be integrated again. A newer release still needs validation even if it points to the same commit. Missing or reclassified releases, moved tags, API failures, downgrades and divergent histories stop synchronization rather than falling back to master.

The 0.13.1 migration keeps historical development commits in the ancestry, but removes their runtime contribution. Future merges use the recorded release base explicitly so those changes can return when a release includes them. Each merge records the exact fork and release parents, even when one is already an ancestor. Promotion recomputes the expected tree.

The internal `bot/upstream-sync` branch exists only while an update is under test or needs intervention. It is not a second product branch, and automation never overwrites human edits there. If a candidate becomes stale, automation keeps it for review rather than adding ordinary merges or force-updating it.

`.github/maintenance/fork-policy.json` protects my README, automation and build rules, and keeps retired paths deleted. Shared runtime, recompiler and dependency changes merge normally. Automation reads the policy from trusted master, not from the candidate, and Actions reports which upstream changes it excluded.

Keeping a fork-owned build file can leave out an upstream build adjustment, so check those summaries when diagnosing incompatibilities. The generated release TSV is the only exception for protected paths: its bytes must match the trusted release record exactly. All other protected content and file modes stay unchanged.

An unexpected shared-code conflict stops integration and updates one issue. If the blocker has not changed, automation does not start another build or create a duplicate issue. Resolve each file individually rather than using a blanket merge strategy. Automation closes the issue once the blocking upstream revision is incorporated. Failed tests do not count as a successful update. To retry an unchanged blocker, select `retry_validation` on a manual run.

## CI and images

Pushes and PRs run syntax checks, ShellCheck, actionlint and offline Python regressions for policy, release state, documentation and privacy. These quick checks do not build Docker images or run QEMU.

Full validation runs for a new eligible stable release or when you manually request **Linux fork checks and manual ARM64 validation**. It starts with quick checks, then uses Docker/QEMU to test compiler probes, the ARM64 runtime, settings/panel navigation, fault handling and ELF imports. Neither workflow receives a dump or tests the game or GPU.

The tools image runs on a Linux x86_64 build PC and cross-compiles for ARM64. Keep that distinction clear in the build internals, because ARM64 is the only product. The build needs Docker Engine with a local Unix socket. Fedora's installed Moby engine works, so there is no need to replace a working installation.

Source downloads have connection, transfer and retry limits. If FFmpeg's primary host is unavailable, the build can use the explicit MacPorts source mirror. Both URLs must match the same pinned SHA-256. A checksum mismatch stops the build immediately, and failed transfers leave no usable archive.

Tools images use `ghcr.io/pablovesnine/mhgurecomp-builder:<full-source-SHA>`. The publisher checks master, image identity, platform and source labels without executing candidate code. Public images need no registry login. If publication fails after master has advanced, retry publication for the same validated SHA rather than rolling back source history.

To run **Publish a validated master tools image** manually, use the source SHA, image ID, artifact name and run ID from the builder summary. The transport artifact lasts one day. If it has expired, a manual master CI run can rebuild, validate and publish. After a successful manual recovery, close issue #2. A no-op sync deliberately leaves an unresolved publication warning open.

Read/write Git/API work, read-only candidate execution and package publication run in separate jobs. Automation uses short-lived GITHUB_TOKEN credentials. Never add a personal token as a permanent secret.

## GitHub settings

Keep Actions, scheduled workflows and Issues enabled. The GHCR package must stay public and accessible to this repository's Actions. GitHub may disable schedules in public repositories after prolonged inactivity. If that happens, re-enable them in Actions rather than adding artificial keepalive commits. Dependency update PRs stay open for review and are separate from upstream sync.

## Local build and privacy

Follow the public commands in the [README](../README.md#build), using `tools/build-linux-release.sh` and your own dump path. Update a clean master checkout with `git pull --ff-only origin master`. Do not reset local changes or clear ignored caches just to update. Keep personal convenience scripts outside the checkout and out of Git. The public wrapper exports tracked HEAD, not unrelated working files.

Dump mounts are read-only. The wrapper adjusts SELinux labels on the dedicated dump, work and output directories. Never point the dump option at your home root.

Release builds use the stable version pinned in `.github/maintenance/upstream-release.tsv`. `bash tools/upstream-version.sh` verifies the exact upstream tag object and commit in a separate ref namespace. It does not use local/fork tags or a higher tag from a historical ancestor. Verification needs network access and full Git history, and the build stops if tags are missing, moved or unverifiable. An explicit `--version` must match the pinned and verified version.

The version number stays the same between releases, while metadata records the exact SHA, tools image and program hashes. Verify checksums only after a successful build, because a failed attempt may leave old archives with the same version.

`.linux-release/`, logs and `dist/` are local outputs, not tracked sources. Never attach dumps, generated sources or private build folders to Issues. CI publishes only the tools image, without a dump or game package.

I can publish a local build with `--publish` on the public build command. This needs authenticated GitHub CLI, Docker buildx and host `llvm-objdump`. Publication requires a clean current master checkout, verified upstream identity, full ARM64 validation and tools-image provenance for that exact SHA.

Publish builds retain their checked outputs in a fresh private directory and print its path. The standalone publisher can check or retry those same files:

```bash
python3 tools/publish-linux-release.py --dist .linux-release/publish.EXAMPLE --dry-run
python3 tools/publish-linux-release.py --dist .linux-release/publish.EXAMPLE
```

`--dry-run` performs preflight checks without creating a tag, release or asset. The publisher checks the archive allowlist, ARM64 programs, metadata and checksums before creating a new draft. It uploads only the package and `SHA256SUMS`, verifies their hashes, then publishes. A failed upload leaves a recoverable draft. Retry the same files, not a rebuild with different archive timestamps. Different existing tags or assets stop publication rather than being replaced. Existing 0.13.1 assets remain unchanged.

Changing the guest base or signed-char flags requires rebuilding both the runtime and the generated game library. The game-library identity includes the relevant headers and flags, so an old library cannot be relabeled safely. The public build uses revision-separated work directories.

The project's license does not authorize redistribution of game-derived code. Keep licenses and required third-party sources intact.

## ARM64 compatibility

The signed-char and 64-GiB guest-base corrections follow the ARM64 approach in [cerroverb's 0.14.0.1 source](https://github.com/cerroverb/MHGURecomp/tree/267c2be968128bf0d9d2dbd82b2e4e35e71ef6b6). The guest window remains 4 GiB. This fork already had the BC fallback, ARM64 glibc wrappers and cross-compiler test controls. I kept those implementations instead of adding duplicates. These are compatibility changes, not measured FPS or build-speed improvements.
