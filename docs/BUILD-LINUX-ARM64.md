# Linux ARM64 compatibility and troubleshooting

The supported build is the [Docker cross-build in the README](../README.md#build-with-docker)
on an x86_64 Linux host. Its output targets AArch64 **Linux with glibc**,
not Android/bionic. Neither native handheld compilation nor manual sysroot
assembly is part of the maintained workflow.

## What is checked

The tools image contains an ARM64 sysroot assembled from signed Ubuntu
packages and host-native compilers. Target headers/libraries and pkg-config
metadata are kept separate from host programs. Before the runtime build,
small C and C++ programs check the compiler, loader and target runtimes;
QEMU runs the ARM64 probes and public regression tests.

The packaged runtime and game library must be ELF64 AArch64. Their imported
symbol versions must not exceed GLIBC 2.39 or GLIBCXX 3.4.32. These checks
do not guarantee compatibility with a device's GPU driver or every library
that it loads. The package hash detects changes against the local checksum;
it is not a signature or independent proof of authenticity.

CI has no game dump and cannot compile `mhgugame.so`, run a hunt, exercise
the renderer or establish multiplayer/save compatibility.

## Device requirements

Use a 64-bit Linux userspace, glibc 2.39 or newer, a desktop session and a
Vulkan driver providing the renderer's required features. The runtime also
reserves a guest virtual-address window; kernel address-space configuration
can therefore matter even on a 64-bit CPU.

If startup fails, record the full build SHA, distribution/kernel, device,
GPU and driver, then capture terminal output:

```bash
./mhgurecomp 2> startup.log
```

Inspect `startup.log` before sharing it and remove personal paths, names,
network addresses and other private details. Do not attach your dump,
game library, generated C, caches or saves.

- **Exec format error:** confirm that this is running on the ARM64 device,
  not the x86_64 build host. The archive is not an Android APK.
- **Missing loader or GLIBC/GLIBCXX version:** compare the device's userspace
  with the requirements. Do not copy libraries into system directories to
  work around an incompatible distribution.
- **Vulkan feature/device error:** capture the exact renderer message and
  driver details. A Vulkan version string alone is not a compatibility test.
- **Guest address reservation failure:** preserve the error and kernel
  details. Do not disable system security features speculatively.
- **Only a modded profile fails:** reproduce in a new installation/profile
  without mods or cheats before attributing it to the ARM64 port.
- **Steam-only problem:** first launch the executable from a terminal.
  Do not enable Proton for this native Linux program.

## Private first-run test

Extract into a new device directory and place your dump in `data/` beside
the executable. To keep settings/caches and saves apart from an existing
installation, start from the extracted directory with a fresh profile:

```bash
test_root="$HOME/.local/share/mhgurecomp-arm64-test"
mkdir -p "$test_root/home" "$test_root/xdg-data"
MHGU_HOME="$test_root/home" XDG_DATA_HOME="$test_root/xdg-data" ./mhgurecomp
```

Choose a new `test_root` for an independent profile. `MHGU_HOME` changes
settings, logs, mods and cache locations; it does **not** relocate saves.
`XDG_DATA_HOME` controls the separate save-data base. With `MHGU_HOME` set,
the default game-data lookup still uses `data/` beside the executable.

Check title/menu rendering, a hunt, audio, controller input, save/load and
repeated launches. Test multiplayer separately; do not infer it from a
successful single-player launch. Back up saves before migrating a profile.

## Validation history

The earlier manual cross-build recipe was tested on 0.11.8 and included
a contributor-confirmed Odin 3 launch. Later Docker builds were tested on
0.12.0, including an Ayn Odin 3 running ArmadaOS through Steam. Neither was
a controlled performance study or exhaustive long-duration compatibility
test.

The 0.13.0 integration and this fork restructuring do not, by themselves,
constitute another complete game build or device test. A successful current
Actions run establishes only the public-code checks at its recorded SHA.
Native ARM64 compilation and the inherited Windows/Android entry points
are not supported or validated by this fork.
