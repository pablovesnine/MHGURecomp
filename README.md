# MHGU Recomp - Linux ARM64

Linux ARM64 adaptation of [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp). Build locally with Docker and your own complete **MHGU 1.4.0** dump.

## Build

Docker must already work as your normal user (`docker info`). Run on your Linux build PC, not on the handheld.

```bash
git clone https://github.com/pablovesnine/MHGURecomp.git
cd MHGURecomp
bash update-build-arm64.sh --repo-dir "$PWD" \
  --game "/absolute/path/to/MHGU dump/"
```

The script updates this fork's `master`, builds with Docker and verifies the archive checksum. It never installs packages or uploads your dump. The dump must contain `exefs/main`, `exefs/sdk` and the complete `romfs/`. Use a dedicated dump directory: Docker adjusts its SELinux labels.

Output: `dist/LinuxARM64-MHGURecomp.<build>.tar.gz` and `dist/SHA256SUMS`. The default build label is a UTC timestamp; the source commit is recorded inside the archive.

## Install

Extract into a new directory on your ARM64 device. Copy your dump's `exefs/` and `romfs/` into its `data/` directory, then run `./mhgurecomp`. Back up saves before testing an update.

Keep the archive, dump and `.linux-release/` private: the build contains game-derived code. Do not upload them to GitHub.

## Maintenance

Upstream is checked every six hours. Compatible changes enter `master` automatically only after public ARM64 checks pass. Fork build rules and
retired files are protected. Unexpected conflicts produce one tracking issue. Only `master` is permanent. CI never receives game files.

[Maintenance](docs/MAINTAINING.md) ·
[Device requirements and troubleshooting](docs/BUILD-LINUX-ARM64.md) ·
[Settings](docs/SETTINGS_UI.md)

## License

[MIT](LICENSE), with [third-party notices](THIRD_PARTY_NOTICES). Game files and recompiled game code are not covered by this license. Not affiliated with Capcom or Nintendo.
