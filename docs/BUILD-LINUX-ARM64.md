# ARM64 device requirements and troubleshooting

Build instructions are in the [README](../README.md#build). The output requires an ARM64 Linux userspace, glibc 2.39 or newer, a desktop session and Vulkan 1.2 with the renderer's required features. The build checks ELF64 AArch64 and imported symbol ceilings of GLIBC 2.39 and GLIBCXX 3.4.32, not GPU compatibility.

## Install and test

Back up saves. Extract into a new device directory and place your own `exefs/` and `romfs/` under `data/` beside the executable. Run from a terminal before trying a Steam shortcut:

```bash
./mhgurecomp 2> startup.log
```

Select the executable directly in Steam, without a compatibility layer. Check graphics, audio, controls, settings and save/load. Settings open with F1 or Minus + Plus. See the [settings guide](SETTINGS_UI.md) for navigation, saving and restart-only options.

Game files, settings, mods and caches normally live beside the executable. Saves normally use `$XDG_DATA_HOME/MHGURecomp/save/`, falling back to `~/.local/share/MHGURecomp/save/`. For an isolated first test, use a fresh extraction and:

```bash
XDG_DATA_HOME="$PWD/test-profile" ./mhgurecomp
```

## Failures

- **Exec format error:** run the package on the ARM64 device.
- **Loader or symbol version missing:** check the device's userspace; do not replace system libraries manually.
- **Vulkan error:** retain the exact message, GPU and driver version. A Vulkan version string alone does not prove feature compatibility.
- **Address reservation failure:** retain kernel and error details; do not disable system security features speculatively.
- **Mod-only failure:** reproduce with a fresh installation without mods.

Report the version and full source SHA: for a downloaded package, copy `source_revision` from its `build-metadata.json`; for a source build, use `git rev-parse HEAD` in the build checkout. Include the device, distribution, GPU/driver and a redacted log in this repository's Issues. Never attach game libraries, dumps, generated code, caches, saves or playable archives.
