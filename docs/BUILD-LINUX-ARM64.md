# ARM64 device requirements and troubleshooting

For build instructions, see the [README](../README.md#build). The package needs an ARM64 Linux userspace, glibc 2.39 or newer, a desktop session and Vulkan 1.2 with the renderer's required features. Build checks verify ELF64 AArch64 and imported symbol ceilings of GLIBC 2.39 and GLIBCXX 3.4.32. They do not check GPU compatibility.

## Install and test

Back up your saves before installing. Extract the package into a new directory on your device, then place your own `exefs/` and `romfs/` under `data/` beside the executable. Run it from a terminal before trying a Steam shortcut:

```bash
./mhgurecomp 2> startup.log
```

In Steam, select the executable directly without a compatibility layer. Check graphics, audio, controls, settings and saving/loading. Open settings with F1 or Minus + Plus. The [settings guide](SETTINGS_UI.md) explains navigation, saving and which options need a restart.

Game files, settings, mods and caches normally live beside the executable. Saves normally use `$XDG_DATA_HOME/MHGURecomp/save/`, or `~/.local/share/MHGURecomp/save/` by default. For a separate test profile, extract a fresh copy and run:

```bash
XDG_DATA_HOME="$PWD/test-profile" ./mhgurecomp
```

## Failures

- **Exec format error:** run the package on the ARM64 device.
- **Loader or symbol version missing:** check your device's userspace. Do not replace system libraries manually.
- **Vulkan error:** keep the exact message, GPU and driver version. A matching Vulkan version does not mean the GPU supports every required feature.
- **Address reservation failure:** keep the kernel and error details. Do not disable system security features to guess at a fix.
- **Mod-only failure:** try to reproduce it in a fresh installation without mods.

When reporting a problem in this repository's Issues, include the version and full source SHA. For a downloaded package, copy `source_revision` from `build-metadata.json`. For a source build, run `git rev-parse HEAD` in the build checkout. Also include your device, distribution, GPU/driver and a log with private information removed. Never attach game libraries, dumps, generated code, caches, saves or playable archives.
