# MHGU Recomp - Linux ARM64

Linux ARM64 adaptation of [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp). Running the game requires your own complete **MHGU 1.4.0** dump.

## AI Usage Disclosure

I use an AI coding agent to help adapt upstream code for Linux ARM64 and maintain this fork. Automated build and public runtime tests do not replace device testing; my device observations are described below. I have not tested every inherited feature, controller or mod on ARM64.

## Included upstream features

These features come from upstream; this fork adapts the build and runtime for ARM64 Linux. Availability in the code is not a compatibility guarantee for every device or mod.

- Graphics settings (resolution, MSAA, FXAA, Supersampling, VSync)
- 16:10, 16:9 and ultrawide aspect ratios; windows narrower than 16:10 are letterboxed
- Configurable frame-rate cap from 30 to 240 FPS; actual performance depends on hardware and settings
- SDL-compatible controllers and experimental, remappable keyboard/mouse controls
- Optional small-monster synchronization in multiplayer, off by default; upstream notes a possible issue with small monsters not attacking
- Optional: monster HP scaling by playercount
- Speed up village/hub event-camera pans by pressing A
- Optional: village quests are playable in multiplayer (press L/R at the quest counter), with appropriately re-scaled monster HP
- Mod overlays, archive merging, exefs patches and Forge plugins, with mod-dependent compatibility (see [Mods](#mods))
- Cheat codes in the same format as Ryujinx and Atmosphère, in the `cheats` folder (see [Cheats](#cheats))
- Ingame PC Settings menu overlay (F1 or `Plus`+`Minus` to open)
- Internet hubs through the default or a custom compatible server, plus LAN/direct play (use "Local Wireless")
- Discord Rich Presence (optional)

## Download

I publish my ARM64 builds in [Releases](https://github.com/pablovesnine/MHGURecomp/releases/tag/0.13.1). Download a package and follow [Install](#install), cloning is not required. To build your own package instead, follow the steps on [Build](#build).

The device needs an ARM64 Linux userspace, glibc 2.39 or newer, a compatible C++ runtime, a desktop session and the renderer's required Vulkan features. See [device requirements](docs/BUILD-LINUX-ARM64.md); a Vulkan version string alone does not establish compatibility.

## Screenshots

I tested this release on **AYN Odin 3** with [ArmadaOS 20261010](https://github.com/armada-os/armada): I observed **~120 FPS in Eco mode**, working online multiplayer and morerokk's custom settings menu. These are my observations on that setup, not a performance guarantee for other devices or settings.

![MHGU gameplay on AYN Odin 3](docs/screenshots/ayn-odin3-gameplay.jpg) ![Online multiplayer lobby list](docs/screenshots/ayn-odin3-online.jpg) ![morerokk's custom settings menu](docs/screenshots/ayn-odin3-menu.jpg)

## Settings

Everything is in `mhgurecomp.ini`, each setting is explained in the file itself. The settings menu changes them in the game: **F1**, or **Minus + Plus** on a controller (Back + Start on an Xbox controller). Frame rate, FOV, draw distance, anti-aliasing, VSync, controls and volume apply when you save; the settings marked * at the next start. Details: [docs/SETTINGS_UI.md](docs/SETTINGS_UI.md). In short:

- `[Display]`: `Mode` (Borderless / Fullscreen / Windowed), `Resolution`, `RenderResolution` (the 3D resolution), `AspectRatio` (16:10 and wider fill the window; narrower windows have bars), `FOV` (1.0 = the game's), `UIAnchor` (Center, 21:9, 32:9 or Edges)
- `[Anti-aliasing]`: `MSAA` (Off / 2x / 4x / 8x), `FXAA` (On / Off), `FXAAMode` (Original / 3_11: FXAA 3.11 in place of GU's FXAA, sharper textures; default Original)
- `[Upscaler]`: FSR 3.1 temporal upscaling, default Off, with NativeAA / Quality / Balanced / Performance / UltraPerformance modes, sharpness and motion/reactive controls. These settings need a restart. FSR replaces MSAA and FXAA and needs additional GPU capabilities; it is not a frame-generation option. See [FSR](docs/SETTINGS_UI.md#fsr).
- `[Graphics]`: `DrawDistance` (how far away people in the villages and the Hubs are still drawn: 1 = the game's, 2 = twice as far, 0.5 = half, 0 = no limit; up to 10)
- `[Performance]`: `FPS` (30 to 240), `VSync`, `ShowFPS` and `ShaderPrewarm`. Background shader/pipeline preparation reduces first-use missing draws and stutter; remaining combinations are prepared on demand. The supplied `pipelines.list` covers common areas with MSAA Off. Preparation time and cache size vary with hardware, driver and settings.
- `[Controls]`: `FaceButtons` (Position / Label), `MenuConfirm` (host settings confirmations only), `BackgroundInput` and `ComboInputWindow` (Lenient / Strict). In-game confirmation buttons are not remapped by `MenuConfirm`. See [host confirmation](docs/SETTINGS_UI.md#host-confirmation-button).
- `[Mouse]`: `MouseSensitivity` (1 = default, 0.1 to 10)
- `[Multiplayer]`: `Port` and `Join` for direct play, `Server` and `Key` for internet hubs, `SyncSmallMonsters` and `ShareUrgentCredit` (default On: clearing another hunter's Urgent quest counts for you if you have unlocked it).
- `[Monster HP]`: HP factors for 1 to 4 hunters in Hub quests, and per-quest exceptions (default: all 1, the original game)
- `[Village Quests]`: `VillageQuestsInHub` (default On), `HubHP` (default 2.0: Village quests posted in the Hub multiply their monsters' HP by this first, then by the `[Monster HP]` factor)
- `[Discord]`: optional `RichPresence` and `ShowHunter`. This needs a compatible local Discord IPC client; availability depends on the client and device environment.
- `[Bonus Content]`: `BonusContent` (default On), see below
- `[Audio]`: `Volume` (0 to 100: the whole game), `MuteInBackground` (On / Off, default Off: no sound while the game's window is in the background)
- `[Application]`: `ConfirmExit`, `Language` (English / Spanish), `ButtonIcons` (Xbox / Switch / PlayStation), `Theme` (Hunter / Gold / Blue) and `MenuScale` (50–200%). Menu Options offers Detach menu, Move menu and Attach menu for placement. The inherited `Updates` setting is retained for compatibility and does not download or install updates, despite the inherited INI help; see [Manual updates](#manual-updates).

### Controls

- SDL controllers use face-button position by default; **Controls > Face buttons** switches to labels. The most recently used connected controller supplies game input.
- **Controls > Keybinds** remaps keyboard/mouse actions, with up to two bindings per action. Defaults include WASD movement, Left Shift to walk, mouse movement for the camera, Space for B, left mouse for X and right mouse for A.
- Click the window to capture the mouse; Escape releases it. The mouse wheel changes the selected item without holding L.
- F11 or Alt+Enter toggles fullscreen. F12 saves a screenshot in `shots/`. F1 or Minus + Plus opens the host settings menu; Insert opens Forge separately.

### Multiplayer

Choose the game's **Local Wireless** options. The client replaces local wireless transport with IP networking; the game's original online service is not used.

**Custom servers are supported.** Open **Network > Hub server**, or set `[Multiplayer] Server` in `mhgurecomp.ini`: empty uses morerokk's default public hub, `Off` disables it, and `hostname[:port]` selects a compatible custom hub (default hub port **39510**). Use **Matchmaking key** to separate a group's listings and **Check hub server** to check the draft address/key. Save changes before searching or joining; these two settings do not require a restart. All players who want the same internet listings need the same server and key.

The hub relays internet connections, so players do not need to forward game ports. LAN discovery and direct hosts are separate: **Search hosts** / `Join` accepts direct host addresses, and **Host port** / `Port` defaults to **39500 TCP/UDP**. Direct internet play without a hub requires that host port to be reachable. An unreachable hub leaves LAN and configured direct-host discovery available.

I do not include a dedicated hub server or its executable in this fork or package. Connecting to a custom hub does not require bundling the server. See [custom hub configuration and separate server hosting](docs/SETTINGS_UI.md#custom-hub-server) for an INI example, restart rules and the upstream server instructions.

### Bonus content

The ARM64 package contains an empty `bonus/` directory; I do not include a bonus save. Optionally place your own compatible donor `system` file containing downloaded content at `bonus/system`. With `BonusContent = On`, eligible existing saves without downloaded content can receive it when opened. Saves that already contain downloaded content are left alone; this is not tied to an exact startup count.

Back up saves before using a donor. Without a donor, no downloaded content is added. Set `BonusContent = Off` to disable filling regardless of donor location.

### Mods

To install a mod, put its folder in `mods/` and restart. Mods are layered over the game at startup; compatibility depends on the mod, its patches/plugins and the renderer.

- Romfs overlays support the `atmosphere/contents/0100770008DD8000/romfs` layout inside a mod.
- Archive merging combines different changed entries of an archive such as `resident_eng.arc`; when two mods change the same entry, later load order wins. Merged archives live in `cache/arcmerge/`.
- Without an order file, mods load alphabetically. A hand-written `mods/load_order.txt` lists only the mods to load. The **Mods** tab manages enabled/disabled entries and order, also admitting newly added mods unless disabled. It offers conflict review and a suggested order; Save, then restart.
- Exefs `.pchtxt`, IPS and IPS32 patches and mod code modules are supported. Patched functions and extra code modules may run in the interpreter; inspect `[mods]` diagnostics rather than assuming every patch is compatible.
- Forge `.nro` plugins are loaded from a mod's `romfs/nativeNX/plugins/`. The port handles the recognized Forge loader itself. Insert opens the Forge menu; mod configuration can select another key. Forge compatibility is plugin-dependent; check `[forge]` diagnostics.
- Resolution settings, FPS caps and hub connectivity are already provided by the port; do not assume an emulator-specific fix mod is needed.

Upstream recommends [Key Quest Markers](https://gamebanana.com/mods/727960) by PurplefinNeptuna for marking progression quests in the quest menu. Check each mod against your game version and back up saves before testing it.

**Good places to get mods:**

- [The MHGURecomp-Mods repo](https://github.com/Oddity-git/MHGURecomp-mods)
- [GameBanana](https://gamebanana.com/mods/games/17088)

### Cheats

Put `.txt` files with MHGU **1.4.0** cheat codes in `cheats/`. The interpreter supports Atmosphère/Ryujinx-style codes, but this is not a guarantee for every code; check the log and back up saves. A file can hold multiple cheats, each starting with its name in square brackets:

```
[Skill points x2]
04000000 000DFAB4 E1A00080
```

- Turn cheats on and off in the **Cheats** tab, then Save. The selection persists in `cheats/_off.txt`. Turning a code off restores its code patches, not values already changed in the save. Master codes (`{Name}`) stay active.
- New files in `cheats/` require a restart. **Add a cheat** writes to `cheats/added.txt` and applies immediately. Online, use cheats only when everyone in the lobby agrees.
- To turn off a file without deleting it, start its name with `_`.
- Cheats that patch game code can route affected functions through the interpreter and reduce performance.
- Diagnostics in `log.txt` or the terminal list loaded cheats and files that could not be read.

I do not include sample cheat files in the source or package.

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

   The dump must contain `exefs/main` and `exefs/sdk` from your own MHGU 1.4.0 update, plus the base game's complete `romfs/` with the update merged over it. An update-only romfs is incomplete.

4. After a successful build, verify the package:

   ```bash
   (cd dist && sha256sum --check SHA256SUMS)
   ```

Output: `dist/LinuxARM64-MHGURecomp.<version>.tar.gz` and `dist/SHA256SUMS`. The version is the stable upstream release pinned in this checkout. Inspect it with `bash tools/upstream-version.sh`. Release builds need network access to verify upstream tags and full Git history.

## Install

Extract into a new directory on your compatible ARM64 Linux device. Copy your complete 1.4.0 dump's `exefs/` and merged `romfs/` into `data/`, then run `./mhgurecomp`. The release contains no dump or bonus donor save. You can add `mhgurecomp` to Steam as a non-Steam game without a compatibility layer; I have used this on ArmadaOS.

### Files and saves

- Settings: `mhgurecomp.ini`, generated beside the executable on first start.
- Mods, cheats, screenshots and shader caches: `mods/`, `cheats/`, `shots/` and `cache/` beside the executable in the normal standalone layout.
- Saves: `$XDG_DATA_HOME/MHGURecomp/save/`, or `~/.local/share/MHGURecomp/save/` by default. Custom environment overrides can change the normal locations.
- To import your own save, close the game, back up the destination and copy `system` and `system_backup` into the save directory's `save_0/`. Keep a backup before using mods, cheats or bonus donors.
- Diagnostics: `log.txt` for non-terminal launches, or terminal output when started interactively. Do not publish saves, dumps or unredacted logs.

## Manual updates

I do not build or ship a binary updater. The inherited **Updates** option and its INI help do not enable automatic updating. Download an ARM64 package from this fork's Releases page, back up saves and extract it into a new directory. Reuse your own game files and copy only the settings/mods you want to retain. Save data normally remains in the user-data location above, separate from the extraction directory.

## Maintenance

Published stable upstream releases are checked every six hours. Compatible releases enter `master` only after full ARM64 validation. Normal fork edits run quick checks; full Docker/QEMU validation is otherwise manual.

[Maintenance](docs/MAINTAINING.md) · [Device requirements and troubleshooting](docs/BUILD-LINUX-ARM64.md) · [Settings](docs/SETTINGS_UI.md)

## License

[MIT](LICENSE), with [third-party notices](THIRD_PARTY_NOTICES). Game files and recompiled game code are not covered by this license. Not affiliated with Capcom or Nintendo.
