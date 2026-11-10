# MHGU Recomp - Linux ARM64

Linux ARM64 adaptation of [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp). Running the game requires your own complete **MHGU 1.4.0** dump.

## AI Usage Disclosure

I use an AI coding agent to help adapt upstream code for Linux ARM64 and maintain this fork. Automated build and public runtime tests help catch problems, but they do not replace testing on a device. My own results are below. I have not tested every inherited feature, controller or mod on ARM64.

## Included upstream features

These features come from upstream. I adapt the build and runtime for ARM64 Linux, but that does not mean every feature works with every device or mod.

- Graphics settings (resolution, MSAA, FXAA, Supersampling, VSync)
- 16:10, 16:9 and ultrawide aspect ratios, with letterboxing for windows narrower than 16:10
- Configurable frame-rate cap from 30 to 240 FPS, with actual performance depending on hardware and settings
- SDL-compatible controllers and experimental, remappable keyboard/mouse controls
- Optional small-monster synchronization in multiplayer. Upstream 0.14.0 restores the default to On and fixes related disconnections and high-FPS monster behavior. Existing explicit Off settings stay Off.
- Experimental native-client lag compensation from 0.16.0, with important lifecycle and peer-trust limits (see [lag compensation](docs/SETTINGS_UI.md#lag-compensation)).
- Optional monster HP scaling by player count, including part HP from 0.15.4
- Speed up village/hub event-camera pans by pressing A
- Optional village quests in multiplayer (press L/R at the quest counter), with adjusted monster HP
- Mod overlays, archive merging, exefs patches and Forge plugins, with mod-dependent compatibility (see [Mods](#mods))
- Cheat codes in the same format as Ryujinx and Atmosphère, in the `cheats` folder (see [Cheats](#cheats))
- Optional native engine modules in upstream 0.14.3, separate from game mods and Forge plugins (see [Engine modules](docs/ENGINE-MODULES.md))
- In-game PC Settings menu overlay (F1 or `Plus`+`Minus` to open)
- Internet hubs through the default or a custom compatible server, plus LAN/direct play (use "Local Wireless")
- Discord Rich Presence (optional)

## Download

I publish my ARM64 builds in [Releases](https://github.com/pablovesnine/MHGURecomp/releases/tag/0.15.4). Download a package and follow [Install](#install), without cloning the repository. If you prefer to build it yourself, follow [Build](#build).

The source transition targets upstream **0.16.0**. Run `bash tools/upstream-version.sh` to check the version pinned in your checkout; newer behavior requires the corresponding source version. The downloadable package remains **0.15.4** until I build and publish a new package with my own dump. The source update alone does not create a playable archive.

Upstream 0.15.0 changes FXAA shaders and the mod interpreter, adds an optional loading/shader indicator and controller access to Forge, adjusts controller rumble updates, and adds up to three extra supply maps to Village quests started from the Hub or Pub. I have not measured its performance or tested those changes on an ARM64 GPU or physical controller. Upstream speedup figures are not measured results for this fork.

Upstream 0.15.1 adds experimental emulator crossplay, optional embedded servers, Mouse4/Mouse5 capture over the keybind dialog, and a smithy-preview adjustment. I keep the new network endpoints disabled by default. The server access controls and connection lifecycle have known limitations; I do not recommend public Internet exposure or treat passphrases as a security boundary. See [experimental crossplay](docs/SETTINGS_UI.md#experimental-emulator-crossplay). Public transport fixtures are not a real emulator, game or device test.

Upstream 0.15.2 adds text spacing and weight controls, parallel mod-archive checks with loading progress, optional HDR output, more 16:10 preview adjustments and a mouse API for mods. I keep HDR off by default. Font mods can need **Fix kerning Off / Bold text On**. I have not tested HDR output or these rendering changes on the device; see [text and HDR](docs/SETTINGS_UI.md#text-and-hdr).

Upstream 0.15.3 adds optional direct UDP between a native hub's host and each player, with relay fallback, and releases monster spawns that wait for skipped Village intros in a session. I keep **Direct connections On** by default: both ends opting in lets a compatible hub server disclose their public IP addresses to each other. Save affects new player links, not existing ones. I have not measured latency, tested hole punching between real routers or reproduced the Village softlock in-game. See [direct connections](docs/SETTINGS_UI.md#direct-connections).

Upstream 0.15.4 shortens selected offline transition waits, extends monster HP factors to part HP, adds mouse control to bow aiming, and changes an ImGui draw-buffer cursor mapping and the renderer's front-face mask representation. I retain the network-session waits. I have not measured loading times or tested bow aiming, part breaks, plugin rendering or the graphics changes in a real hunt on ARM64. See [0.15.4 gameplay settings](docs/SETTINGS_UI.md#offline-transitions-hp-and-mouse-aiming).

Upstream 0.16.0 adds experimental lag compensation for supported melee and bow/bowgun hits, longer chat messages, Prowler item-wheel handling, Better Inputs/Forge binding changes and Village quest-list/text handling. I retain lag compensation On by default, but the source has no report deduplication, authenticated sender-slot binding or session reset; queued reports can still apply after network loss or transition to crossplay. I have not validated real combat, emulator interoperability, plugins, input hardware or the new graphics paths. See [0.16.0 controls and Village changes](docs/SETTINGS_UI.md#0160-controls-chat-and-village-quests).

Your device needs an ARM64 Linux userspace, glibc 2.39 or newer, a compatible C++ runtime and a desktop session. It also needs the Vulkan features required by the renderer, not just a matching version number. See [device requirements](docs/BUILD-LINUX-ARM64.md).

## Screenshots

I tested **0.13.1** on **AYN Odin 3** with [ArmadaOS 20261010](https://github.com/armada-os/armada). I got **~120 FPS in Eco mode**, with online multiplayer and morerokk's custom settings menu working. Those results do not validate 0.14.0, 0.14.3, 0.15.0, 0.15.1, 0.15.2, 0.15.3, 0.15.4 or 0.16.0, or predict performance on other devices.

![MHGU gameplay on AYN Odin 3](docs/screenshots/ayn-odin3-gameplay.jpg) ![Online multiplayer lobby list](docs/screenshots/ayn-odin3-online.jpg) ![morerokk's custom settings menu](docs/screenshots/ayn-odin3-menu.jpg)

## Settings

Settings live in `mhgurecomp.ini`, with explanations in the file. To change them in the game, open the settings menu with **F1** or **Minus + Plus** on a controller (Back + Start on an Xbox controller). Frame rate, FOV, draw distance, anti-aliasing, VSync, controls and volume apply when you save. Settings marked * take effect after a restart. See [docs/SETTINGS_UI.md](docs/SETTINGS_UI.md) for details. The main sections are:

- `[Display]`: `Mode` (Borderless / Fullscreen / Windowed), `Resolution`, `RenderResolution` (the 3D resolution), `AspectRatio` (16:10 and wider fill the window, while narrower windows have bars), `FOV` (1.0 = the game's), `UIAnchor` (Center, 21:9, 32:9 or Edges)
- `[Anti-aliasing]`: `MSAA` (Off / 2x / 4x / 8x), `FXAA` (On / Off), `FXAAMode` (Original by default, or 3_11 for FXAA 3.11 in place of GU's FXAA and sharper textures)
- `[Upscaler]`: FSR 3.1 temporal upscaling, default Off, with NativeAA / Quality / Balanced / Performance / UltraPerformance modes, sharpness and motion/reactive controls. In 0.14.3, sharpness and reactive mask apply on Save; enable, quality, object motion and animated surfaces still need a restart. FSR replaces MSAA and FXAA and needs additional GPU capabilities. It does not generate frames. See [FSR](docs/SETTINGS_UI.md#fsr).
- `[Graphics]`: `DrawDistance` (how far away people in villages and Hubs remain visible: 1 = the game's, 2 = twice as far, 0.5 = half, 0 = no limit, up to 10)
- From 0.15.2, `[Graphics]` also has `FixKerning` (default On) and `BoldText` (default Off on Linux), applied on Save. `[HDR] HDR` defaults to Off and needs an HDR-capable display, compositor and Vulkan surface. I have not validated HDR on a device.
- `[Performance]`: `FPS` (30 to 240), `VSync`, `ShowFPS` and `ShaderPrewarm`. Preparing shaders and pipelines in the background reduces missing draws and stutter on first use. Other combinations are prepared as needed. The supplied `pipelines.list` covers common areas with MSAA Off. Preparation time and cache size depend on your hardware, driver and settings. In 0.15.0, `LoadingIndicator` defaults to On; it is INI-only and needs a restart. See [loading indicator](docs/SETTINGS_UI.md#loading-indicator).
- `[Controls]`: `FaceButtons` (Position / Label), `MenuConfirm` (host settings confirmations only), `BackgroundInput` and `ComboInputWindow` (Lenient / Strict). In-game confirmation buttons are not remapped by `MenuConfirm`. See [host confirmation](docs/SETTINGS_UI.md#host-confirmation-button).
- `[Mouse]`: `MouseSensitivity` (1 = default, 0.1 to 10)
- `[Multiplayer]`: `Port` and `Join` for direct play, `Server` and `Key` for internet hubs, `SyncSmallMonsters` and `ShareUrgentCredit` (default On: clearing another hunter's Urgent quest counts for you if you have unlocked it).
- From 0.15.3, `[Multiplayer] Direct` defaults to On. Turn it Off to keep new native internet-hub links on the relay and avoid opting in to peer IP disclosure. Leave and rejoin to replace existing links.
- From 0.16.0, `[Multiplayer] LagCompensation` defaults to On and applies on Save through **Misc > Lag compensation (experimental)**. This is separate from Direct and does not validate crossplay.
- `[Monster HP]`: HP factors for 1 to 4 hunters in Hub quests, and per-quest exceptions (default: all 1, the original game). From 0.15.4, the factor also applies to part HP; see the timing rules in [0.15.4 gameplay settings](docs/SETTINGS_UI.md#offline-transitions-hp-and-mouse-aiming).
- `[Village Quests]`: `VillageQuestsInHub` (default On), `HubHP` (default 2.0: monsters in Village quests posted in the Hub get this HP multiplier first, then the `[Monster HP]` factor; from 0.15.4 this also scales part HP)
- `[Discord]`: optional `RichPresence` and `ShowHunter`. You need a compatible local Discord IPC client, so availability depends on your client and device environment.
- `[Bonus Content]`: `BonusContent` (default On), see below
- `[Audio]`: `Volume` (0 to 100: the whole game), `MuteInBackground` (On / Off, default Off: no sound while the game's window is in the background)
- `[Application]`: `ConfirmExit`, `Language` (English / Spanish), `ButtonIcons` (Xbox / Switch / PlayStation), `Theme` (Hunter / Gold / Blue) and `MenuScale` (50–200%). Use Detach menu, Move menu and Attach menu in Menu Options to position the panel. The legacy `Updates` key remains readable for compatibility but does not download or install updates. The inactive menu row is removed. See [Manual updates](#manual-updates).

### Controls

- SDL controllers use face-button position by default. Switch to labels in **Controls > Face buttons**. The game takes input from the connected controller you used most recently.
- **Controls > Keybinds** remaps keyboard/mouse actions, with up to two bindings per action. Defaults include WASD movement, Left Shift to walk, mouse movement for the camera, Space for B, left mouse for X and right mouse for A.
- Click the window to capture the mouse, and press Escape to release it. The mouse wheel changes the selected item without holding L.
- F11 or Alt+Enter toggles fullscreen. F12 saves a screenshot in `shots/`. F1 or Minus + Plus opens the host settings menu, while Insert opens Forge separately. In 0.15.0, **Mods > Open the Forge menu** also works with a controller when plugins are available. Cancel or Minus + Plus closes Forge; if it opened over settings, it returns there.

### Multiplayer

Choose **Local Wireless** in the game. The client uses IP networking instead of local wireless, without connecting to the game's original online service.

**You can use a custom server.** Open **Network > Hub server**, or set `[Multiplayer] Server` in `mhgurecomp.ini`. Leave it empty for morerokk's default public hub, use `Off` to disable it, or enter `hostname[:port]` for a compatible custom hub (default hub port **39510**). Use **Matchmaking key** to separate your group's listings and **Check hub server** to check the draft address/key. Save before searching or joining. Neither setting needs a restart, but everyone who wants the same internet listings needs the same server and key.

The hub relays internet connections, so players do not need to forward game ports. For direct play, **Search hosts** / `Join` accepts host addresses, and **Host port** / `Port` defaults to **39500 TCP/UDP**. Direct internet play without a hub needs that host port to be reachable. If the hub is unreachable, LAN discovery and the direct hosts you configured remain available.

Upstream **0.14.3 uses protocol 3** and cannot share hubs with earlier recomp releases. Everyone in a session needs a compatible client. The Linux ARM64 fork keeps upstream's desktop public matchmaking behavior. In 0.14.3, saving Port or Join affects the next host/search operation, not an already active hub.

I do not include a dedicated hub server or its executable in this fork or package. You can connect to a custom hub without those files. See [custom hub configuration and separate server hosting](docs/SETTINGS_UI.md#custom-hub-server) for an INI example, restart rules and upstream hosting instructions.

### Bonus content

The ARM64 package has an empty `bonus/` directory, and I do not include a bonus save. To use this feature, place your own compatible donor `system` file with downloaded content at `bonus/system`. With `BonusContent = On`, eligible existing saves can receive that content when opened, as long as they do not already have downloaded content. Saves that already have it stay unchanged. This does not depend on how many times you have started the game.

Back up saves before using a donor. Without one, the game adds no downloaded content. Set `BonusContent = Off` to disable this feature regardless of where the donor is stored.

### Mods

To install a mod, put its folder in `mods/` and restart. The game loads mod layers at startup, and compatibility depends on the mod, its patches/plugins and the renderer.

- Romfs overlays support the `atmosphere/contents/0100770008DD8000/romfs` layout inside a mod.
- Archive merging combines changes to different entries in archives such as `resident_eng.arc`. Upstream 0.14.0 also supports partial `.arc` overlays that preserve untouched original entries. If two mods change the same entry, the later mod wins. Merged archives live in `cache/arcmerge/`.
- Without an order file, mods load alphabetically. A hand-written `mods/load_order.txt` lists only the mods to load. In the **Mods** tab, you can enable or disable mods, change their order and review conflicts. Newly added mods are included unless you disable them. You can also use the suggested order. Save, then restart.
- The port supports exefs `.pchtxt`, IPS and IPS32 patches and mod code modules. Patched functions and extra modules may run in the interpreter, so check `[mods]` diagnostics rather than assuming every patch works.
- Forge `.nro` plugins load from a mod's `romfs/nativeNX/plugins/`, and the port handles the recognized Forge loader itself. Insert opens the Forge menu, though a mod can configure another key. In 0.15.0, the Mods tab also has **Open the Forge menu** for controller navigation. Compatibility depends on the plugin, so check `[forge]` diagnostics.
- The port already provides resolution settings, FPS caps and hub connectivity. You may not need an emulator-specific fix mod for these.

Upstream recommends [Key Quest Markers](https://gamebanana.com/mods/727960) by PurplefinNeptuna for marking progression quests in the quest menu. Check each mod against your game version and back up saves before testing it.

**Good places to get mods:**

- [The MHGURecomp-Mods repo](https://github.com/Oddity-git/MHGURecomp-mods)
- [GameBanana](https://gamebanana.com/mods/games/17088)

### Cheats

Put `.txt` files with MHGU **1.4.0** cheat codes in `cheats/`. The interpreter supports Atmosphère/Ryujinx-style codes, though not every code is guaranteed to work. Back up saves and check the log when testing them. A file can hold multiple cheats, each starting with its name in square brackets:

```
[Skill points x2]
04000000 000DFAB4 E1A00080
```

- Turn cheats on and off in the **Cheats** tab, then Save. Your selection is stored in `cheats/_off.txt`. Turning a code off undoes its code patches, but not values it already changed in the save. Master codes (`{Name}`) stay active.
- In 0.14.3, close and reopen the settings menu to rescan files added, changed or removed in `cheats/`, then Save your selection. Earlier packages need a restart for new files. **Add a cheat** writes to `cheats/added.txt` and applies immediately. Online, use cheats only when everyone in the lobby agrees.
- To turn off a file without deleting it, start its name with `_`.
- Cheats that patch game code can route affected functions through the interpreter and reduce performance.
- Diagnostics in `log.txt` or the terminal list loaded cheats and files that could not be read.

I do not include sample cheat files in the source or package.

## Build

Build on a **Linux x86-64 PC** with Git and a working local Docker installation. The output is for **ARM64** only. For an x86-64 build, use [morerokk/MHGURecomp](https://github.com/morerokk/MHGURecomp).

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

The build creates `dist/LinuxARM64-MHGURecomp.<version>.tar.gz` and `dist/SHA256SUMS`. It uses the stable upstream version pinned in this checkout, which you can check with `bash tools/upstream-version.sh`. Release builds need full Git history and network access to verify upstream tags.

To build and publish from my clean, current master checkout, I authenticate with GitHub CLI and add `--publish`. This also needs Docker buildx and host `llvm-objdump`:

```bash
gh auth login
bash tools/build-linux-release.sh --game "$GAME_DIR" --jobs 2 --publish
```

Publication requires full ARM64 validation and a verified tools image for the exact source SHA. The dump stays local. The command uploads only the checked package and `SHA256SUMS`. It does not replace an existing release with different content. See [publication checks and recovery](docs/MAINTAINING.md#local-build-and-privacy).

To publish an already successful build from `dist` without compiling again, I use the standalone publisher with the same clean source checkout and verified package metadata. GitHub CLI authentication, Docker buildx and host `llvm-objdump` are still required:

```bash
python3 tools/publish-linux-release.py --dist dist
```

For a build made with `--publish`, retry the private output directory printed by that command instead of assuming it is `dist`. I keep the checked archive and `SHA256SUMS` together; a failed build can leave older files, so I do not publish merely because an archive exists.

## Install

Extract the package into a new directory on your compatible ARM64 Linux device. Copy `exefs/` and the merged `romfs/` from your complete 1.4.0 dump into `data/`, then run `./mhgurecomp`. The release includes neither a dump nor a bonus donor save. You can also add `mhgurecomp` to Steam as a non-Steam game without a compatibility layer. I have used it this way on ArmadaOS.

### Files and saves

- Settings: `mhgurecomp.ini`, generated beside the executable on first start.
- Mods, cheats, screenshots and shader caches: `mods/`, `cheats/`, `shots/` and `cache/` beside the executable in the normal standalone layout.
- Saves: `$XDG_DATA_HOME/MHGURecomp/save/`, or `~/.local/share/MHGURecomp/save/` by default. In 0.14.0, **Menu Options > Save folder** selects another folder containing `save_0`. Back up and copy existing saves yourself, then save settings and restart. See [save folders](docs/SETTINGS_UI.md#save-folder). Custom environment overrides can change the normal locations.
- To import your own save, close the game, back up the destination and copy `system` and `system_backup` into the save directory's `save_0/`. Keep a backup before using mods, cheats or bonus donors.
- Diagnostics: `log.txt` for non-terminal launches, or terminal output when started interactively. Do not publish saves, dumps or unredacted logs.

## Manual updates

I do not build or ship a binary updater. The legacy **Updates** key is ignored. To update, download an ARM64 package from this fork's Releases page, back up saves and extract it into a new directory. Reuse your own game files and copy only the settings/mods you want to keep. Saves normally stay in the user-data location above, separate from the extraction directory.

## Maintenance

Automation checks for published stable upstream releases every hour and merges compatible releases into `master` only after full ARM64 validation. An unchanged release does not start another build. Normal fork edits run quick checks. Outside upstream updates, full Docker/QEMU validation runs only when requested manually.

[Maintenance](docs/MAINTAINING.md) · [Device requirements and troubleshooting](docs/BUILD-LINUX-ARM64.md) · [Settings](docs/SETTINGS_UI.md)

## License

[MIT](LICENSE), with [third-party notices](THIRD_PARTY_NOTICES). Game files and recompiled game code are not covered by this license. Not affiliated with Capcom or Nintendo.
