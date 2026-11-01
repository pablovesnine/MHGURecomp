# Manual Linux builds

This guide covers native Linux builds and WSL for anyone who wants to manage
the build environment directly. For most users, the recommended starting point
is the Docker workflow in [Build both Linux packages](BUILD-LINUX-DOCKER.md).
The instructions here were moved from the README; the separate
[ARM64 guide](BUILD-LINUX-ARM64.md) goes into more detail on cross-compilation.

Run the commands from the repository root with your own complete MHGU 1.4.0
dump, and check the [source prerequisites](../README.md#building-from-source)
first. If you do not need a native build, the Windows version can also run
under Proton or Wine.

## Native Linux dependencies

On Linux, the Makefile selects `runtime/platform/linux.c` and shares the rest
of the build with the other platforms. The original native recipe was tested
on Gentoo x86-64 with Clang, Wayland, and NVIDIA; that is a historical test,
not a new validation of every distribution.

Start with `make`, `git`, `clang`, `lld`, and Python 3.10 or newer, plus:

- The Vulkan loader and Vulkan headers.
- `curl` and, optionally, `nasm` for the bundled FFmpeg build. A system FFmpeg
  package is not required; see [FFmpeg](../README.md#ffmpeg).
- `cmake` and SDL's desktop development dependencies: X11, Xcursor, Xext,
  Xfixes, Xi, Xrandr, Xss, Xtst, Wayland, wayland-protocols, libxkbcommon,
  libdecor, PipeWire, PulseAudio, ALSA, libudev, and D-Bus.
- VMA 3.4.0. The current checkout already includes `vk_mem_alloc.h` under
  `third_party/vk_mem_alloc/`, so there is no separate download step.
  A distribution package on the compiler's default include path is another
  option. The [ARM64 guide](BUILD-LINUX-ARM64.md#1-host-tools-and-source-prerequisites)
  includes a hash check for the bundled header.
- `zenity` or `kdialog` if you want a dialog for fatal errors. Without either,
  errors still appear in the terminal and `log.txt`.
- zlib headers to compile the updater. At run time it loads `libcurl.so.4`;
  if libcurl is unavailable, it starts the game without checking for updates.

On the first build, the Makefile downloads pinned SDL3 and shaderc sources,
including glslang and SPIRV-Tools, into `third_party/`, verifies their SHA-256
hashes, and links them statically. This lets the result run on distributions
without SDL3, such as Ubuntu 24.04. It still needs glibc, libstdc++, and the
Vulkan loader, while SDL loads the system's desktop and audio libraries at
run time. Allow a few minutes for the first dependency build; configuration
stops if SDL cannot find a required backend (`SDL3_NEED`).

If the system has an SDL3 version at least as new as the bundled one, the game
uses it instead. Check the `[ui] SDL ...` entry in `log.txt` to see which was
selected, or set `MHGU_SDL=bundled` to force the bundled version.

For distribution-style linking, `make SDL3=system SHADERC=system` selects the
system's `libSDL3.so.0` and `libshaderc_shared.so.1`. Those libraries then need
to be installed on the machine that runs the resulting programs.

## Build and run

Replace `../mhgu/game` with the folder containing your `exefs/` and `romfs/`.
The original manual recipe is:

```bash
python3 -m venv tools/venv && tools/venv/bin/pip install -r tools/requirements.txt
make gen GAME=../mhgu/game       # as above: the folder holding exefs/ and romfs/
make -j8 GAME=../mhgu/game
cd build && ./mhgurecomp
```

The resulting `build/` folder contains `mhgurecomp`, the recompiled game
library `mhgugame.so`, and `data/`, with hard links to your game files. Settings,
caches, and `mods/` are written beside the executable unless you set
`MHGU_HOME=<folder>` to put them elsewhere.

Saves are separate: they use `$XDG_DATA_HOME/MHGURecomp/save`, which defaults
to `~/.local/share/MHGURecomp/save`. Windows uses the same layout under
`%APPDATA%`, so transferring a save means copying `save_0`. Back up your saves
before testing either build.

## WSL with Arch Linux

Install Arch Linux in WSL with `wsl --install -d archlinux`, then use your
Windows checkout under `/mnt/c/`. Separate build and object directories keep
the Windows build unchanged. Install the packages below as root inside WSL,
but run the final `make` command as your normal user. Prepare Python and
generate the game code as in the native recipe before building.

```bash
pacman -Syu --needed make git clang lld python cmake vulkan-headers vulkan-icd-loader nasm vulkan-swrast \
    libx11 libxcursor libxext libxfixes libxi libxrandr libxss libxtst wayland wayland-protocols libxkbcommon \
    libdecor pipewire libpulse alsa-lib systemd-libs dbus
make -j16 B=build-linux O=obj-linux     # in the repository, under /mnt/c/...
```

The older recipe copied VMA 3.4.0 from MSYS2. That step is no longer needed
because the header is now included in the checkout; it does not depend on
an Arch VMA package.

To avoid a second copy of your dump, create `build-linux/data/` and link the
game folders into it: use `ln -s /mnt/c/.../exefs build-linux/data/exefs`,
create the equivalent link for `romfs`, then run
`touch build-linux/data/.complete`.

In the original WSLg test, the dzn driver could not create the renderer's
pipeline layouts, so the build needed Mesa's software Vulkan driver, selected
with `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/lvp_icd.json`. Software rendering
was slow. WSLg also could not capture the mouse: clicks still worked as
buttons, but screenshots were black. These are observations from that test,
not a guarantee of how every WSL installation behaves.

## Linux ARM64

`TARGET_ARCH` defaults to the host architecture, either `x86_64` or `aarch64`,
and also accepts the aliases `amd64` and `arm64`. A native ARM64 build uses
the Linux dependencies listed above. Cross-compiling instead requires host
Clang/LLD, LLVM tools, CMake, Python, pkg-config, and the Wayland scanner, plus
an **external AArch64 Linux sysroot** containing the target headers and
libraries. The x86-64 host's `/usr` is not a suitable sysroot.

The detailed [Linux ARM64 guide](BUILD-LINUX-ARM64.md) covers the Fedora
x86-64 recipe, including host packages, Python, VMA, compiler checks, tests,
and device use. It also explains how to prepare an Ubuntu 24.04 ARM64 sysroot
with an optional rootless Podman container. That container only prepares
dependencies; the host Makefile compiles the programs. If you already have
a compatible sysroot, you do not need Podman.

```bash
export ARM_SYSROOT=/absolute/path/to/aarch64-sysroot
export GAME_DUMP=/absolute/path/to/game
python3 -m venv tools/venv
tools/venv/bin/python -m pip install -r tools/requirements.txt
make gen GAME="$GAME_DUMP"
make -j4 JOBS=4 TARGET_ARCH=aarch64 SYSROOT="$ARM_SYSROOT" \
    B=build-arm64 O=obj-arm64 GAME="$GAME_DUMP"
```

Give each architecture and sysroot its own `B` and `O` directories; without
overrides, they remain `build` and `obj`. The two job settings have different
roles: `-j` controls outer Make jobs, while `JOBS` limits each bundled
dependency build, not the total number of processes.

ARM game code defaults to `-march=armv8-a`, while x86-64 retains
`-march=x86-64-v3`. CPU flags contribute to the game-library identity, but the
absolute sysroot path does not. The release ceilings remain glibc 2.39 and
GLIBCXX_3.4.32, which a newer native distribution can exceed.

This is a Linux-with-glibc build, not an Android build. An ARM64 CPU alone is
not enough: the device also needs the renderer's Vulkan features and enough
virtual address space. QEMU regression checks do not test graphics or gameplay,
so test the complete build on the target device before making an ARM64 release.
