# Maintenance

`master` is the only permanent branch, and normal merge commits preserve upstream history. I request upstream updates manually to control Actions usage; the workflow still validates and promotes the exact candidate without a separate approval. There is no need to force-push or reset published history.

## Repository structure

The public build entry points are `tools/build-linux-release.sh` and `tools/upstream-version.sh`. Release synchronization lives in `.github/maintenance/sync-upstream.py`, with trusted policy in `.github/maintenance/fork-policy.json` and pinned release state in `.github/maintenance/upstream-release.tsv`. Runtime code lives in `runtime/`, recompiler tools and build helpers in `tools/`, and regression tests in `tests/`.

The five maintained workflows each have a separate job:

- [linux-ci.yml](../.github/workflows/linux-ci.yml): manual full validation, with one reusable quick-check job.
- [linux-checks.yml](../.github/workflows/linux-checks.yml): reusable quick checks.
- [linux-builder.yml](../.github/workflows/linux-builder.yml): reusable ARM64 validation and tools-image artifact.
- [linux-publisher.yml](../.github/workflows/linux-publisher.yml): publish an already validated master image.
- [upstream-sync.yml](../.github/workflows/upstream-sync.yml): discover, validate and promote stable upstream releases.

The experimental Vulkan replay diagnostic (vkreplay.c) is retired. `tools/vkprobe.c` is still available as an optional diagnostic, but the build does not need it. Runtime networking still needs `updater/sha256.c` and its interface in `updater/updater.h`. Despite the directory name, these are not a binary updater. The recompiler differential tests still need `tools/test_lift.py` and `tools/test_harness.c`.

## Manual upstream updates

I run **Synchronize stable upstream releases after ARM64 validation** only when I request an update manually from Actions. There is no scheduled polling or push trigger. It checks published Releases from `morerokk/MHGURecomp`; drafts, prereleases, standalone tags and commits on upstream's development master do not qualify for integration.

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

I also protect `runtime/hle/villagehub.c` to retain a bounded supply-box trace formatter. Upstream 0.15.0 advances a buffer pointer by snprintf's untruncated length; a full box can overrun the trace buffer with `MHGU_VQ_TRACE` enabled. Review future upstream edits to this file manually rather than dropping the safety fix. Other runtime paths remain shared.

`tools/test_lift.py` is protected after reconciling its 0.15.0 conflict with my compiler/target/runner controls. Review future upstream changes to this test driver manually too; the surrounding recompiler tools and public test sources still merge normally.

I protect `tests/test_settings_panel.cpp` after reconciling 0.15.1's constant Forge stubs with the controlled availability and one-shot-request assertions. I ported the upstream Mouse4 case explicitly, under `MHGU_TEST_MOUSE_CAPTURE`; the corrected Forge navigation includes the conditional suggested-order row. Review future fixture changes manually. The runtime panel and other public tests remain shared.

For 0.15.2 I also ported the frame counter and text-row navigation into that fixture. `MHGU_TEST_TEXT_HDR` checks Save and live publication of kerning and text weight while retaining Forge and Mouse4 coverage. `tests/frame_counter_fixture.c` supplies the UI counter for the separate engine-module test, which links config.c without a renderer.

For 0.15.3 I ported the spawn-demo hook into protected `villagehub.c` without replacing the safe formatter. I restored two upstream-only server-reference comments in shared `runtime/net/ldn.c` to remove a prose conflict; this does not restore the retired server product. Network runtime remains shared. I protect only the exact new fixture paths `tests/test_ldn_direct.c` and `tests/test_villagehub_demo.c`.

For 0.15.4 I keep the shared fastload, HP-scaling, mouse-camera, ImGui and renderer changes. The Makefile's HLE wildcard includes the new fastload source. Android file-location and log-sharing flows remain outside this Linux product; their guarded declarations do not add a desktop page. I port the applicable settings and feature explanations here and in the README, without restoring the retired upstream STATUS or research documents or copying upstream game timings as my own results. I protect the exact new fixture paths, not a runtime prefix.

For 0.16.0 I port the Village list reload and Chinese text-archive lifecycle into protected `runtime/hle/villagehub.c`, retaining the bounded trace and spawn-demo hook. The network wildcard includes shared hitsync.c. `MHGU_TEST_LAGCOMP` extends the protected panel fixture at the actual Misc row: Save, discard and Reset this tab retain live-setting boundaries. Temporary mod bindings must not replace the player's saved keys. I keep runtime networking, Forge, input, chat, combo-window and graphics paths shared, protecting only the exact new fixture filenames and their common test header.

An unexpected shared-code conflict stops integration and updates one issue. If the blocker has not changed, automation does not start another build or create a duplicate issue. Resolve each file individually rather than using a blanket merge strategy. Automation closes the issue once the blocking upstream revision is incorporated. Failed tests do not count as a successful update. To retry an unchanged blocker, select `retry_validation` on a manual run.

## CI and images

Pushes and PRs do not start Actions. I run syntax checks, ShellCheck, actionlint and offline Python regressions locally before pushing. The manual validator runs these quick checks once before the ARM64 job; the quick-check job itself does not build Docker images or run QEMU.

Full validation runs only when I request **Synchronize stable upstream releases after ARM64 validation** for an eligible update or **Linux fork checks and manual ARM64 validation** for current master. I use one workflow, not both for the same candidate, and inspect failures before authorizing a retry. It starts with quick checks, then uses Docker/QEMU to test compiler probes, the ARM64 runtime, settings/panel navigation, fault handling and ELF imports. Neither workflow receives a dump or tests the game or GPU.

I reuse the existing cache for reads but export no new cache. Docker build records are not uploaded. The only required image transport artifact expires after one day; after verifying publication, I can remove that exact artifact early. I keep the tested-image handoff and separate job permissions rather than rebuilding the image or weakening publication checks. A manual workflow contains several jobs, so one workflow is not one billed job.

For source pins from 0.14.3, engine-module and cheat tests are mandatory. From 0.15.0, `test-interp` exercises public synthetic ARM instructions, predecoded operations and cache invalidation; `test-villagehub` checks synthetic supply slots and trace safety. The panel fixture also compiles with `MHGU_TEST_FORGE_MENU` to test disabled access and one-shot Forge requests without loading a plugin. Selection uses the tracked source pin, never the check-mode package version `0` or whether a test file happens to exist. Missing sources must fail.

From 0.15.1, `test-crossplay-bins` builds five public AArch64 fixtures with Unix ENet, bundled verified zstd 1.5.7 and C++20. The same immutable tools image then runs `test-crossplay` in a second Docker container with `--network none`. The supervisor refuses any namespace with interfaces other than loopback, checks child exit codes and final assertions, enforces deadlines and reaps every fixture process. It tests room/client traffic, Ryu client traffic with a Python stub and the embedded C++ server, and a mixed synthetic hub using the production embedded servers. It does not run upstream's Windows shell launchers, whose error handling can hide failures.

From 0.15.2, `test-textlayout` exercises the production text-layout helpers with public synthetic archives, compressed and plain entries, texture bounds and kerning pairs. It is mandatory by source pin and its ELF is checked before delivery. It uses no game fonts or GPU. The runtime links system zlib dynamically; both the Docker host and target sysroot already install `zlib1g-dev`. Upstream's RenoDX attribution and MIT text remain in the shared notices. Rebuild generated game code after this update: camera and text patches changed, and `check-generated` still guards the actual packaging path.

From 0.15.3, `test-ldn-direct` and `test-villagehub-demo` are mandatory by source pin, with checked AArch64 ELFs. The direct fixture intercepts network I/O and time: it must not open sockets or contact a real hub. The Village fixture uses bounded synthetic memory, not guest dumps or fixed host mappings. It checks session, quest, slot and event-area gates, one-shot release, reset and register/original-call ordering. The existing supply and trace test remains mandatory. `MHGU_TEST_DIRECT` adds Network-row navigation, INI Save and live-setting assertions while retaining Forge, Mouse4 and text checks.

From 0.15.4, `test-fastload`, `test-hpscale` and `test-mousecam` are mandatory with checked AArch64 ELFs and QEMU execution. They include the production hooks with bounded synthetic guest memory, intercepted time and input, and no game or network connection. They cover offline/session gates and original-call ordering, HP and part-row state, and normal/aim camera transitions. Missing source or executable is a failure, not a reason to skip. I also run these fixtures natively with AddressSanitizer and UndefinedBehaviorSanitizer before publishing source.

`tests/test_0154_portable.py` checks thunk regeneration, 32-bit guest/64-bit host cursor layouts, production mirror conversion helpers and the paired front-face uniform/shader contract. Its compiler checks include generic AArch64; they do not run a GPU. Public synthetic tests do not validate loading times, bow handling, monster part behavior, real plugin rendering or HDR. The existing Direct, Village, interpreter, text, panel and isolated crossplay gates remain required.

From source pin 0.16.0, `test-hitsync`, `test-chat`, `test-itembar`, `test-combowin` and `test-villagehub-text` are mandatory, with QEMU execution and checked AArch64 ELFs. They include the production hooks and use bounded synthetic guest memory, intercepted input, clock, resource and transport calls. No game, emulator, real hub, fixed host mapping or GPU participates. `tests/test_0160_fixture.h` shares only the chat/wheel test seam. Missing fixtures must fail, not skip. The preparation commit retains the previous pin; only that older pin may skip the new native sanitizer cases.

`tests/test_0160_portable.py` runs those hooks natively with fail-closed ASan/UBSan and checks actual generator snippets, original instruction order and a negative combo-window control. `tests/test_0160_contracts.py` covers portable graphics and Forge/input helper contracts without claiming full rendering or plugin execution. The two new combo hooks change generation identity: regenerate from the local dump and let `check-generated` reject stale output.

The hitsync fixture records actual wire layout, opt-in/old-peer fallback, supported shot capabilities, field bounds, ownership, arrival ordering, queue expiry and original-call staging. It also characterizes limits rather than asserting features the code lacks: duplicate reports are not deduplicated, payload slots are not authenticated, and disconnect/repeated init do not reset state. Running its `--red-active-drain` mode deliberately fails on the pending-report activation gap described in the settings guide. Separate chat and wheel RED modes demonstrate malformed-UTF-8 and extreme-integer hardening limits. These are known upstream limitations, not passing safety guarantees or proven real-game exploits.

The graphics contracts also retain explicit RED probes for backward-branch FMZ tracking and stacked-group scissor prediction. Both must compile for generic AArch64 and natively, then fail at their specific runtime assertion; a compiler failure or unrelated assertion cannot satisfy the check. I do not mark arbitrary test failures as expected successes. The original 0.15.4 front-face test remains unchanged and required. Source pins newer than 0.16.0 still run these contracts rather than silently skipping them.

I retain the new netrate, dummy-slot/facing, KO-owner and quickhunt diagnostics as opt-in code, not normal startup behavior. `MHGU_NETRATE`, `MHGU_DUMMY`, `MHGU_KOTRACE`, `MHGU_FORCE_EVENT`, `MHGU_KILL_AFTER`, `MHGU_VQ_DEMO_TEST`, `MHGU_LDN_RTT` and `MHGU_LDN_BLOCK_DIRECT` are developer controls, not gameplay validation. Use only valid, bounded inputs. I do not enable them in the product or treat their counters as a measured speedup.

The tests use the production room server rather than the weak room stand-in, whose proxy offsets are incorrect. Fixture initialization only makes readiness output line-buffered and matches Linux runtime SIGPIPE handling. No real emulator or game participates. Synthetic success does not validate passphrase enforcement, repeated bridge teardown/restart, departed-member cleanup or real game-packet rewriting. Keep those separate from transport coverage.

I retain source SPDX headers and include the suyu Emulator Project MIT attribution for the embedded C++ server in `THIRD_PARTY_NOTICES`. ENet's notice and the bundled zstd license also travel with the package. The new CPU metadata remains x86-guarded; ARM64 does not require AVX2. The generated game library and loader must still be rebuilt together when their identity changes.

`tools/test_lift.py --interp-ops` adds differential predecoded-operation testing while retaining `--cc`, `--genarch`, signed-char compilation and `--runner`. These NSO-based differential tests require a local licensed dump and are not part of public CI. Public synthetic tests do not establish GPU correctness, physical-controller behavior or arbitrary concurrent guest-code patch safety.

The tools image runs on a Linux x86_64 build PC and cross-compiles for ARM64. Keep that distinction clear in the build internals, because ARM64 is the only product. The build needs Docker Engine with a local Unix socket. Fedora's installed Moby engine works, so there is no need to replace a working installation.

Source downloads have connection, transfer and retry limits. If FFmpeg's primary host is unavailable, the build can use the explicit MacPorts source mirror. Both URLs must match the same pinned SHA-256. A checksum mismatch stops the build immediately, and failed transfers leave no usable archive.

Tools images use `ghcr.io/pablovesnine/mhgurecomp-builder:<full-source-SHA>`. The publisher checks master, image identity, platform and source labels without executing candidate code. Public images need no registry login. If publication fails after master has advanced, retry publication for the same validated SHA rather than rolling back source history.

To run **Publish a validated master tools image** manually, use the source SHA, image ID, artifact name and run ID from the builder summary. The transport artifact lasts one day. If it has expired, a manual master CI run can rebuild, validate and publish. After a successful manual recovery, close issue #2. A no-op sync deliberately leaves an unresolved publication warning open.

Read/write Git/API work, read-only candidate execution and package publication run in separate jobs. Automation uses short-lived GITHUB_TOKEN credentials. Never add a personal token as a permanent secret.

## GitHub settings

Keep Actions and Issues enabled when requesting validation. These workflows have no schedules and do not run on pushes or PRs; I do not use keepalive commits. The GHCR package must stay public and accessible to this repository's Actions. Dependency update PRs stay open for review and are separate from upstream sync. I check account usage before a manual run; repository workflow settings do not establish the cause or cost of an account-level usage warning.

## Local build and privacy

Follow the public commands in the [README](../README.md#build), using `tools/build-linux-release.sh` and your own dump path. Update a clean master checkout with `git pull --ff-only origin master`. Do not reset local changes or clear ignored caches just to update. Keep personal convenience scripts outside the checkout and out of Git. The public wrapper exports tracked HEAD, not unrelated working files.

Building locally does not require Actions. If the exact public tools image is unavailable, the wrapper builds tools locally from tracked HEAD. This does not grant publication approval: the public release publisher still requires successful full exact-source validation and verified GHCR image provenance.

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

Generation records `gen.id` from the normalized generator sources only after both SDK and main generation succeed. Starting generation removes any older stamp, so a failed attempt cannot look current. `make check-generated` rejects absent or stale stamps before `make dist`; the Docker entrypoint also runs `check-generated` before recording metadata and packaging, because the public wrapper calls `tools/dist.py` directly. After generator changes, regenerate from the local dump instead of copying an old stamp.

The project's license does not authorize redistribution of game-derived code. Keep licenses and required third-party sources intact.

## ARM64 compatibility

The signed-char and 64-GiB guest-base corrections follow the ARM64 approach in [cerroverb's 0.14.0.1 source](https://github.com/cerroverb/MHGURecomp/tree/267c2be968128bf0d9d2dbd82b2e4e35e71ef6b6). The guest window remains 4 GiB. This fork already had the BC fallback, ARM64 glibc wrappers and cross-compiler test controls. I kept those implementations instead of adding duplicates. These are compatibility changes, not measured FPS or build-speed improvements.
