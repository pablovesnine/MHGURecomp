# Native engine modules on Linux ARM64

Upstream 0.14.3 adds optional native engine modules. These extend the host recomp runtime, not the original AArch32 game. They are separate from `mods/`, exefs patches and Forge `.nro` plugins. I do not include or enable native modules in the ARM64 package.

## Trust and compatibility

A module is arbitrary native code with your user's permissions. The loader is not a sandbox. Only use modules whose source and origin you trust. Linux dynamic-library constructors can run during loading, before the loader checks the module API or calls its entry function. A rejected API is not a guarantee that no module code ran.

Use an AArch64 Linux `.so` built for the device's native ABI and compatible system libraries. An x86-64 `.so`, Windows DLL or guest plugin is not interchangeable. Modules that use only the declared engine-module API have the intended version check; runtime symbols outside that API are unstable. Modules with private shared-library dependencies must also arrange their resolution, for example with an appropriate `$ORIGIN` RUNPATH.

## Enable a module

Close the game. Put each trusted module in its own directory beside the executable:

```text
engine_modules/
  enabled.txt
  example/
    example.so
```

Add the folder name, one per line, to `engine_modules/enabled.txt`:

```text
example
```

The loader reads only listed folder names, in order. A missing list loads nothing. Blank lines and `#` comments are accepted; duplicate successful loads are ignored. Folder names must not contain path traversal. A module directory must contain its matching `.so`. Restart after changing the list or replacing a module. Remove its line to disable it on the next start.

Check the `[engine modules]` diagnostics for load failures, API mismatch, missing entry symbols or a declined initialization. Loaded modules remain in the process until exit. Shutdown callbacks are not hot unloading, and a crash does not guarantee clean shutdown.

## Build the public example

On a native AArch64 Linux development machine with Clang and LLD, the internal `make example-engine-module` target builds the public logging example under `obj/engine-module-test/engine_modules/example/`. It does not install or enable it. Cross-compilation must use the same target/sysroot as the runtime; the recipe carries `TARGET_FLAGS` rather than silently building for the compiler host.

For development, use the API header supplied with the same source version. The public `test-engine-modules` target checks opt-in loading, API rejection, missing symbols, declined initialization, unsafe names, duplicates and shutdown without game files. In CI it builds AArch64 executables and libraries and runs the executable with QEMU. The `test-cheats` target also runs without a dump. These checks do not validate an arbitrary third-party module or its GPU behavior.

For the supported game-package build, use the [Linux ARM64 build entry point](../README.md#build). I do not add example modules to that package.
