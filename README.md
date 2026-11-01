# MHGU Recomp — Linux ARM64 fork

This fork of [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp)
focuses on **Linux ARM64**, including handhelds running a desktop Linux
distribution. It keeps the original recompiler and runtime, with a Docker
cross-build, ARM64 checks and automated upstream-update proposals maintained
here. The upstream project is not responsible for this fork's ARM64 support.

**No game files, keys or playable downloads are provided.** You need your own
complete Monster Hunter Generations Ultimate 1.4.0 dump. The local build
recompiles its code into `mhgugame.so`; that library is game-derived and must
stay private along with your dump and generated sources.

## Supported setup

| Role | Supported environment |
| --- | --- |
| Build host | x86_64 Linux with Docker Engine and a local Unix-socket daemon |
| Tools container | x86_64 Ubuntu 24.04; cross-compiles for AArch64 |
| Target device | 64-bit AArch64 Linux with glibc 2.39 or newer and a compatible Vulkan driver |
| Game | Monster Hunter Generations Ultimate, Switch version 1.4.0 |

The runtime needs a Vulkan 1.2-capable GPU **and the renderer's required
features**, a suitable desktop session and sufficient guest virtual address
space. A Vulkan version number or an ARM64 CPU alone does not establish
device compatibility. This is not an Android APK or a Windows build, and
native compilation on the handheld is not a supported workflow.

Earlier Docker builds were contributor-tested on 0.12.0, with execution on
an Ayn Odin 3 running ArmadaOS through Steam. That is historical validation,
not a claim that the current source has been tested on the device.
[ARM64 compatibility and troubleshooting](docs/BUILD-LINUX-ARM64.md) explains
what CI can check and what still needs a private device test.

## Build with Docker

Install Docker using its [Linux installation guide](https://docs.docker.com/engine/install/).
Configure [rootless Docker](https://docs.docker.com/engine/security/rootless/)
or [normal-user access](https://docs.docker.com/engine/install/linux-postinstall/);
membership of the `docker` group grants root-level privileges. Run the
commands below as your normal user, not with `sudo`.

The host also needs Git, Bash, `tar`, `flock`, `realpath` and `sha256sum`.
Allow at least 20 GB of working space in addition to the dump and the final
device installation; this is a starting budget, not a measured upper bound.
The first build also needs internet access for public tools and dependencies.

```bash
git clone https://github.com/pablovesnine/MHGURecomp.git
cd MHGURecomp
docker info

bash tools/build-linux-release.sh --game "/absolute/path/to/your/dump" \
  --version 0.13.0 --jobs 2

(cd dist && sha256sum -c SHA256SUMS)
```

The dump directory must contain `exefs/main`, `exefs/sdk` and the complete
updated `romfs/`, not just the base game or the title update on its own.
The expected `main` build ID begins `FB08F1D20FD1204F`; the title ID is
`0100770008DD8000`. This repository does not explain how to obtain a dump.

The script tries the tools image for the checkout's full commit SHA at
`ghcr.io/pablovesnine/mhgurecomp-builder`. If it is unavailable, the script
builds that commit's tools locally. There is no dependency on a mutable
`latest` tag and no need to upload your dump or log in for a public image.
To force a local tools rebuild, add `--rebuild-image`.

The source snapshot comes from **tracked files at `HEAD`**, not uncommitted
edits or untracked files in the checkout. Commit intended changes before
using this release workflow. The `--version` value labels the local build;
it does not fetch or select an upstream release.

One successful build produces:

```text
dist/
  LinuxARM64-MHGURecomp.0.13.0.tar.gz
  SHA256SUMS
```

The archive contains the ARM64 runtime, your locally recompiled game
library, licenses, pipeline data and build metadata. It does not contain
the raw dump, saves, mods, caches or an updater. Keep the archive private:
excluding the raw dump does not make `mhgugame.so` distributable.

### Install on the ARM64 device

Back up existing saves before testing a new build. Extract the archive into
a new directory on the **ARM64 device**, then put your own `exefs/` and
`romfs/` inside its `data/` directory:

```text
LinuxARM64-MHGURecomp/
  mhgurecomp
  mhgugame.so
  licenses/
  pipelines.list
  data/
    exefs/
      main
      sdk
      ...
    romfs/
      nativeNX/
      ...
```

Run `./mhgurecomp` on that device. If adding it to Steam as a non-Steam game,
select the executable directly; it is a native Linux program, not a Proton
or Windows executable. Check graphics, audio, controls and save/load before
reusing a profile you care about.

| Data | Default location |
| --- | --- |
| Game files | `data/exefs/` and `data/romfs/` beside the executable |
| Settings, mods, cheats and caches | Beside the executable |
| Saves | `$XDG_DATA_HOME/MHGURecomp/save/`, or `~/.local/share/MHGURecomp/save/` |
| Log | Terminal stderr; `log.txt` beside the executable when launched without a terminal |
| Screenshots | `shots/` beside the executable |

The settings menu opens with **F1** or **Minus + Plus** on a controller.
See [settings documentation](docs/SETTINGS_UI.md) for the available controls.
Mods go in `mods/`, cheat files in `cheats/`; try a clean profile before
reporting a problem with either enabled. The optional multiplayer hub
remains documented in [server/README.md](server/README.md); it is not part of
the Docker build.

### Update a local build

```bash
git switch master
git pull --ff-only
bash tools/build-linux-release.sh --game "/absolute/path/to/your/dump" \
  --version 0.13.0 --jobs 2
```

Choose the appropriate local version label, verify `SHA256SUMS`, and install
into a new directory before migrating settings. This fork does **not**
ship or run `mhgurecomp-updater`, and does not download upstream game
packages. Any inherited `Updates` setting has no effect without that program.
Source updates are proposed by Actions and merged by the fork maintainer.

## Public checks and automation

You can run the public ARM64 build checks without a game dump:

```bash
bash tools/build-linux-release.sh --check --version 0 --jobs 2
```

GitHub Actions runs these checks on code changes and upstream-update
candidates. They compile public runtime code and run small ARM64 tests under
QEMU; they do not build a game library, launch the game or exercise a GPU.
After `master` passes, a separate job publishes the **tested tools image**,
not a playable package.

Upstream is checked every six hours and on demand. Changes become a PR in
this fork, with validation tied to the candidate commit. Conflicts require
manual resolution, and even a green PR is not merged automatically.
`master` is the only permanent product branch; bot and dependency-update
branches are temporary.

See [Maintaining this fork](docs/MAINTAINING.md) for first-time Actions/GHCR
activation, permissions, sync failures and manual recovery.

## Privacy, caches and build failures

Your dump is mounted read-only in a **local** build container, never copied
into a Docker image or sent to Actions/GHCR. However, the ignored
`.linux-release/` cache contains private generated game code after a full
build. Do not upload it, `dist/`, saves or an entire build directory when
asking for help.

Only local Docker Unix-socket contexts are supported. The wrapper maps host
UID/GID and supplementary groups for rootful Docker; rootless Docker uses
its normal mapping. On SELinux hosts, `:Z` labels work/output mounts and
`:ro,z` labels the read-only dump mount. These options relabel the selected
directories, so use a dedicated dump directory, not your home directory.
The build neither disables SELinux nor requests privileged containers.

Spaces in checkout and dump paths are supported; colons and newlines are
not. Use one build at a time per checkout. A failed build can leave an older
archive in `dist/`; only a successful command and a fresh hash check establish
that the requested build finished. Existing `build-arm64/` and `obj-arm64/`
directories are not used by this workflow.

Report fork-specific failures in
[this fork's Issues](https://github.com/pablovesnine/MHGURecomp/issues) with
the full source SHA, host/device distro, GPU/driver and a redacted log.
Do not direct ARM64 support requests to the upstream maintainer.

## Source and attribution

The original project is [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp).
It statically recompiles the game's 32-bit ARM code to C and supplies a host
runtime for Switch services and the NVN graphics API using Vulkan.
This fork preserves that work and its upstream history.

`tools/` contains the recompiler and build/maintenance tools; `runtime/`
contains the host runtime; `tests/` holds public regression tests.
`updater/sha256.c` and its header remain because networking uses SHA256;
the retained updater/platform sources are not supported build products.
Other technical documents describe inherited code and research, not
additional supported platforms.

MHGU Recomp's own code is under the [MIT License](LICENSE). It builds on LAS
Recomp and Forge and includes cimgui/Dear ImGui, FidelityFX and FSR-Vulkan;
retain [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES) and all bundled dependency
licenses. This license does not cover the game or its recompiled code.

This project is not affiliated with or endorsed by Capcom or Nintendo.
Monster Hunter is a trademark of Capcom. Support the developers by owning
the game.
