# MHGU Recomp - Linux ARM64

My Linux ARM64 adaptation of [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp). Running the game requires your own complete **MHGU 1.4.0** dump.

## Download

I publish my ARM64 builds in [Releases](https://github.com/pablovesnine/MHGURecomp/releases/tag/0.13.1). Download a package and follow [Install](#install), cloning is not required. To build your own package instead, follow the steps below.

## Screenshots

I tested this release on **AYN Odin 3** with [ArmadaOS 20261010](https://github.com/armada-os/armada): running at **~120 FPS in Eco mode**, working online multiplayer, and morerokk's custom menu with all its features working.

![MHGU gameplay on AYN Odin 3](docs/screenshots/ayn-odin3-gameplay.jpg) ![Online multiplayer lobby list](docs/screenshots/ayn-odin3-online.jpg) ![morerokk's custom settings menu](docs/screenshots/ayn-odin3-menu.jpg)

## Build

Build on a **Linux x86-64 PC** with Git and working local Docker, the output is for **ARM64** only. For an x86-64 build, please refer to [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp).

1. Check the prerequisites:

   ```bash
   git --version
   docker info
   ```

2. Clone this fork:

   ```bash
   git clone --branch master --single-branch https://github.com/pablovesnine/MHGURecomp.git
   cd MHGURecomp
   ```

3. Replace the example path with your dump directory, then build:

   ```bash
   GAME_DIR="/absolute/path/to/MHGU dump/"
   bash tools/build-linux-release.sh --game "$GAME_DIR" --jobs 2
   ```

   The dump must contain `exefs/main`, `exefs/sdk` and the complete `romfs/` from your own MHGU 1.4.0.

4. After a successful build, verify the package:

   ```bash
   (cd dist && sha256sum --check SHA256SUMS)
   ```

Output: `dist/LinuxARM64-MHGURecomp.<version>.tar.gz` and `dist/SHA256SUMS`. The version is the stable upstream release pinned in this checkout. Inspect it with `bash tools/upstream-version.sh`. Release builds need network access to verify upstream tags and full Git history.

## Install

Extract into a new directory on your ARM64 Linux device. Copy your dump's `exefs/` and `romfs/` into its `data/` directory, then run `./mhgurecomp`. Back up saves before testing an update. You can add `mhgurecomp` to Steam as a non-Steam game and it will launch into the game, at least in ArmadaOS.

## Maintenance

Published stable upstream releases are checked every six hours. Compatible releases enter `master` only after full ARM64 validation. Normal fork edits run quick checks; full Docker/QEMU validation is otherwise manual.

[Maintenance](docs/MAINTAINING.md) · [Device requirements and troubleshooting](docs/BUILD-LINUX-ARM64.md) · [Settings](docs/SETTINGS_UI.md)

## License

[MIT](LICENSE), with [third-party notices](THIRD_PARTY_NOTICES). Game files and recompiled game code are not covered by this license. Not affiliated with Capcom or Nintendo.
